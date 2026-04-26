import datetime as dt
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from concertpvr.main import create_app
from concertpvr.models import Recording, Stream


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CPVR_DATA_DIR", str(tmp_path))
    with TestClient(create_app()) as c:
        yield c


def _seed_recording(client) -> int:
    db = client.app.state.db
    with db.session() as s:
        stream = Stream(kind="live", youtube_id="x", url="u", title="t", channel_name="c")
        s.add(stream)
        s.flush()
        rec = Recording(
            stream_id=stream.id,
            started_at=dt.datetime(2026, 4, 12, 14, 0, tzinfo=dt.UTC),
            path="/buf/1", is_buffer=True,
        )
        s.add(rec)
        s.flush()
        return rec.id


def test_post_setlist_replaces_all(client):
    rid = _seed_recording(client)
    r = client.post(f"/api/recordings/{rid}/setlist", json={
        "entries": [
            {"artist": "Phoebe Bridgers", "start_s": 21, "end_s": 94},
            {"artist": "Goose", "start_s": 100, "end_s": 200},
        ],
    })
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 2

    r2 = client.post(f"/api/recordings/{rid}/setlist", json={
        "entries": [{"artist": "Tame Impala", "start_s": 5, "end_s": 10}],
    })
    assert r2.status_code == 200
    assert len(r2.json()) == 1


def test_post_setlist_paste_parses_text(client):
    rid = _seed_recording(client)
    paste = (Path(__file__).parent / "fixtures" / "setlist_paste.txt").read_text(encoding="utf-8")
    r = client.post(
        f"/api/recordings/{rid}/setlist/paste",
        content=paste,
        headers={"content-type": "text/plain"},
    )
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 4


def test_get_setlist(client):
    rid = _seed_recording(client)
    client.post(f"/api/recordings/{rid}/setlist", json={
        "entries": [{"artist": "Goose", "start_s": 1, "end_s": 2}],
    })
    r = client.get(f"/api/recordings/{rid}/setlist")
    assert r.status_code == 200
    assert r.json()[0]["artist"] == "Goose"


def test_post_setlist_404_for_unknown_recording(client):
    r = client.post("/api/recordings/9999/setlist", json={"entries": []})
    assert r.status_code == 404


def test_post_paste_400_on_unparseable(client):
    rid = _seed_recording(client)
    r = client.post(
        f"/api/recordings/{rid}/setlist/paste",
        content="absolute nonsense line",
        headers={"content-type": "text/plain"},
    )
    assert r.status_code == 400
