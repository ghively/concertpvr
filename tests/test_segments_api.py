import datetime as dt
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from concertpvr.main import create_app
from concertpvr.models import Recording, Stream

FIXTURE = Path(__file__).parent / "fixtures" / "tiny.mp4"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CPVR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CPVR_PUBLISH_DIR", str(tmp_path / "media"))
    with TestClient(create_app()) as c:
        yield c


def _seed_recording(client) -> int:
    db = client.app.state.db
    with db.session() as s:
        stream = Stream(
            kind="live",
            youtube_id="x",
            url="u",
            title="Coachella — Mojave",
            channel_name="Coachella",
        )
        s.add(stream)
        s.flush()
        rec = Recording(
            stream_id=stream.id,
            started_at=dt.datetime(2026, 4, 12, 14, 0, tzinfo=dt.UTC),
            path=str(FIXTURE),
            is_buffer=False,
            status="complete",
        )
        s.add(rec)
        s.flush()
        return rec.id


def test_post_segment_creates_draft(client):
    rid = _seed_recording(client)
    r = client.post(
        "/api/segments",
        json={
            "recording_id": rid,
            "artist": "Phoebe Bridgers",
            "title": "Mojave Set",
            "start_s": 0,
            "end_s": 2,
            "source": "manual",
        },
    )
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "draft"
    assert body["artist"] == "Phoebe Bridgers"


def test_post_segment_rejects_when_end_before_start(client):
    rid = _seed_recording(client)
    r = client.post(
        "/api/segments",
        json={
            "recording_id": rid,
            "artist": "X",
            "start_s": 100,
            "end_s": 50,
            "source": "manual",
        },
    )
    assert r.status_code == 400


def test_get_segments_filter_by_recording(client):
    rid = _seed_recording(client)
    client.post(
        "/api/segments",
        json={
            "recording_id": rid,
            "artist": "A",
            "start_s": 0,
            "end_s": 1,
            "source": "manual",
        },
    )
    client.post(
        "/api/segments",
        json={
            "recording_id": rid,
            "artist": "B",
            "start_s": 1,
            "end_s": 2,
            "source": "manual",
        },
    )
    r = client.get(f"/api/segments?recording_id={rid}")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 2
    assert {row["artist"] for row in body} == {"A", "B"}


def test_patch_segment_updates_times(client):
    rid = _seed_recording(client)
    created = client.post(
        "/api/segments",
        json={
            "recording_id": rid,
            "artist": "X",
            "start_s": 0,
            "end_s": 1,
            "source": "manual",
        },
    ).json()
    r = client.patch(f"/api/segments/{created['id']}", json={"start_s": 1, "end_s": 2})
    assert r.status_code == 200
    assert r.json()["start_s"] == 1


def test_delete_segment(client):
    rid = _seed_recording(client)
    created = client.post(
        "/api/segments",
        json={
            "recording_id": rid,
            "artist": "X",
            "start_s": 0,
            "end_s": 1,
            "source": "manual",
        },
    ).json()
    r = client.delete(f"/api/segments/{created['id']}")
    assert r.status_code == 204


def test_publish_segment(client, tmp_path):
    rid = _seed_recording(client)
    seg = client.post(
        "/api/segments",
        json={
            "recording_id": rid,
            "artist": "Phoebe Bridgers",
            "start_s": 0,
            "end_s": 2,
            "source": "manual",
        },
    ).json()

    r = client.post(
        f"/api/segments/{seg['id']}/publish",
        json={"festival": "Coachella W1", "venue": "Mojave", "year": 2026},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "published"
    assert body["emby_path"] is not None

    emby_path = Path(body["emby_path"])
    assert emby_path.is_dir()
    assert (emby_path / "movie.nfo").exists()


def test_list_segments_filter_by_status(client):
    rid = _seed_recording(client)
    client.post(
        "/api/segments",
        json={
            "recording_id": rid,
            "artist": "A",
            "start_s": 0,
            "end_s": 1,
            "source": "manual",
        },
    )
    r = client.get("/api/segments?status=draft")
    assert r.status_code == 200
    body = r.json()
    assert all(row["status"] == "draft" for row in body)
