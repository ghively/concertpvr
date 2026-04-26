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
    with TestClient(create_app()) as c:
        yield c


def _seed(client) -> int:
    db = client.app.state.db
    with db.session() as s:
        stream = Stream(kind="live", youtube_id="x", url="u", title="t", channel_name="c")
        s.add(stream)
        s.flush()
        rec = Recording(
            stream_id=stream.id,
            started_at=dt.datetime(2026, 4, 25, 12, 0, tzinfo=dt.UTC),
            path=str(FIXTURE),
            is_buffer=False,
            status="complete",
        )
        s.add(rec)
        s.flush()
        return rec.id


def test_get_media_returns_full_file(client):
    rid = _seed(client)
    r = client.get(f"/api/recordings/{rid}/media")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("video/")
    assert r.headers.get("accept-ranges") == "bytes"
    assert int(r.headers.get("content-length", "0")) > 0
    assert len(r.content) == FIXTURE.stat().st_size


def test_get_media_supports_range(client):
    rid = _seed(client)
    r = client.get(f"/api/recordings/{rid}/media", headers={"range": "bytes=0-99"})
    assert r.status_code == 206
    assert r.headers.get("content-range", "").startswith("bytes 0-99/")
    assert int(r.headers.get("content-length", "0")) == 100
    assert len(r.content) == 100


def test_get_media_404_for_unknown_recording(client):
    r = client.get("/api/recordings/9999/media")
    assert r.status_code == 404


def test_get_media_404_when_file_missing(client, tmp_path):
    db = client.app.state.db
    with db.session() as s:
        stream = Stream(kind="live", youtube_id="y", url="u", title="t", channel_name="c")
        s.add(stream)
        s.flush()
        rec = Recording(
            stream_id=stream.id,
            started_at=dt.datetime(2026, 4, 25, 12, 0, tzinfo=dt.UTC),
            path=str(tmp_path / "nonexistent.mp4"),
            is_buffer=False,
            status="complete",
        )
        s.add(rec)
        s.flush()
        rid = rec.id

    r = client.get(f"/api/recordings/{rid}/media")
    assert r.status_code == 404


def test_get_media_refuses_to_serve_directory(client, tmp_path):
    rec_dir = tmp_path / "buf"
    rec_dir.mkdir()
    db = client.app.state.db
    with db.session() as s:
        stream = Stream(kind="live", youtube_id="z", url="u", title="t", channel_name="c")
        s.add(stream)
        s.flush()
        rec = Recording(
            stream_id=stream.id,
            started_at=dt.datetime(2026, 4, 25, 12, 0, tzinfo=dt.UTC),
            path=str(rec_dir),
            is_buffer=True,
            status="complete",
        )
        s.add(rec)
        s.flush()
        rid = rec.id

    r = client.get(f"/api/recordings/{rid}/media")
    assert r.status_code == 415
