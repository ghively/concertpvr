"""DVR-pull endpoint (v0.4.1)."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from concertpvr.main import create_app
from concertpvr.models import Recording, Stream


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CPVR_DATA_DIR", str(tmp_path))
    with TestClient(create_app()) as c:
        # Mock the queue so dvr-pull's enqueue is captured but doesn't actually run yt-dlp
        mock_q = MagicMock()
        mock_q.enqueue = AsyncMock()
        mock_q.stop = AsyncMock()
        c.app.state.vod_queue = mock_q
        yield c


def _seed_stream(client, kind: str = "live") -> int:
    db = client.app.state.db
    with db.session() as s:
        st = Stream(kind=kind, youtube_id="livestream-001", url="u", title="t", channel_name="c")
        s.add(st)
        s.flush()
        return st.id


def test_dvr_pull_creates_recording_with_dvr_prefix_and_enqueues(client):
    sid = _seed_stream(client, kind="live")
    r = client.post(f"/api/streams/{sid}/dvr-pull")
    assert r.status_code == 201
    body = r.json()
    rec_id = body["recording_id"]

    db = client.app.state.db
    with db.session() as s:
        rec = s.get(Recording, rec_id)
        assert rec is not None
        assert rec.status == "vod_queued"
        # Discriminator: filename prefix tells the handler to use --live-from-start
        assert "/dvr-livestream-001." in rec.path or rec.path.endswith("dvr-livestream-001.%(ext)s")

    client.app.state.vod_queue.enqueue.assert_awaited_once_with(rec_id)


def test_dvr_pull_rejects_video_kind(client):
    sid = _seed_stream(client, kind="video")
    r = client.post(f"/api/streams/{sid}/dvr-pull")
    assert r.status_code == 409
    body = r.json()
    assert "live" in body["detail"]


def test_dvr_pull_unknown_stream_returns_404(client):
    r = client.post("/api/streams/99999/dvr-pull")
    assert r.status_code == 404


def test_dvr_pull_reuses_vod_pipeline(client):
    """A DVR pull is a Recording with status vod_queued — same pipeline as VODs."""
    sid = _seed_stream(client, kind="live")
    client.post(f"/api/streams/{sid}/dvr-pull")

    db = client.app.state.db
    with db.session() as s:
        rec = s.scalar(select(Recording).where(Recording.stream_id == sid))
        assert rec is not None
        assert rec.is_buffer is False
        # No auto-publish — DVR pulls are explicit user actions.
        assert rec.auto_publish_after_download is False
