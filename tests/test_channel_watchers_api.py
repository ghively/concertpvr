from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from concertpvr.main import create_app
from concertpvr.ytdlp_channels import ChannelInfo


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

    with patch("concertpvr.api.channel_watchers.probe_channel",
               side_effect=_async_probe) as m:
        yield m, info


def test_post_creates_watcher_with_probed_metadata(client, fake_probe):
    _, info = fake_probe
    r = client.post("/api/channel-watchers", json={
        "channel_url": "https://www.youtube.com/@nprmusic",
        "title_filter": "tiny desk",
        "retention_days": 14,
    })
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
        r = client.post("/api/channel-watchers",
                        json={"channel_url": "https://www.youtube.com/@bad"})
    assert r.status_code == 400


def test_post_rejects_duplicate_url(client, fake_probe):
    body = {"channel_url": "https://www.youtube.com/@nprmusic"}
    assert client.post("/api/channel-watchers", json=body).status_code == 201
    assert client.post("/api/channel-watchers", json=body).status_code == 409


def test_get_lists_watchers(client, fake_probe):
    client.post("/api/channel-watchers",
                json={"channel_url": "https://www.youtube.com/@nprmusic"})
    r = client.get("/api/channel-watchers")
    assert r.status_code == 200
    assert len(r.json()) == 1


def test_patch_updates_filter_and_enabled(client, fake_probe):
    created = client.post("/api/channel-watchers",
                          json={"channel_url": "https://www.youtube.com/@nprmusic"}).json()
    r = client.patch(f"/api/channel-watchers/{created['id']}",
                     json={"title_filter": "session", "enabled": False})
    assert r.status_code == 200
    body = r.json()
    assert body["title_filter"] == "session"
    assert body["enabled"] is False


def test_delete_watcher(client, fake_probe):
    created = client.post("/api/channel-watchers",
                          json={"channel_url": "https://www.youtube.com/@nprmusic"}).json()
    r = client.delete(f"/api/channel-watchers/{created['id']}")
    assert r.status_code == 204
    r = client.get(f"/api/channel-watchers/{created['id']}")
    assert r.status_code == 404


def test_polling_job_is_registered(client):
    sched = client.app.state.scheduler
    job_ids = {j.id for j in sched.get_jobs()}
    assert "channel_poller" in job_ids
