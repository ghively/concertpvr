from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from concertpvr.main import create_app
from concertpvr.ytdlp import StreamInfo


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CPVR_DATA_DIR", str(tmp_path))
    with TestClient(create_app()) as c:
        yield c


@pytest.fixture
def fake_probe():
    info = StreamInfo(
        youtube_id="dQw4w9WgXcQ",
        url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        title="Coachella 2026",
        channel_name="Coachella",
        is_live=True,
        thumbnail_url="https://example.com/t.jpg",
    )

    async def _async_probe(_url, **_kwargs):
        return info

    with patch("concertpvr.api.streams.probe", side_effect=_async_probe) as m:
        yield m, info


def test_post_streams_probes_and_creates(client, fake_probe):
    mock, info = fake_probe
    r = client.post("/api/streams", json={"url": info.url})
    assert r.status_code == 201
    body = r.json()
    assert body["youtube_id"] == "dQw4w9WgXcQ"
    assert body["title"] == "Coachella 2026"
    assert body["kind"] == "live"
    mock.assert_called_once_with(info.url, cookies_path=None)


def test_post_streams_rejects_duplicate(client, fake_probe):
    _, info = fake_probe
    r1 = client.post("/api/streams", json={"url": info.url})
    assert r1.status_code == 201
    r2 = client.post("/api/streams", json={"url": info.url})
    assert r2.status_code == 409


def test_post_streams_returns_400_on_probe_error(client):
    from concertpvr.ytdlp import ProbeError

    async def _raise(_url, **_kwargs):
        raise ProbeError("video unavailable")

    with patch("concertpvr.api.streams.probe", side_effect=_raise):
        r = client.post("/api/streams", json={"url": "https://www.youtube.com/watch?v=bad"})
    assert r.status_code == 400
    assert "unavailable" in r.json()["detail"].lower()


def test_get_streams_lists(client, fake_probe):
    _, info = fake_probe
    client.post("/api/streams", json={"url": info.url})
    r = client.get("/api/streams")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, list)
    assert len(body) == 1
    assert body[0]["youtube_id"] == "dQw4w9WgXcQ"


def test_get_stream_by_id(client, fake_probe):
    _, info = fake_probe
    created = client.post("/api/streams", json={"url": info.url}).json()
    r = client.get(f"/api/streams/{created['id']}")
    assert r.status_code == 200
    assert r.json()["youtube_id"] == "dQw4w9WgXcQ"


def test_get_stream_404_for_unknown(client):
    r = client.get("/api/streams/9999")
    assert r.status_code == 404


def test_delete_stream(client, fake_probe):
    _, info = fake_probe
    created = client.post("/api/streams", json={"url": info.url}).json()
    r = client.delete(f"/api/streams/{created['id']}")
    assert r.status_code == 204
    r = client.get(f"/api/streams/{created['id']}")
    assert r.status_code == 404


def test_watch_subscription_get_returns_404_when_none(client, fake_probe):
    _, info = fake_probe
    created = client.post("/api/streams", json={"url": info.url}).json()
    r = client.get(f"/api/streams/{created['id']}/watch")
    assert r.status_code == 404


def test_watch_subscription_patch_creates_then_updates(client, fake_probe):
    _, info = fake_probe
    created = client.post("/api/streams", json={"url": info.url}).json()
    sid = created["id"]

    r = client.patch(f"/api/streams/{sid}/watch", json={"enabled": True, "retention_days": 14})
    assert r.status_code == 200
    body = r.json()
    assert body["enabled"] is True
    assert body["retention_days"] == 14

    r = client.patch(f"/api/streams/{sid}/watch", json={"enabled": False})
    assert r.status_code == 200
    body = r.json()
    assert body["enabled"] is False
    assert body["retention_days"] == 14


def test_watch_subscription_patch_404_for_unknown_stream(client):
    r = client.patch("/api/streams/9999/watch", json={"enabled": True})
    assert r.status_code == 404


def test_enabling_watch_starts_recorder(client, fake_probe, monkeypatch):
    """Patching enabled=True should call pool.start with a worker for that stream."""
    from unittest.mock import AsyncMock, MagicMock

    started_workers = []

    async def fake_start(worker):
        started_workers.append(worker)

    fake_pool = MagicMock()
    fake_pool.is_recording = MagicMock(return_value=False)
    fake_pool.start = AsyncMock(side_effect=fake_start)
    fake_pool.stop = AsyncMock()
    monkeypatch.setattr(client.app.state, "pool", fake_pool)

    _, info = fake_probe
    sid = client.post("/api/streams", json={"url": info.url}).json()["id"]
    client.patch(f"/api/streams/{sid}/watch", json={"enabled": True})

    assert len(started_workers) == 1
    assert started_workers[0].stream_id == sid


def test_disabling_watch_stops_recorder(client, fake_probe, monkeypatch):
    from unittest.mock import AsyncMock, MagicMock

    fake_pool = MagicMock()
    # Simulate: not recording before first PATCH, recording after.
    is_recording_calls = iter([False, True])
    fake_pool.is_recording = MagicMock(side_effect=lambda sid: next(is_recording_calls))
    fake_pool.start = AsyncMock()
    fake_pool.stop = AsyncMock()
    monkeypatch.setattr(client.app.state, "pool", fake_pool)

    _, info = fake_probe
    sid = client.post("/api/streams", json={"url": info.url}).json()["id"]
    client.patch(f"/api/streams/{sid}/watch", json={"enabled": True})
    client.patch(f"/api/streams/{sid}/watch", json={"enabled": False})

    fake_pool.stop.assert_awaited_with(sid)


