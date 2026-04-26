import datetime as dt
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
        youtube_id="phish-x", url="https://www.youtube.com/watch?v=phish-x",
        title="Phish — Dick's Night 2", channel_name="Phish",
        is_live=True, thumbnail_url=None,
    )

    async def _async_probe(_url):
        return info

    with patch("concertpvr.api.schedules.probe", side_effect=_async_probe) as m, \
         patch("concertpvr.api.streams.probe", side_effect=_async_probe):
        yield m, info


def test_post_schedule_with_url_creates_stream_and_schedule(client, fake_probe):
    _, info = fake_probe
    starts = dt.datetime(2099, 5, 1, 19, 0, tzinfo=dt.timezone.utc)
    ends = dt.datetime(2099, 5, 1, 21, 0, tzinfo=dt.timezone.utc)
    r = client.post("/api/schedules", json={
        "url": info.url,
        "starts_at": starts.isoformat(),
        "ends_at": ends.isoformat(),
        "artist": "Phish",
    })
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "pending"
    assert body["artist"] == "Phish"
    assert body["recording_id"] is None
    assert body["stream_id"] is not None


def test_post_schedule_with_existing_stream_id(client, fake_probe):
    _, info = fake_probe
    s = client.post("/api/streams", json={"url": info.url}).json()
    starts = dt.datetime(2099, 5, 1, 19, 0, tzinfo=dt.timezone.utc)
    ends = dt.datetime(2099, 5, 1, 21, 0, tzinfo=dt.timezone.utc)

    with patch("concertpvr.api.schedules.probe") as no_probe:
        r = client.post("/api/schedules", json={
            "stream_id": s["id"],
            "starts_at": starts.isoformat(),
            "ends_at": ends.isoformat(),
        })
    assert r.status_code == 201
    assert r.json()["stream_id"] == s["id"]
    no_probe.assert_not_called()


def test_post_schedule_rejects_when_neither_url_nor_stream_id(client):
    starts = dt.datetime(2099, 5, 1, 19, 0, tzinfo=dt.timezone.utc)
    ends = dt.datetime(2099, 5, 1, 21, 0, tzinfo=dt.timezone.utc)
    r = client.post("/api/schedules", json={
        "starts_at": starts.isoformat(),
        "ends_at": ends.isoformat(),
    })
    assert r.status_code == 422


def test_post_schedule_rejects_when_ends_before_starts(client, fake_probe):
    _, info = fake_probe
    starts = dt.datetime(2099, 5, 1, 21, 0, tzinfo=dt.timezone.utc)
    ends = dt.datetime(2099, 5, 1, 19, 0, tzinfo=dt.timezone.utc)
    r = client.post("/api/schedules", json={
        "url": info.url,
        "starts_at": starts.isoformat(),
        "ends_at": ends.isoformat(),
    })
    assert r.status_code == 400


def test_get_schedules_lists(client, fake_probe):
    _, info = fake_probe
    starts = dt.datetime(2099, 5, 1, 19, 0, tzinfo=dt.timezone.utc)
    ends = dt.datetime(2099, 5, 1, 21, 0, tzinfo=dt.timezone.utc)
    client.post("/api/schedules", json={
        "url": info.url, "starts_at": starts.isoformat(), "ends_at": ends.isoformat(),
    })
    r = client.get("/api/schedules")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1


def test_get_schedule_by_id(client, fake_probe):
    _, info = fake_probe
    starts = dt.datetime(2099, 5, 1, 19, 0, tzinfo=dt.timezone.utc)
    ends = dt.datetime(2099, 5, 1, 21, 0, tzinfo=dt.timezone.utc)
    created = client.post("/api/schedules", json={
        "url": info.url, "starts_at": starts.isoformat(), "ends_at": ends.isoformat(),
    }).json()
    r = client.get(f"/api/schedules/{created['id']}")
    assert r.status_code == 200
    assert r.json()["id"] == created["id"]


def test_patch_schedule_updates_artist_and_times(client, fake_probe):
    _, info = fake_probe
    starts = dt.datetime(2099, 5, 1, 19, 0, tzinfo=dt.timezone.utc)
    ends = dt.datetime(2099, 5, 1, 21, 0, tzinfo=dt.timezone.utc)
    created = client.post("/api/schedules", json={
        "url": info.url, "starts_at": starts.isoformat(), "ends_at": ends.isoformat(),
    }).json()

    new_starts = dt.datetime(2099, 5, 1, 20, 0, tzinfo=dt.timezone.utc)
    r = client.patch(f"/api/schedules/{created['id']}", json={
        "starts_at": new_starts.isoformat(),
        "artist": "Trey Anastasio Band",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["starts_at"].startswith("2099-05-01T20:00")
    assert body["artist"] == "Trey Anastasio Band"


def test_delete_schedule(client, fake_probe):
    _, info = fake_probe
    starts = dt.datetime(2099, 5, 1, 19, 0, tzinfo=dt.timezone.utc)
    ends = dt.datetime(2099, 5, 1, 21, 0, tzinfo=dt.timezone.utc)
    created = client.post("/api/schedules", json={
        "url": info.url, "starts_at": starts.isoformat(), "ends_at": ends.isoformat(),
    }).json()
    r = client.delete(f"/api/schedules/{created['id']}")
    assert r.status_code == 204
    r = client.get(f"/api/schedules/{created['id']}")
    assert r.status_code == 404
