import datetime as _dt
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from concertpvr.buffer import BufferManager
from concertpvr.channel_poller import poll_all_channel_watchers
from concertpvr.db import Database
from concertpvr.models import Base, ChannelWatcher, Recording, Stream
from concertpvr.vod_queue import VodQueue
from concertpvr.ws import Broadcaster
from concertpvr.ytdlp import StreamInfo
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


def _seed_watcher(
    db: Database, *, title_filter: str | None = None, last_live_id: str | None = None
) -> int:
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
            db=setup["db"],
            pool=setup["pool"],
            buf=setup["buf"],
            bc=setup["bc"],
            default_quality="best",
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
            db=setup["db"],
            pool=setup["pool"],
            buf=setup["buf"],
            bc=setup["bc"],
            default_quality="best",
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
            db=setup["db"],
            pool=setup["pool"],
            buf=setup["buf"],
            bc=setup["bc"],
            default_quality="best",
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
            channel_name="X",
            enabled=False,
        )
        s.add(w)

    fetch_mock = AsyncMock(return_value=[])
    with patch("concertpvr.channel_poller.fetch_channel_live_broadcasts", new=fetch_mock):
        await poll_all_channel_watchers(
            db=setup["db"],
            pool=setup["pool"],
            buf=setup["buf"],
            bc=setup["bc"],
            default_quality="best",
        )
    fetch_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_existing_stream_is_reused(setup):
    db = setup["db"]
    _seed_watcher(db)

    with db.session() as s:
        existing = Stream(
            kind="live",
            youtube_id="live123",
            url="https://www.youtube.com/watch?v=live123",
            title="Existing",
            channel_name="NPR Music",
        )
        s.add(existing)
        s.flush()
        existing_id = existing.id

    new_broadcast = BroadcastInfo(
        youtube_id="live123",
        url="https://www.youtube.com/watch?v=live123",
        title="Tiny Desk Live",
        channel_name="NPR Music",
        is_live=True,
    )

    with patch(
        "concertpvr.channel_poller.fetch_channel_live_broadcasts",
        new=AsyncMock(return_value=[new_broadcast]),
    ):
        await poll_all_channel_watchers(
            db=setup["db"],
            pool=setup["pool"],
            buf=setup["buf"],
            bc=setup["bc"],
            default_quality="best",
        )

    with db.session() as s:
        streams = s.query(Stream).all()
        assert len(streams) == 1
        assert streams[0].id == existing_id


# ---------------------------------------------------------------------------
# VOD uploads branch tests
# ---------------------------------------------------------------------------


def _make_vod_queue(db: Database) -> VodQueue:
    """Create a VodQueue with a no-op handler (no real downloading)."""
    handler = AsyncMock()
    vq = VodQueue(db=db, handler=handler, max_concurrent=1)
    return vq


def _seed_vod_watcher(
    db: Database,
    *,
    watch_live: bool = False,
    watch_vod_uploads: bool = True,
    vod_title_filter: str | None = None,
    vod_artist_regex: str | None = None,
    auto_publish: bool = False,
    added_at: _dt.datetime | None = None,
) -> int:
    with db.session() as s:
        w = ChannelWatcher(
            channel_url="https://www.youtube.com/@nprmusic",
            channel_name="NPR Music",
            watch_live=watch_live,
            watch_vod_uploads=watch_vod_uploads,
            vod_title_filter=vod_title_filter,
            vod_artist_regex=vod_artist_regex,
            auto_publish=auto_publish,
        )
        if added_at is not None:
            w.added_at = added_at
        s.add(w)
        s.flush()
        return w.id


def _fake_stream_info(
    youtube_id: str = "vod001",
    title: str = "Tiny Desk Concert — Foo Fighter",
) -> StreamInfo:
    return StreamInfo(
        youtube_id=youtube_id,
        url=f"https://www.youtube.com/watch?v={youtube_id}",
        title=title,
        channel_name="NPR Music",
        is_live=False,
        thumbnail_url=None,
        original_upload_date=_dt.date(2026, 4, 20),
        description=None,
        tags=None,
        chapters=None,
        comments=None,
        duration_s=1800,
    )


