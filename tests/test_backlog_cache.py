import datetime as dt
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from concertpvr.backlog_cache import fetch_full_channel, is_stale
from concertpvr.db import Database
from concertpvr.models import Base, ChannelBacklogCache, ChannelWatcher
from concertpvr.ytdlp_channels import BroadcastInfo


@pytest.fixture
def db(tmp_path):  # type: ignore[no-untyped-def]
    d = Database(f"sqlite:///{tmp_path / 'b.db'}")
    Base.metadata.create_all(d.engine)
    return d


def _seed_watcher(db: Database, channel_url: str = "https://www.youtube.com/@test") -> int:
    with db.session() as s:
        w = ChannelWatcher(channel_url=channel_url, channel_name="Test")
        s.add(w)
        s.flush()
        return w.id


@pytest.mark.asyncio
async def test_fetch_populates_cache_with_items(db: Database) -> None:
    watcher_id = _seed_watcher(db)
    fake_items = [
        BroadcastInfo(
            youtube_id="a",
            url="https://a",
            title="Video A",
            channel_name="Test",
            is_live=False,
            upload_date=dt.date(2024, 1, 1),
            duration_s=120,
            thumbnail_url="t1",
        ),
        BroadcastInfo(
            youtube_id="b",
            url="https://b",
            title="Video B",
            channel_name="Test",
            is_live=False,
            upload_date=dt.date(2024, 2, 1),
            duration_s=300,
            thumbnail_url="t2",
        ),
    ]
    with patch("concertpvr.backlog_cache.list_all_uploads", AsyncMock(return_value=fake_items)):
        count = await fetch_full_channel(db, watcher_id)
    assert count == 2
    with db.session() as s:
        cache = s.get(ChannelBacklogCache, watcher_id)
        assert cache is not None
        assert cache.status == "complete"
        assert cache.total_count == 2
        assert cache.items_json is not None
        assert len(cache.items_json) == 2


@pytest.mark.asyncio
async def test_fetch_handles_error(db: Database) -> None:
    watcher_id = _seed_watcher(db)
    with patch(
        "concertpvr.backlog_cache.list_all_uploads",
        AsyncMock(side_effect=RuntimeError("boom")),
    ):
        with pytest.raises(RuntimeError):
            await fetch_full_channel(db, watcher_id)
    with db.session() as s:
        cache = s.get(ChannelBacklogCache, watcher_id)
        assert cache is not None
        assert cache.status == "error"
        assert "boom" in (cache.error or "")


def test_is_stale_for_never_fetched(db: Database) -> None:
    watcher_id = _seed_watcher(db)
    with db.session() as s:
        cache = ChannelBacklogCache(watcher_id=watcher_id, status="never_fetched")
        s.add(cache)
        s.flush()
        s.refresh(cache)
        assert is_stale(cache) is True


def test_is_stale_for_fresh(db: Database) -> None:
    watcher_id = _seed_watcher(db)
    with db.session() as s:
        cache = ChannelBacklogCache(
            watcher_id=watcher_id,
            status="complete",
            fetched_at=dt.datetime.now(dt.UTC).replace(tzinfo=None),  # store naive
        )
        s.add(cache)
        s.flush()
        s.refresh(cache)
        assert is_stale(cache) is False


def test_is_stale_for_old(db: Database) -> None:
    watcher_id = _seed_watcher(db)
    with db.session() as s:
        cache = ChannelBacklogCache(
            watcher_id=watcher_id,
            status="complete",
            fetched_at=dt.datetime.now(dt.UTC).replace(tzinfo=None)
            - dt.timedelta(days=2),
        )
        s.add(cache)
        s.flush()
        s.refresh(cache)
        assert is_stale(cache) is True
