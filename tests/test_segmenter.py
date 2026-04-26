import datetime as dt
import json

import pytest

from concertpvr.db import Database
from concertpvr.models import Base, Recording, Segment, Setlist, Stream
from concertpvr.segmenter import derive_draft_segments


@pytest.fixture
def db(tmp_path):
    d = Database(f"sqlite:///{tmp_path / 'seg.db'}")
    Base.metadata.create_all(d.engine)
    return d


def _seed_recording(db: Database, *, with_chapters: bool = False) -> int:
    with db.session() as s:
        stream = Stream(kind="live", youtube_id="x", url="u", title="t", channel_name="c")
        s.add(stream)
        s.flush()
        chapters = None
        if with_chapters:
            chapters = json.dumps([
                {"title": "Phoebe Bridgers", "start_time": 21, "end_time": 1900},
                {"title": "Goose", "start_time": 1900, "end_time": 4000},
            ])
        rec = Recording(
            stream_id=stream.id,
            started_at=dt.datetime(2026, 4, 25, 12, 0, tzinfo=dt.UTC),
            path="/buf/1",
            is_buffer=True,
            raw_chapters_json=chapters,
        )
        s.add(rec)
        s.flush()
        return rec.id


def test_derives_from_chapters_when_present(db):
    rid = _seed_recording(db, with_chapters=True)
    with db.session() as s:
        rec = s.get(Recording, rid)
        segments = derive_draft_segments(rec, s)
    assert len(segments) == 2
    assert segments[0].artist == "Phoebe Bridgers"
    assert segments[0].source == "chapter"
    assert segments[0].start_s == 21
    assert segments[0].end_s == 1900
    assert segments[1].artist == "Goose"


def test_derives_from_setlist_when_no_chapters(db):
    rid = _seed_recording(db, with_chapters=False)
    with db.session() as s:
        s.add(Setlist(recording_id=rid, artist="Tame Impala", start_s=10, end_s=2000))
        s.add(Setlist(recording_id=rid, artist="Rüfüs Du Sol", start_s=2100, end_s=4000))
        s.flush()
        rec = s.get(Recording, rid)
        segments = derive_draft_segments(rec, s)
    assert len(segments) == 2
    assert segments[0].artist == "Tame Impala"
    assert segments[0].source == "setlist"


def test_returns_empty_list_when_neither_chapters_nor_setlist(db):
    rid = _seed_recording(db, with_chapters=False)
    with db.session() as s:
        rec = s.get(Recording, rid)
        segments = derive_draft_segments(rec, s)
    assert segments == []


def test_chapters_take_precedence_over_setlist(db):
    rid = _seed_recording(db, with_chapters=True)
    with db.session() as s:
        s.add(Setlist(recording_id=rid, artist="ShouldNotAppear", start_s=0, end_s=99))
        s.flush()
        rec = s.get(Recording, rid)
        segments = derive_draft_segments(rec, s)
    assert all(seg.source == "chapter" for seg in segments)
    assert "ShouldNotAppear" not in {seg.artist for seg in segments}


def test_persists_to_db(db):
    rid = _seed_recording(db, with_chapters=True)
    with db.session() as s:
        rec = s.get(Recording, rid)
        derive_draft_segments(rec, s)

    with db.session() as s:
        rows = s.query(Segment).filter_by(recording_id=rid).all()
        assert len(rows) == 2
        assert all(r.status == "draft" for r in rows)
