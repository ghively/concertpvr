import datetime as dt
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from concertpvr.backlog_cache import fetch_full_channel, is_stale
from concertpvr.db import Database
from concertpvr.main import create_app
from concertpvr.models import Base, ChannelBacklogCache, ChannelWatcher, Recording, Stream
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


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CPVR_DATA_DIR", str(tmp_path))
    with TestClient(create_app()) as c:
        yield c


def test_cancel_backlog_downloads(client: TestClient) -> None:
    db = client.app.state.db

    with db.session() as s:
        w = ChannelWatcher(channel_url="https://www.youtube.com/@cancel_test", channel_name="Test")
        s.add(w)
        s.flush()
        watcher_id = w.id

        st1 = Stream(
            kind="video",
            youtube_id="cancel-vid-1",
            url="https://cancel-vid-1",
            title="Cancel 1",
            channel_name="Test",
        )
        st2 = Stream(
            kind="video",
            youtube_id="cancel-vid-2",
            url="https://cancel-vid-2",
            title="Cancel 2",
            channel_name="Test",
        )
        s.add(st1)
        s.add(st2)
        s.flush()

        rec1 = Recording(
            stream_id=st1.id, started_at=dt.datetime.now(dt.UTC), path="tmp", status="vod_queued"
        )
        rec2 = Recording(
            stream_id=st2.id, started_at=dt.datetime.now(dt.UTC), path="tmp", status="complete"
        )
        s.add(rec1)
        s.add(rec2)
        s.flush()

    # Needs a mock for cancel_by_youtube_id
    from unittest.mock import AsyncMock

    client.app.state.vod_queue.cancel_by_youtube_id = AsyncMock()

    r = client.post(
        f"/api/channel-watchers/{watcher_id}/backlog/cancel",
        json={"video_ids": ["cancel-vid-1", "cancel-vid-2"]},
    )
    assert r.status_code == 200
    assert r.json() == {"cancelled": ["cancel-vid-1"]}

    with db.session() as s:
        # st1 and rec1 should be deleted because rec1 was queued
        assert s.scalar(select(Recording).where(Recording.status == "vod_queued")) is None
        assert s.scalar(select(Stream).where(Stream.youtube_id == "cancel-vid-1")) is None
        # st2 and rec2 should remain because rec2 was complete
        assert s.scalar(select(Recording).where(Recording.status == "complete")) is not None
        assert s.scalar(select(Stream).where(Stream.youtube_id == "cancel-vid-2")) is not None

    client.app.state.vod_queue.cancel_by_youtube_id.assert_awaited_once_with("cancel-vid-1")


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
    with (
        patch(
            "concertpvr.backlog_cache.list_all_uploads",
            AsyncMock(side_effect=RuntimeError("boom")),
        ),
        pytest.raises(RuntimeError),
    ):
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
            fetched_at=dt.datetime.now(dt.UTC).replace(tzinfo=None) - dt.timedelta(days=2),
        )
        s.add(cache)
        s.flush()
        s.refresh(cache)
        assert is_stale(cache) is True


@pytest.mark.asyncio
async def test_fetch_full_channel_does_not_trigger_downloads(db: Database) -> None:
    """Guardrail: populating the backlog cache must NEVER queue a download.

    The cache is metadata-only browsing infrastructure. Download queueing
    only happens via explicit user action on the backlog/download endpoint
    or via the channel poller's forward-only path. A future refactor
    must not couple these systems.
    """
    watcher_id = _seed_watcher(db)
    fake_items = [
        BroadcastInfo(
            youtube_id=f"item{i}",
            url=f"https://x{i}",
            title=f"Item {i}",
            channel_name="Test",
            is_live=False,
            upload_date=dt.date(2024, 1, 1),
            duration_s=120,
            thumbnail_url="t",
        )
        for i in range(10)
    ]
    with patch(
        "concertpvr.backlog_cache.list_all_uploads",
        AsyncMock(return_value=fake_items),
    ):
        await fetch_full_channel(db, watcher_id)

    # No Recording rows should exist after a full-channel fetch.
    from concertpvr.models import Recording, Stream

    with db.session() as s:
        rec_count = len(list(s.scalars(select(Recording))))
        stream_count_video = len(list(s.scalars(select(Stream).where(Stream.kind == "video"))))
    assert rec_count == 0, (
        f"backlog cache fetch created {rec_count} recordings — coupling violation"
    )
    assert stream_count_video == 0, (
        f"backlog cache fetch created {stream_count_video} kind=video streams — coupling violation"
    )