def _fake_upload(
    youtube_id: str = "vod001",
    title: str = "Tiny Desk Concert — Foo Fighter",
    upload_date: _dt.date | None = _dt.date(2026, 4, 20),
    is_live: bool = False,
) -> BroadcastInfo:
    return BroadcastInfo(
        youtube_id=youtube_id,
        url=f"https://www.youtube.com/watch?v={youtube_id}",
        title=title,
        channel_name="NPR Music",
        is_live=is_live,
        upload_date=upload_date,
    )


@pytest.mark.asyncio
async def test_poller_skips_vod_when_watch_vod_uploads_off(setup, tmp_path):
    """Watcher with watch_vod_uploads=False must never call list_recent_uploads."""
    db = setup["db"]
    _seed_vod_watcher(db, watch_vod_uploads=False, watch_live=False)
    vq = _make_vod_queue(db)

    list_mock = AsyncMock(return_value=[_fake_upload()])
    with (
        patch("concertpvr.channel_poller.list_recent_uploads", new=list_mock),
        patch(
            "concertpvr.channel_poller.fetch_channel_live_broadcasts",
            new=AsyncMock(return_value=[]),
        ),
    ):
        await poll_all_channel_watchers(
            db=db,
            pool=setup["pool"],
            buf=setup["buf"],
            bc=setup["bc"],
            default_quality="best",
            vod_queue=vq,
            staging_root=tmp_path,
        )

    list_mock.assert_not_awaited()
    with db.session() as s:
        assert s.query(Recording).count() == 0


@pytest.mark.asyncio
async def test_poller_creates_vod_recording_with_auto_publish_when_artist_extracted(
    setup, tmp_path
):
    """When auto_publish=True and vod_artist_regex matches, recording gets auto_publish_after_download=True."""
    db = setup["db"]
    _seed_vod_watcher(
        db,
        watch_vod_uploads=True,
        auto_publish=True,
        vod_artist_regex=r"Tiny Desk Concert — (?P<artist>.+)",
        added_at=_dt.datetime(2026, 1, 1, tzinfo=_dt.UTC),
    )
    vq = _make_vod_queue(db)

    upload = _fake_upload(youtube_id="vod001", title="Tiny Desk Concert — Foo Fighter")
    info = _fake_stream_info(youtube_id="vod001", title="Tiny Desk Concert — Foo Fighter")

    with (
        patch(
            "concertpvr.channel_poller.list_recent_uploads", new=AsyncMock(return_value=[upload])
        ),
        patch("concertpvr.channel_poller.probe", new=AsyncMock(return_value=info)),
        patch(
            "concertpvr.channel_poller.fetch_channel_live_broadcasts",
            new=AsyncMock(return_value=[]),
        ),
    ):
        await poll_all_channel_watchers(
            db=db,
            pool=setup["pool"],
            buf=setup["buf"],
            bc=setup["bc"],
            default_quality="best",
            vod_queue=vq,
            staging_root=tmp_path,
        )

    with db.session() as s:
        streams = s.query(Stream).all()
        assert len(streams) == 1
        assert streams[0].kind == "video"
        assert streams[0].youtube_id == "vod001"

        recs = s.query(Recording).all()
        assert len(recs) == 1
        assert recs[0].status == "vod_queued"
        assert recs[0].auto_publish_after_download is True


