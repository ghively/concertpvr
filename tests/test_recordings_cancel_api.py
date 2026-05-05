"""POST /api/recordings/{id}/cancel — VOD cancellation API."""

import datetime as dt
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from concertpvr.main import create_app
from concertpvr.models import Recording, Stream


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CPVR_DATA_DIR", str(tmp_path))
    with TestClient(create_app()) as c:
        # Replace the live queue with a mock so the API endpoint's call to
        # .cancel() doesn't actually terminate anything. Lifespan teardown
        # awaits .stop() so it must be an AsyncMock.
        mock_q = MagicMock()
        mock_q.cancel = AsyncMock(return_value="queued")
        mock_q.stop = AsyncMock()
        c.app.state.vod_queue = mock_q
        yield c


def _seed_vod(client, status: str) -> int:
    db = client.app.state.db
    with db.session() as s:
        st = Stream(kind="video", youtube_id="abc", url="u", title="t", channel_name="c")
        s.add(st)
        s.flush()
        rec = Recording(
            stream_id=st.id,
            started_at=dt.datetime.now(dt.UTC),
            path="/tmp/x",
            status=status,
            is_buffer=False,
        )
        s.add(rec)
        s.flush()
        return rec.id


def test_cancel_queued_recording_calls_queue_cancel(client):
    rid = _seed_vod(client, "vod_queued")
    r = client.post(f"/api/recordings/{rid}/cancel")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "vod_cancelled"
    client.app.state.vod_queue.cancel.assert_awaited_once_with(rid)


def test_cancel_downloading_recording_calls_queue_cancel(client):
    client.app.state.vod_queue.cancel = AsyncMock(return_value="running")
    rid = _seed_vod(client, "vod_downloading")
    r = client.post(f"/api/recordings/{rid}/cancel")
    assert r.status_code == 200
    body = r.json()
    assert body["previous"] == "running"


def test_cancel_complete_recording_returns_409(client):
    rid = _seed_vod(client, "complete")
    r = client.post(f"/api/recordings/{rid}/cancel")
    assert r.status_code == 409


def test_cancel_failed_recording_returns_409(client):
    rid = _seed_vod(client, "vod_failed")
    r = client.post(f"/api/recordings/{rid}/cancel")
    assert r.status_code == 409


def test_cancel_unknown_recording_returns_404(client):
    r = client.post("/api/recordings/99999/cancel")
    assert r.status_code == 404


def test_cancel_live_recording_returns_409(client):
    """Cancellation only applies to the VOD pipeline; live recordings have a different lifecycle."""
    rid = _seed_vod(client, "recording")
    r = client.post(f"/api/recordings/{rid}/cancel")
    assert r.status_code == 409
