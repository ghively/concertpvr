"""Slow-refresh cancellation + resumption (v0.4)."""

from unittest.mock import patch

import pytest

from concertpvr.backlog_cache import (
    fetch_full_channel_with_views,
    request_cancel,
)
from concertpvr.db import Database
from concertpvr.models import Base, ChannelBacklogCache, ChannelWatcher
from concertpvr.ytdlp_channels import ProbeResult


@pytest.fixture
def db(tmp_path):
    d = Database(f"sqlite:///{tmp_path / 'c.db'}")
    Base.metadata.create_all(d.engine)
    return d


def _seed_watcher(db: Database) -> int:
    with db.session() as s:
        w = ChannelWatcher(channel_url="https://youtube.com/@cancel", channel_name="Cancel")
        s.add(w)
        s.flush()
        return w.id


def _seed_cache_with_items(db: Database, watcher_id: int, n_items: int) -> None:
    with db.session() as s:
        existing = s.get(ChannelBacklogCache, watcher_id)
        if existing is not None:
            s.delete(existing)
            s.flush()
        cache = ChannelBacklogCache(
            watcher_id=watcher_id,
            status="complete",
            items_json=[{"youtube_id": f"v{i}", "duration_s": 10} for i in range(n_items)],
        )
        s.add(cache)


@pytest.mark.asyncio
async def test_cancel_request_stops_loop_after_next_batch(db: Database) -> None:
    """Refresh batches 5 items at a time. Cancel after batch 1 → progress halts."""
    watcher_id = _seed_watcher(db)
    _seed_cache_with_items(db, watcher_id, 25)

    probe_call_count = 0

    async def slow_probe(yid, **kwargs):
        nonlocal probe_call_count
        probe_call_count += 1
        # After the first batch (BATCH_SIZE=20), request cancel
        if probe_call_count == 1:
            request_cancel(watcher_id)
        return ProbeResult(yid, 100 + probe_call_count)

    async def mock_flat_impl(d, wid):
        # cache already seeded — flat refresh wipes view_counts but the
        # already-seeded cache lacks view_counts so the slow-refresh is
        # effectively the only path that fills them.
        return 25

    with (
        patch("concertpvr.backlog_cache.fetch_full_channel", side_effect=mock_flat_impl),
        patch("concertpvr.ytdlp_channels.probe_video_metadata", side_effect=slow_probe),
    ):
        await fetch_full_channel_with_views(db, watcher_id)

    with db.session() as s:
        cache = s.get(ChannelBacklogCache, watcher_id)
        assert cache is not None
        assert cache.status == "cancelled"
        # Some items have view_counts (the first batch), some don't.
        items = cache.items_json
        assert items is not None
        with_views = [it for it in items if isinstance(it.get("view_count"), int)]
        assert 0 < len(with_views) < 25, "should have partial progress, not zero, not all"


@pytest.mark.asyncio
async def test_resume_skips_already_probed_items(db: Database) -> None:
    """Second call to slow-refresh after cancel preserves view_counts and finishes."""
    watcher_id = _seed_watcher(db)

    # Seed a cache that already has view_counts on the first 5 items
    # and status='cancelled'.
    with db.session() as s:
        existing = s.get(ChannelBacklogCache, watcher_id)
        if existing is not None:
            s.delete(existing)
            s.flush()
        items = []
        for i in range(10):
            it = {"youtube_id": f"v{i}", "duration_s": 10}
            if i < 5:
                it["view_count"] = 999
            items.append(it)
        cache = ChannelBacklogCache(
            watcher_id=watcher_id,
            status="cancelled",
            items_json=items,
            progress_pct=50,
        )
        s.add(cache)

    probe_calls = []

    async def fake_probe(yid, **kwargs):
        probe_calls.append(yid)
        return ProbeResult(yid, 200)

    # fetch_full_channel should NOT be called since we're resuming
    flat_call_count = 0

    async def mock_flat_impl(d, wid):
        nonlocal flat_call_count
        flat_call_count += 1
        return 10

    with (
        patch("concertpvr.backlog_cache.fetch_full_channel", side_effect=mock_flat_impl),
        patch("concertpvr.ytdlp_channels.probe_video_metadata", side_effect=fake_probe),
    ):
        await fetch_full_channel_with_views(db, watcher_id)

    # flat extract was skipped (resumption path)
    assert flat_call_count == 0
    # only the un-probed items got new probes
    assert sorted(probe_calls) == [f"v{i}" for i in range(5, 10)]

    with db.session() as s:
        cache = s.get(ChannelBacklogCache, watcher_id)
        assert cache is not None
        assert cache.status == "complete"
        assert cache.progress_pct == 100
        # Earlier items keep their original view_count (999), new items get 200
        items = cache.items_json
        for it in items[:5]:
            assert it["view_count"] == 999
        for it in items[5:]:
            assert it["view_count"] == 200
