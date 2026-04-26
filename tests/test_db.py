import datetime as dt

from sqlalchemy import text

from concertpvr.db import Database
from concertpvr.models import (
    Base,
    ChannelWatcher,
    Recording,
    Schedule,
    Segment,
    Setlist,
    Settings,
    Stream,
    WatchSubscription,
)


def test_database_connects_and_pings(tmp_path):
    db = Database(f"sqlite:///{tmp_path / 'test.db'}")
    with db.session() as s:
        result = s.execute(text("SELECT 1")).scalar_one()
        assert result == 1


def test_database_session_is_transactional(tmp_path):
    """Each session() context manager is its own transaction."""
    db = Database(f"sqlite:///{tmp_path / 'test.db'}")
    with db.session() as s:
        s.execute(text("CREATE TABLE t (x INTEGER)"))
        s.execute(text("INSERT INTO t VALUES (1)"))

    with db.session() as s:
        count = s.execute(text("SELECT COUNT(*) FROM t")).scalar_one()
        assert count == 1


def test_settings_model_round_trip(tmp_path):
    db = Database(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(db.engine)

    with db.session() as s:
        s.add(Settings(id=1, emby_url="http://emby:8096", folder_pattern="{artist}"))

    with db.session() as s:
        row = s.get(Settings, 1)
        assert row is not None
        assert row.emby_url == "http://emby:8096"
        assert row.folder_pattern == "{artist}"
        assert row.default_quality == "bestvideo*+bestaudio/best"  # default
        assert row.max_concurrent_recordings == 4  # default


def test_stream_with_subscription_round_trip(tmp_path):
    db = Database(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(db.engine)

    with db.session() as s:
        stream = Stream(
            kind="live",
            youtube_id="abc123",
            url="https://youtube.com/watch?v=abc123",
            title="Coachella Mojave Stage",
            channel_name="Coachella",
        )
        stream.subscription = WatchSubscription(enabled=True, retention_days=7)
        s.add(stream)
        s.flush()
        sid = stream.id

    with db.session() as s:
        loaded = s.get(Stream, sid)
        assert loaded is not None
        assert loaded.youtube_id == "abc123"
        assert loaded.subscription is not None
        assert loaded.subscription.retention_days == 7


def test_recording_belongs_to_stream(tmp_path):
    db = Database(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(db.engine)

    with db.session() as s:
        stream = Stream(kind="live", youtube_id="x1", url="u", title="t", channel_name="c")
        s.add(stream)
        s.flush()
        rec = Recording(
            stream_id=stream.id,
            started_at=dt.datetime(2026, 4, 25, 12, 0, tzinfo=dt.UTC),
            path="/buffer/1/00.ts",
            is_buffer=True,
        )
        s.add(rec)
        s.flush()
        rid = rec.id

    with db.session() as s:
        loaded = s.get(Recording, rid)
        assert loaded is not None
        assert loaded.is_buffer is True
        assert loaded.status == "recording"


def test_schedule_round_trip(tmp_path):
    db = Database(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(db.engine)

    with db.session() as s:
        stream = Stream(kind="live", youtube_id="z1", url="u", title="t", channel_name="c")
        s.add(stream)
        s.flush()
        sch = Schedule(
            stream_id=stream.id,
            starts_at=dt.datetime(2026, 5, 1, 19, 0, tzinfo=dt.UTC),
            ends_at=dt.datetime(2026, 5, 1, 21, 0, tzinfo=dt.UTC),
            artist="Phish",
        )
        s.add(sch)
        s.flush()
        sid = sch.id

    with db.session() as s:
        loaded = s.get(Schedule, sid)
        assert loaded is not None
        assert loaded.artist == "Phish"
        assert loaded.status == "pending"
        assert loaded.recording_id is None


def test_segment_round_trip(tmp_path):
    db = Database(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(db.engine)

    with db.session() as s:
        stream = Stream(kind="live", youtube_id="seg1", url="u", title="t", channel_name="c")
        s.add(stream)
        s.flush()
        rec = Recording(
            stream_id=stream.id,
            started_at=dt.datetime(2026, 4, 25, 12, 0, tzinfo=dt.UTC),
            path="/buf/1",
            is_buffer=True,
        )
        s.add(rec)
        s.flush()

        seg = Segment(
            recording_id=rec.id,
            artist="Phoebe Bridgers",
            title="Mojave Set",
            start_s=21,
            end_s=94 * 60 + 21,
            source="chapter",
        )
        s.add(seg)
        s.flush()
        sid = seg.id

    with db.session() as s:
        loaded = s.get(Segment, sid)
        assert loaded is not None
        assert loaded.artist == "Phoebe Bridgers"
        assert loaded.status == "draft"
        assert loaded.source == "chapter"
        assert loaded.emby_path is None


def test_setlist_round_trip(tmp_path):
    db = Database(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(db.engine)

    with db.session() as s:
        stream = Stream(kind="live", youtube_id="set1", url="u", title="t", channel_name="c")
        s.add(stream)
        s.flush()
        rec = Recording(
            stream_id=stream.id,
            started_at=dt.datetime(2026, 4, 25, 12, 0, tzinfo=dt.UTC),
            path="/buf/1",
            is_buffer=True,
        )
        s.add(rec)
        s.flush()

        sl = Setlist(recording_id=rec.id, artist="Goose", start_s=111 * 60, end_s=222 * 60)
        s.add(sl)
        s.flush()
        slid = sl.id

    with db.session() as s:
        loaded = s.get(Setlist, slid)
        assert loaded is not None
        assert loaded.artist == "Goose"


def test_settings_auth_columns_default_to_null(tmp_db):
    Base.metadata.create_all(tmp_db.engine)
    with tmp_db.session() as s:
        s.add(Settings(id=1))
    with tmp_db.session() as s:
        row = s.get(Settings, 1)
        assert row is not None
        assert row.password_hash is None
        assert row.session_secret is None


def test_channel_watcher_round_trip(tmp_db):
    Base.metadata.create_all(tmp_db.engine)

    with tmp_db.session() as s:
        w = ChannelWatcher(
            channel_url="https://www.youtube.com/@nprmusic",
            channel_name="NPR Music",
            title_filter="tiny desk",
            retention_days=14,
        )
        s.add(w)
        s.flush()
        wid = w.id

    with tmp_db.session() as s:
        loaded = s.get(ChannelWatcher, wid)
        assert loaded is not None
        assert loaded.channel_name == "NPR Music"
        assert loaded.title_filter == "tiny desk"
        assert loaded.enabled is True
        assert loaded.last_polled is None
        assert loaded.last_live_id is None
