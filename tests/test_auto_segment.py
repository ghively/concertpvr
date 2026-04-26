import datetime as dt
import json

import pytest
from fastapi.testclient import TestClient

from concertpvr.main import create_app
from concertpvr.models import Recording, Segment, Stream


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CPVR_DATA_DIR", str(tmp_path))
    with TestClient(create_app()) as c:
        yield c


def test_setting_recording_complete_with_chapters_creates_segments(client):
    db = client.app.state.db
    chapters = json.dumps(
        [
            {"title": "A", "start_time": 0, "end_time": 60},
            {"title": "B", "start_time": 60, "end_time": 120},
        ]
    )
    with db.session() as s:
        stream = Stream(kind="live", youtube_id="x", url="u", title="t", channel_name="c")
        s.add(stream)
        s.flush()
        rec = Recording(
            stream_id=stream.id,
            started_at=dt.datetime(2026, 4, 12, 14, 0, tzinfo=dt.UTC),
            path="/buf/1",
            status="recording",
            is_buffer=True,
            raw_chapters_json=chapters,
        )
        s.add(rec)
        s.flush()
        rid = rec.id

    with db.session() as s:
        rec = s.get(Recording, rid)
        rec.status = "complete"

    with db.session() as s:
        segments = s.query(Segment).filter_by(recording_id=rid).all()
        assert len(segments) == 2
        assert {seg.artist for seg in segments} == {"A", "B"}


def test_completion_without_chapters_creates_no_segments(client):
    db = client.app.state.db
    with db.session() as s:
        stream = Stream(kind="live", youtube_id="y", url="u", title="t", channel_name="c")
        s.add(stream)
        s.flush()
        rec = Recording(
            stream_id=stream.id,
            started_at=dt.datetime(2026, 4, 12, 14, 0, tzinfo=dt.UTC),
            path="/buf/1",
            status="recording",
            is_buffer=True,
        )
        s.add(rec)
        s.flush()
        rid = rec.id

    with db.session() as s:
        rec = s.get(Recording, rid)
        rec.status = "complete"

    with db.session() as s:
        segments = s.query(Segment).filter_by(recording_id=rid).all()
        assert segments == []
