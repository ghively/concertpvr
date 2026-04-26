import datetime as dt

import pytest
from fastapi.testclient import TestClient

from concertpvr.main import create_app
from concertpvr.models import Recording, Stream


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CPVR_DATA_DIR", str(tmp_path))
    with TestClient(create_app()) as c:
        yield c


def _seed(client, n: int) -> int:
    db = client.app.state.db
    with db.session() as s:
        stream = Stream(kind="live", youtube_id=f"a{n}", url="u", title="t", channel_name="c")
        s.add(stream)
        s.flush()
        for i in range(n):
            s.add(
                Recording(
                    stream_id=stream.id,
                    started_at=dt.datetime(2026, 4, 25, 12, i, tzinfo=dt.UTC),
                    path=f"/buf/{i}",
                    is_buffer=True,
                )
            )
        return stream.id


def test_list_recordings_empty(client):
    r = client.get("/api/recordings")
    assert r.status_code == 200
    assert r.json() == []


def test_list_recordings_returns_all_ordered(client):
    _seed(client, 3)
    r = client.get("/api/recordings")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 3
    starts = [row["started_at"] for row in body]
    assert starts == sorted(starts, reverse=True)


def test_list_recordings_filter_by_stream(client):
    sid = _seed(client, 2)
    _seed(client, 1)
    r = client.get(f"/api/recordings?stream_id={sid}")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 2
    assert all(row["stream_id"] == sid for row in body)


def test_get_recording_by_id(client):
    sid = _seed(client, 1)
    listing = client.get(f"/api/recordings?stream_id={sid}").json()
    rid = listing[0]["id"]
    r = client.get(f"/api/recordings/{rid}")
    assert r.status_code == 200
    assert r.json()["id"] == rid


def test_get_recording_404(client):
    r = client.get("/api/recordings/9999")
    assert r.status_code == 404


import json


def test_finalize_recording_captures_chapters_and_creates_segments(client, tmp_path):
    db = client.app.state.db

    rec_dir = tmp_path / "rec1"
    rec_dir.mkdir()
    (rec_dir / "x.info.json").write_text(json.dumps({
        "chapters": [
            {"title": "Phoebe", "start_time": 0, "end_time": 60},
            {"title": "Goose", "start_time": 60, "end_time": 120},
        ],
    }))

    with db.session() as s:
        from concertpvr.models import Stream
        stream = Stream(kind="live", youtube_id="x", url="u", title="t", channel_name="c")
        s.add(stream)
        s.flush()
        from concertpvr.models import Recording
        rec = Recording(
            stream_id=stream.id,
            started_at=dt.datetime(2026, 4, 25, 12, 0, tzinfo=dt.UTC),
            path=str(rec_dir),
            is_buffer=True,
            status="recording",
        )
        s.add(rec)
        s.flush()
        rid = rec.id

    r = client.post(f"/api/recordings/{rid}/finalize")
    assert r.status_code == 200
    assert r.json()["status"] == "complete"

    segs = client.get(f"/api/segments?recording_id={rid}").json()
    assert len(segs) == 2
    assert {seg["artist"] for seg in segs} == {"Phoebe", "Goose"}
