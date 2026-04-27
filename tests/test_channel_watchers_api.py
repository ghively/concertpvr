import datetime as _dt
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from concertpvr.main import create_app
from concertpvr.ytdlp_channels import BroadcastInfo, ChannelInfo


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CPVR_DATA_DIR", str(tmp_path))
    with TestClient(create_app()) as c:
        yield c


@pytest.fixture
def fake_probe():
    info = ChannelInfo(
        channel_name="NPR Music",
        canonical_url="https://www.youtube.com/@nprmusic/streams",
        avatar_url="https://example.com/avatar.jpg",
    )

    async def _async_probe(_url):
        return info

    with patch("concertpvr.api.channel_watchers.probe_channel", side_effect=_async_probe) as m:
        yield m, info


def test_post_creates_watcher_with_probed_metadata(client, fake_probe):
    _, info = fake_probe
    r = client.post(
        "/api/channel-watchers",
        json={
            "channel_url": "https://www.youtube.com/@nprmusic",
            "title_filter": "tiny desk",
            "retention_days": 14,
        },
    )
    assert r.status_code == 201
    body = r.json()
    assert body["channel_name"] == "NPR Music"
    assert body["avatar_url"] == "https://example.com/avatar.jpg"
    assert body["title_filter"] == "tiny desk"
    assert body["retention_days"] == 14
    assert body["enabled"] is True


def test_post_rejects_when_probe_fails(client):
    from concertpvr.ytdlp_channels import ChannelProbeError

    async def _raise(_url):
        raise ChannelProbeError("not a channel")

    with patch("concertpvr.api.channel_watchers.probe_channel", side_effect=_raise):
        r = client.post(
            "/api/channel-watchers", json={"channel_url": "https://www.youtube.com/@bad"}
        )
    assert r.status_code == 400


def test_post_rejects_duplicate_url(client, fake_probe):
    body = {"channel_url": "https://www.youtube.com/@nprmusic"}
    assert client.post("/api/channel-watchers", json=body).status_code == 201
    assert client.post("/api/channel-watchers", json=body).status_code == 409


def test_get_lists_watchers(client, fake_probe):
    client.post("/api/channel-watchers", json={"channel_url": "https://www.youtube.com/@nprmusic"})
    r = client.get("/api/channel-watchers")
    assert r.status_code == 200
    assert len(r.json()) == 1


def test_patch_updates_filter_and_enabled(client, fake_probe):
    created = client.post(
        "/api/channel-watchers", json={"channel_url": "https://www.youtube.com/@nprmusic"}
    ).json()
    r = client.patch(
        f"/api/channel-watchers/{created['id']}", json={"title_filter": "session", "enabled": False}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["title_filter"] == "session"
    assert body["enabled"] is False


def test_delete_watcher(client, fake_probe):
    created = client.post(
        "/api/channel-watchers", json={"channel_url": "https://www.youtube.com/@nprmusic"}
    ).json()
    r = client.delete(f"/api/channel-watchers/{created['id']}")
    assert r.status_code == 204
    r = client.get(f"/api/channel-watchers/{created['id']}")
    assert r.status_code == 404


def test_polling_job_is_registered(client):
    sched = client.app.state.scheduler
    job_ids = {j.id for j in sched.get_jobs()}
    assert "channel_poller" in job_ids


def _make_broadcast_items() -> list[BroadcastInfo]:
    return [
        BroadcastInfo(
            youtube_id="vid_aaa",
            url="https://www.youtube.com/watch?v=vid_aaa",
            title="Concert A",
            channel_name="NPR Music",
            is_live=False,
            upload_date=_dt.date(2025, 3, 1),
            duration_s=3600,
            thumbnail_url="https://example.com/thumb_a.jpg",
        ),
        BroadcastInfo(
            youtube_id="vid_bbb",
            url="https://www.youtube.com/watch?v=vid_bbb",
            title="Concert B",
            channel_name="NPR Music",
            is_live=False,
            upload_date=_dt.date(2025, 2, 1),
            duration_s=1800,
            thumbnail_url=None,
        ),
    ]


def test_get_backlog_404_for_unknown_watcher(client):
    with patch(
        "concertpvr.api.channel_watchers.list_recent_uploads",
        new=AsyncMock(return_value=[]),
    ):
        r = client.get("/api/channel-watchers/9999/backlog")
    assert r.status_code == 404


def test_get_backlog_marks_existing_streams_as_downloaded(client, fake_probe):
    # Create the watcher
    created = client.post(
        "/api/channel-watchers", json={"channel_url": "https://www.youtube.com/@nprmusic"}
    ).json()
    wid = created["id"]

    # Seed a Stream with youtube_id "vid_aaa" into the DB
    from concertpvr.models import Stream

    with client.app.state.db.session() as s:
        stream = Stream(
            kind="video",
            youtube_id="vid_aaa",
            url="https://www.youtube.com/watch?v=vid_aaa",
            title="Concert A",
            channel_name="NPR Music",
            thumbnail_url=None,
        )
        s.add(stream)
        s.flush()

    items = _make_broadcast_items()
    with patch(
        "concertpvr.api.channel_watchers.list_recent_uploads",
        new=AsyncMock(return_value=items),
    ):
        r = client.get(f"/api/channel-watchers/{wid}/backlog")

    assert r.status_code == 200
    body = r.json()
    assert len(body) == 2
    state_by_id = {item["youtube_id"]: item["state"] for item in body}
    assert state_by_id["vid_aaa"] == "downloaded"
    assert state_by_id["vid_bbb"] == "not_downloaded"


def test_post_backlog_download_creates_recordings_and_enqueues(client, fake_probe, monkeypatch):
    # Create the watcher
    created = client.post(
        "/api/channel-watchers", json={"channel_url": "https://www.youtube.com/@nprmusic"}
    ).json()
    wid = created["id"]

    # Set up fake vod_queue
    fake_queue = MagicMock()
    fake_queue.enqueue = AsyncMock()
    fake_queue.stop = AsyncMock()
    monkeypatch.setattr(client.app.state, "vod_queue", fake_queue)

    from concertpvr.ytdlp import StreamInfo

    def _make_probe(yid: str) -> StreamInfo:
        return StreamInfo(
            youtube_id=yid,
            url=f"https://www.youtube.com/watch?v={yid}",
            title=f"Video {yid}",
            channel_name="NPR Music",
            is_live=False,
            thumbnail_url=None,
        )

    async def _probe(url: str, **kw: object) -> StreamInfo:
        yid = url.split("v=")[-1]
        return _make_probe(yid)

    with patch("concertpvr.api.channel_watchers.probe", side_effect=_probe):
        r = client.post(
            f"/api/channel-watchers/{wid}/backlog/download",
            json={"video_ids": ["vid_xxx", "vid_yyy"]},
        )

    assert r.status_code == 201
    body = r.json()
    rec_ids = body["queued_recording_ids"]
    assert len(rec_ids) == 2
    assert fake_queue.enqueue.await_count == 2

    # Verify recordings have auto_publish_after_download=False
    from sqlalchemy import select

    from concertpvr.models import Recording

    with client.app.state.db.session() as s:
        recs = list(s.scalars(select(Recording).where(Recording.id.in_(rec_ids))))
        assert all(r.auto_publish_after_download is False for r in recs)
