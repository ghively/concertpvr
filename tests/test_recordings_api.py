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
