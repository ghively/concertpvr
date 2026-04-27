"""Migration 0008 smoke test — schema additive only, defaults populate existing rows."""

import pytest
from fastapi.testclient import TestClient

from concertpvr.main import create_app
from concertpvr.models import ChannelWatcher, Recording, Segment, Settings, Stream


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CPVR_DATA_DIR", str(tmp_path))
    with TestClient(create_app()) as c:
        yield c


def test_existing_watcher_rows_get_safe_defaults(client):
    """A watcher created before migration must come up with watch_live=True and VOD off."""
    db = client.app.state.db
    with db.session() as s:
        w = ChannelWatcher(
            channel_url="https://www.youtube.com/@nprmusic", channel_name="NPR Music"
        )
        s.add(w)
        s.flush()
        wid = w.id

    with db.session() as s:
        w = s.get(ChannelWatcher, wid)
        assert w.watch_live is True
        assert w.watch_vod_uploads is False
        assert w.vod_segmentation_mode == "chapters"
        assert w.vod_title_filter is None
        assert w.vod_artist_regex is None
        assert w.auto_publish is False
        assert w.extract_setlist_from_comments is False
        assert w.default_genres is None
        assert w.auto_delete_source_after_publish is None


def test_existing_stream_columns_default_null(client):
    db = client.app.state.db
    with db.session() as s:
        st = Stream(kind="live", youtube_id="abc", url="https://x", title="T", channel_name="C")
        s.add(st)
        s.flush()
        sid = st.id

    with db.session() as s:
        st = s.get(Stream, sid)
        assert st.original_upload_date is None
        assert st.description is None
        assert st.youtube_tags is None
        assert st.detected_setlist_text is None
        assert st.detected_setlist_source is None
        assert st.watcher_id is None


def test_existing_settings_get_vod_defaults(client):
    db = client.app.state.db
    with db.session() as s:
        row = s.get(Settings, 1)
        assert row is not None
        assert row.max_concurrent_vod_downloads == 2
        assert row.auto_delete_source_after_publish is False


def test_recording_gets_source_deleted_default(client):
    db = client.app.state.db
    import datetime as _dt

    with db.session() as s:
        st = Stream(kind="live", youtube_id="abc", url="https://x", title="T", channel_name="C")
        s.add(st)
        s.flush()
        rec = Recording(
            stream_id=st.id,
            started_at=_dt.datetime.now(_dt.UTC),
            path="/tmp/x",
            status="recording",
            is_buffer=True,
        )
        s.add(rec)
        s.flush()
        rid = rec.id

    with db.session() as s:
        rec = s.get(Recording, rid)
        assert rec.auto_publish_after_download is False
        assert rec.source_deleted is False


def test_segment_genres_default_null(client):
    db = client.app.state.db
    import datetime as _dt

    with db.session() as s:
        st = Stream(kind="video", youtube_id="abc", url="https://x", title="T", channel_name="C")
        s.add(st)
        s.flush()
        rec = Recording(
            stream_id=st.id,
            started_at=_dt.datetime.now(_dt.UTC),
            path="/tmp/x",
            status="complete",
            is_buffer=False,
        )
        s.add(rec)
        s.flush()
        seg = Segment(
            recording_id=rec.id,
            artist="A",
            start_s=0,
            end_s=10,
            source="manual",
            status="draft",
        )
        s.add(seg)
        s.flush()
        sid = seg.id

    with db.session() as s:
        seg = s.get(Segment, sid)
        assert seg.genres is None
