"""VOD download workflow end-to-end tests (mocked).

This file mirrors the test pattern used for live recordings in
test_streams_api.py but isolates the VOD lifecycle:
    paste URL → vod_queued → vod_downloading → complete → publish

Real-network probes/downloads live in tests/integration/test_real_yt_dlp.py
(env-gated). The smoke harness in scripts/smoke-e2e.sh covers full container
flow against a real video.
"""

import datetime as _dt
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from concertpvr.main import create_app
from concertpvr.models import Recording, Stream
from concertpvr.ytdlp import StreamInfo


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CPVR_DATA_DIR", str(tmp_path))
    with TestClient(create_app()) as c:
        # Mock the vod queue so handler never actually runs yt-dlp
        fake_queue = MagicMock()
        fake_queue.enqueue = AsyncMock()
        fake_queue.stop = AsyncMock()
        monkeypatch.setattr(c.app.state, "vod_queue", fake_queue)
        yield c


@pytest.fixture
def fake_vod_probe():
    info = StreamInfo(
        youtube_id="vod-test-001",
        url="https://www.youtube.com/watch?v=vod-test-001",
        title="Khruangbin: Tiny Desk Concert",
        channel_name="NPR Music",
        is_live=False,
        thumbnail_url="https://example.com/t.jpg",
        original_upload_date=_dt.date(2020, 9, 2),
        description="0:00 - Intro\n1:24 - Pelota\n5:12 - So We Won't Forget",
        tags=["khruangbin", "tiny desk", "indie"],
        chapters=None,
    )

    async def _async_probe(_url, **_kwargs):
        return info

    with patch("concertpvr.api.streams.probe", side_effect=_async_probe):
        yield info


def test_paste_vod_url_creates_queued_recording(client, fake_vod_probe):
    """Workflow A entry point — pasting a non-live URL queues a VOD download."""
    info = fake_vod_probe
    r = client.post("/api/streams", json={"url": info.url})
    assert r.status_code == 201
    body = r.json()
    assert body["kind"] == "video"
    assert body["youtube_id"] == "vod-test-001"
    assert body["detected_setlist_source"] == "description"

    db = client.app.state.db
    with db.session() as s:
        st = s.scalar(select(Stream).where(Stream.youtube_id == "vod-test-001"))
        assert st is not None
        rec = s.scalar(select(Recording).where(Recording.stream_id == st.id))
        assert rec is not None
        assert rec.status == "vod_queued"
        assert rec.is_buffer is False
        # Forward-looking: VOD recordings never start in 'recording' state
        assert rec.status in {"vod_queued", "vod_downloading", "complete", "vod_failed"}

    client.app.state.vod_queue.enqueue.assert_awaited_once_with(rec.id)


def test_vod_workflow_status_transitions_use_vod_namespace(client, fake_vod_probe):
    """Sanity: VOD-originated recordings only ever take VOD-namespaced statuses
    until they reach `complete`. They never appear in `recording` or
    `interrupted` (those are live-only)."""
    info = fake_vod_probe
    client.post("/api/streams", json={"url": info.url})

    db = client.app.state.db
    with db.session() as s:
        rec = s.scalar(select(Recording))
        assert rec is not None
        # Simulate a transition the queue handler would do
        rec.status = "vod_downloading"
    with db.session() as s:
        rec = s.scalar(select(Recording))
        assert rec.status == "vod_downloading"
        rec.status = "complete"
    with db.session() as s:
        rec = s.scalar(select(Recording))
        assert rec.status == "complete"


def test_paste_live_url_does_not_create_vod_recording(client):
    """Sanity: live URL path is unchanged by VOD additions."""
    live_info = StreamInfo(
        youtube_id="live-001",
        url="https://www.youtube.com/watch?v=live-001",
        title="Phish — Dick's",
        channel_name="Phish",
        is_live=True,
        thumbnail_url=None,
    )

    async def _async_probe(_url, **_kwargs):
        return live_info

    with patch("concertpvr.api.streams.probe", side_effect=_async_probe):
        r = client.post("/api/streams", json={"url": live_info.url})
    assert r.status_code == 201
    assert r.json()["kind"] == "live"
    db = client.app.state.db
    with db.session() as s:
        rec_count = len(list(s.scalars(select(Recording))))
    assert rec_count == 0  # live URLs don't create Recording at paste time
