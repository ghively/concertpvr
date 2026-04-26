from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from concertpvr.buffer import BufferManager
from concertpvr.channel_poller import poll_all_channel_watchers
from concertpvr.db import Database
from concertpvr.models import Base, ChannelWatcher, Recording, Stream
from concertpvr.ws import Broadcaster
from concertpvr.ytdlp_channels import BroadcastInfo


@pytest.fixture
def setup(tmp_path):
    db = Database(f"sqlite:///{tmp_path / 'cp.db'}")
    Base.metadata.create_all(db.engine)
    pool = MagicMock()
    pool.start = AsyncMock()
    buf = BufferManager(tmp_path / "buf")
    bc = Broadcaster()
    return {"db": db, "pool": pool, "buf": buf, "bc": bc}


def _seed_watcher(db: Database, *, title_filter: str | None = None,
                  last_live_id: str | None = None) -> int:
    with db.session() as s:
        w = ChannelWatcher(
            channel_url="https://www.youtube.com/@nprmusic",
            channel_name="NPR Music",
            title_filter=title_filter,
            last_live_id=last_live_id,
        )
        s.add(w)
        s.flush()
        return w.id


@pytest.mark.asyncio
async def test_creates_stream_and_recording_when_new_live_found(setup):
    db = setup["db"]
    _seed_watcher(db)

    new_broadcast = BroadcastInfo(
        youtube_id="live123",
        url="https://www.youtube.com/watch?v=live123",
        title="Tiny Desk Live — Jason Isbell",
        channel_name="NPR Music",
        is_live=True,
    )

    with patch(
        "concertpvr.channel_poller.fetch_channel_live_broadcasts",
        new=AsyncMock(return_value=[new_broadcast]),
    ):
        await poll_all_channel_watchers(
            db=setup["db"], pool=setup["pool"], buf=setup["buf"],
            bc=setup["bc"], default_quality="best",
        )

    with db.session() as s:
        streams = s.query(Stream).all()
        assert len(streams) == 1
        assert streams[0].youtube_id == "live123"
        assert streams[0].kind == "live"

        recordings = s.query(Recording).all()
        assert len(recordings) == 1
        assert recordings[0].stream_id == streams[0].id

        watcher = s.query(ChannelWatcher).first()
        assert watcher.last_live_id == "live123"
        assert watcher.last_polled is not None

    setup["pool"].start.assert_awaited_once()


@pytest.mark.asyncio
async def test_skips_when_no_change_since_last_poll(setup):
    db = setup["db"]
    _seed_watcher(db, last_live_id="live123")

    same_broadcast = BroadcastInfo(
        youtube_id="live123",
        url="https://www.youtube.com/watch?v=live123",
        title="Tiny Desk Live",
        channel_name="NPR Music",
        is_live=True,
    )

    with patch(
        "concertpvr.channel_poller.fetch_channel_live_broadcasts",
        new=AsyncMock(return_value=[same_broadcast]),
    ):
        await poll_all_channel_watchers(
            db=setup["db"], pool=setup["pool"], buf=setup["buf"],
            bc=setup["bc"], default_quality="best",
        )

    setup["pool"].start.assert_not_awaited()
    with db.session() as s:
        assert s.query(Recording).count() == 0


@pytest.mark.asyncio
async def test_title_filter_skips_non_matches(setup):
    db = setup["db"]
    _seed_watcher(db, title_filter="tiny desk")

    other = BroadcastInfo(
        youtube_id="live999",
        url="https://www.youtube.com/watch?v=live999",
        title="Behind the Scenes Q&A",
        channel_name="NPR Music",
        is_live=True,
    )

    with patch(
        "concertpvr.channel_poller.fetch_channel_live_broadcasts",
        new=AsyncMock(return_value=[other]),
    ):
        await poll_all_channel_watchers(
            db=setup["db"], pool=setup["pool"], buf=setup["buf"],
            bc=setup["bc"], default_quality="best",
        )

    setup["pool"].start.assert_not_awaited()
    with db.session() as s:
        assert s.query(Recording).count() == 0


@pytest.mark.asyncio
async def test_disabled_watcher_is_ignored(setup):
    db = setup["db"]
    with db.session() as s:
        w = ChannelWatcher(
            channel_url="https://www.youtube.com/@x",
            channel_name="X", enabled=False,
        )
        s.add(w)

    fetch_mock = AsyncMock(return_value=[])
    with patch("concertpvr.channel_poller.fetch_channel_live_broadcasts", new=fetch_mock):
        await poll_all_channel_watchers(
            db=setup["db"], pool=setup["pool"], buf=setup["buf"],
            bc=setup["bc"], default_quality="best",
        )
    fetch_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_existing_stream_is_reused(setup):
    db = setup["db"]
    _seed_watcher(db)

    with db.session() as s:
        existing = Stream(
            kind="live", youtube_id="live123",
            url="https://www.youtube.com/watch?v=live123",
            title="Existing", channel_name="NPR Music",
        )
        s.add(existing)
        s.flush()
        existing_id = existing.id

    new_broadcast = BroadcastInfo(
        youtube_id="live123",
        url="https://www.youtube.com/watch?v=live123",
        title="Tiny Desk Live", channel_name="NPR Music", is_live=True,
    )

    with patch(
        "concertpvr.channel_poller.fetch_channel_live_broadcasts",
        new=AsyncMock(return_value=[new_broadcast]),
    ):
        await poll_all_channel_watchers(
            db=setup["db"], pool=setup["pool"], buf=setup["buf"],
            bc=setup["bc"], default_quality="best",
        )

    with db.session() as s:
        streams = s.query(Stream).all()
        assert len(streams) == 1
        assert streams[0].id == existing_id
