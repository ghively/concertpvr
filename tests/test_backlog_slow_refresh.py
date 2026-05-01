from unittest.mock import patch

import pytest

from concertpvr.backlog_cache import fetch_full_channel_with_views
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
        w = ChannelWatcher(channel_url="https://youtube.com/@test2", channel_name="Test2")
        s.add(w)
        s.flush()
        return w.id


@pytest.mark.asyncio
async def test_slow_refresh(db: Database) -> None:
    watcher_id = _seed_watcher(db)

    async def fake_probe(yid, **kwargs):
        view_counts = {"a": 100, "b": 500, "c": None}
        return ProbeResult(yid, view_counts.get(yid))

    with patch("concertpvr.backlog_cache.fetch_full_channel") as mock_flat:

        async def mock_flat_impl(d, wid):
            with d.session() as s:
                cache = ChannelBacklogCache(
                    watcher_id=wid,
                    status="complete",
                    items_json=[
                        {"youtube_id": "a", "duration_s": 10},
                        {"youtube_id": "b", "duration_s": 20},
                        {"youtube_id": "c", "duration_s": 30},
                    ],
                )
                s.add(cache)
            return 3

        mock_flat.side_effect = mock_flat_impl

        with patch("concertpvr.ytdlp_channels.probe_video_metadata", side_effect=fake_probe):
            await fetch_full_channel_with_views(db, watcher_id)

    with db.session() as s:
        cache = s.get(ChannelBacklogCache, watcher_id)
        assert cache is not None
        assert cache.status == "complete"
        assert cache.progress_pct == 100

        items = cache.items_json
        assert len(items) == 3
        assert items[0]["view_count"] == 100
        assert items[1]["view_count"] == 500
        assert items[2]["view_count"] is None
