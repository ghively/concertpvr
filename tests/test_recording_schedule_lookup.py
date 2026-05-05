"""GET /api/recordings/{id}/schedule reverse-lookup (v0.4)."""

import datetime as dt

import pytest
from fastapi.testclient import TestClient

from concertpvr.main import create_app
from concertpvr.models import Recording, Schedule, Stream


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CPVR_DATA_DIR", str(tmp_path))
    with TestClient(create_app()) as c:
        yield c


def _seed(client, *, schedule_links_recording: bool) -> tuple[int, int]:
    """Returns (recording_id, schedule_id_or_zero)."""
    db = client.app.state.db
    with db.session() as s:
        st = Stream(kind="live", youtube_id="x", url="u", title="t", channel_name="c")
        s.add(st)
        s.flush()
        rec = Recording(
            stream_id=st.id,
            started_at=dt.datetime(2026, 5, 1, 12, 0, tzinfo=dt.UTC),
            path="/tmp/x",
            status="complete",
            is_buffer=False,
        )
        s.add(rec)
        s.flush()

        sched_id = 0
        if schedule_links_recording:
            sched = Schedule(
                stream_id=st.id,
                starts_at=dt.datetime(2026, 5, 1, 12, 0, tzinfo=dt.UTC),
                ends_at=dt.datetime(2026, 5, 1, 13, 0, tzinfo=dt.UTC),
                artist="Test Artist",
                status="complete",
                recording_id=rec.id,
            )
            s.add(sched)
            s.flush()
            sched_id = sched.id

        return rec.id, sched_id


def test_recording_with_linked_schedule_returns_schedule(client):
    rid, sid = _seed(client, schedule_links_recording=True)
    r = client.get(f"/api/recordings/{rid}/schedule")
    assert r.status_code == 200
    body = r.json()
    assert body is not None
    assert body["id"] == sid
    assert body["recording_id"] == rid
    assert body["artist"] == "Test Artist"


def test_recording_with_no_linked_schedule_returns_null(client):
    rid, _ = _seed(client, schedule_links_recording=False)
    r = client.get(f"/api/recordings/{rid}/schedule")
    assert r.status_code == 200
    assert r.json() is None


def test_unknown_recording_returns_404(client):
    r = client.get("/api/recordings/9999/schedule")
    assert r.status_code == 404