def test_enabling_watch_returns_507_when_pool_at_capacity(client, fake_probe, monkeypatch):
    """If pool.start raises capacity RuntimeError, surface as 507."""
    from unittest.mock import AsyncMock, MagicMock

    fake_pool = MagicMock()
    fake_pool.is_recording = MagicMock(return_value=False)
    fake_pool.start = AsyncMock(side_effect=RuntimeError("recorder pool at capacity (4)"))
    fake_pool.stop = AsyncMock()
    monkeypatch.setattr(client.app.state, "pool", fake_pool)

    _, info = fake_probe
    sid = client.post("/api/streams", json={"url": info.url}).json()["id"]
    r = client.patch(f"/api/streams/{sid}/watch", json={"enabled": True})
    assert r.status_code == 507
    assert "max concurrent" in r.json()["detail"].lower()


def test_list_streams_supports_limit_and_offset(client, fake_probe, monkeypatch):
    """With multiple streams, limit + offset slice the result correctly."""
    from concertpvr.ytdlp import StreamInfo

    info_a = StreamInfo("yidA", "https://a", "A", "c", True, None)
    info_b = StreamInfo("yidB", "https://b", "B", "c", True, None)
    info_c = StreamInfo("yidC", "https://c", "C", "c", True, None)

    from unittest.mock import patch

    async def _seq_probe(url, **_kw):
        return {"https://a": info_a, "https://b": info_b, "https://c": info_c}[url]

    with patch("concertpvr.api.streams.probe", side_effect=_seq_probe):
        client.post("/api/streams", json={"url": "https://a"})
        client.post("/api/streams", json={"url": "https://b"})
        client.post("/api/streams", json={"url": "https://c"})

    r = client.get("/api/streams?limit=2&offset=0")
    assert len(r.json()) == 2
    r = client.get("/api/streams?limit=2&offset=2")
    assert len(r.json()) == 1
    r = client.get("/api/streams")  # default unlimited
    assert len(r.json()) == 3


def test_post_streams_vod_creates_stream_and_queued_recording(client, monkeypatch):
    """Pasting a non-live URL creates Stream(kind=video) + Recording(vod_queued)."""
    from unittest.mock import AsyncMock, MagicMock

    from concertpvr.ytdlp import StreamInfo

    info = StreamInfo(
        youtube_id="vod123",
        url="https://www.youtube.com/watch?v=vod123",
        title="Khruangbin: Tiny Desk Concert",
        channel_name="NPR Music",
        is_live=False,
        thumbnail_url=None,
        description="0:00 - Intro\n1:24 - Pelota\n5:12 - So We Won't Forget",
        tags=["khruangbin", "indie"],
        chapters=None,
        duration_s=1122,
    )

    async def _async_probe(_url, **_kwargs):
        return info

    fake_queue = MagicMock()
    fake_queue.enqueue = AsyncMock()
    fake_queue.stop = AsyncMock()
    monkeypatch.setattr(client.app.state, "vod_queue", fake_queue)

    with patch("concertpvr.api.streams.probe", side_effect=_async_probe):
        r = client.post("/api/streams", json={"url": info.url})
    assert r.status_code == 201
    body = r.json()
    assert body["kind"] == "video"
    assert body["youtube_id"] == "vod123"
    assert body["description"].startswith("0:00")
    assert body["detected_setlist_source"] == "description"

    # Recording was created with vod_queued status
    db = client.app.state.db
    from sqlalchemy import select

    from concertpvr.models import Recording, Stream

    with db.session() as s:
        st = s.scalar(select(Stream).where(Stream.youtube_id == "vod123"))
        rec = s.scalar(select(Recording).where(Recording.stream_id == st.id))
        assert rec is not None
        assert rec.status == "vod_queued"
        assert rec.is_buffer is False

    # Queue.enqueue was called with the new recording id
    fake_queue.enqueue.assert_awaited_once()


def test_post_streams_vod_dedupe_409(client, monkeypatch):
    """Posting the same VOD URL twice returns 201 then 409."""
    from unittest.mock import AsyncMock, MagicMock

    from concertpvr.ytdlp import StreamInfo

    info = StreamInfo(
        youtube_id="dup1",
        url="https://www.youtube.com/watch?v=dup1",
        title="t",
        channel_name="c",
        is_live=False,
        thumbnail_url=None,
    )

    async def _p(_u, **_kw):
        return info

    fake_queue = MagicMock()
    fake_queue.enqueue = AsyncMock()
    fake_queue.stop = AsyncMock()
    monkeypatch.setattr(client.app.state, "vod_queue", fake_queue)

    with patch("concertpvr.api.streams.probe", side_effect=_p):
        r1 = client.post("/api/streams", json={"url": info.url})
        assert r1.status_code == 201
        r2 = client.post("/api/streams", json={"url": info.url})
        assert r2.status_code == 409