@pytest.mark.asyncio
async def test_poller_skips_already_known_youtube_id(setup, tmp_path):
    """Uploads whose youtube_id already has a Stream row are silently skipped."""
    db = setup["db"]
    _seed_vod_watcher(
        db,
        watch_vod_uploads=True,
        added_at=_dt.datetime(2026, 1, 1, tzinfo=_dt.UTC),
    )
    vq = _make_vod_queue(db)

    # Pre-create the stream
    with db.session() as s:
        existing = Stream(
            kind="video",
            youtube_id="vod_known",
            url="https://www.youtube.com/watch?v=vod_known",
            title="Already Known",
            channel_name="NPR Music",
        )
        s.add(existing)

    upload = _fake_upload(youtube_id="vod_known")
    probe_mock = AsyncMock(return_value=_fake_stream_info(youtube_id="vod_known"))

    with (
        patch(
            "concertpvr.channel_poller.list_recent_uploads", new=AsyncMock(return_value=[upload])
        ),
        patch("concertpvr.channel_poller.probe", new=probe_mock),
        patch(
            "concertpvr.channel_poller.fetch_channel_live_broadcasts",
            new=AsyncMock(return_value=[]),
        ),
    ):
        await poll_all_channel_watchers(
            db=db,
            pool=setup["pool"],
            buf=setup["buf"],
            bc=setup["bc"],
            default_quality="best",
            vod_queue=vq,
            staging_root=tmp_path,
        )

    # probe should NOT have been called (skipped by known youtube_id check)
    probe_mock.assert_not_awaited()
    with db.session() as s:
        # No new recordings
        assert s.query(Recording).count() == 0


@pytest.mark.asyncio
async def test_poller_forward_only_skips_uploads_older_than_watcher_created_at(setup, tmp_path):
    """Uploads with upload_date before watcher.added_at are skipped (forward-only filter)."""
    db = setup["db"]
    watcher_created = _dt.datetime(2026, 4, 10, tzinfo=_dt.UTC)
    _seed_vod_watcher(
        db,
        watch_vod_uploads=True,
        added_at=watcher_created,
    )
    vq = _make_vod_queue(db)

    old_upload = _fake_upload(
        youtube_id="vod_old",
        title="Old Concert",
        upload_date=_dt.date(2026, 4, 5),  # before watcher created_at
    )
    probe_mock = AsyncMock(return_value=_fake_stream_info(youtube_id="vod_old"))

    with (
        patch(
            "concertpvr.channel_poller.list_recent_uploads",
            new=AsyncMock(return_value=[old_upload]),
        ),
        patch("concertpvr.channel_poller.probe", new=probe_mock),
        patch(
            "concertpvr.channel_poller.fetch_channel_live_broadcasts",
            new=AsyncMock(return_value=[]),
        ),
    ):
        await poll_all_channel_watchers(
            db=db,
            pool=setup["pool"],
            buf=setup["buf"],
            bc=setup["bc"],
            default_quality="best",
            vod_queue=vq,
            staging_root=tmp_path,
        )

    # probe must NOT have been called — upload was filtered before probe
    probe_mock.assert_not_awaited()
    with db.session() as s:
        assert s.query(Recording).count() == 0


@pytest.mark.asyncio
async def test_poller_applies_vod_title_filter(setup, tmp_path):
    """Uploads not matching vod_title_filter are skipped without probing."""
    db = setup["db"]
    _seed_vod_watcher(
        db,
        watch_vod_uploads=True,
        vod_title_filter="Tiny Desk",
        added_at=_dt.datetime(2026, 1, 1, tzinfo=_dt.UTC),
    )
    vq = _make_vod_queue(db)

    non_matching = _fake_upload(
        youtube_id="vod_nope",
        title="Behind the Scenes Documentary",
        upload_date=_dt.date(2026, 4, 20),
    )
    probe_mock = AsyncMock(return_value=_fake_stream_info(youtube_id="vod_nope"))

    with (
        patch(
            "concertpvr.channel_poller.list_recent_uploads",
            new=AsyncMock(return_value=[non_matching]),
        ),
        patch("concertpvr.channel_poller.probe", new=probe_mock),
        patch(
            "concertpvr.channel_poller.fetch_channel_live_broadcasts",
            new=AsyncMock(return_value=[]),
        ),
    ):
        await poll_all_channel_watchers(
            db=db,
            pool=setup["pool"],
            buf=setup["buf"],
            bc=setup["bc"],
            default_quality="best",
            vod_queue=vq,
            staging_root=tmp_path,
        )

    probe_mock.assert_not_awaited()
    with db.session() as s:
        assert s.query(Recording).count() == 0
