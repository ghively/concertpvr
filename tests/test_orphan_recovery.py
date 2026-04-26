import datetime as dt

import pytest
from fastapi.testclient import TestClient

from concertpvr.main import create_app
from concertpvr.models import Recording, Stream


@pytest.fixture
def setup_with_orphan(tmp_path, monkeypatch):
    """Boot the app once to create the schema, seed an orphan, reboot."""
    monkeypatch.setenv("CPVR_DATA_DIR", str(tmp_path))

    # First boot: creates schema and shuts down cleanly
    with TestClient(create_app()) as c:
        db = c.app.state.db
        with db.session() as s:
            stream = Stream(kind="live", youtube_id="x", url="u", title="t", channel_name="c")
            s.add(stream)
            s.flush()
            rec = Recording(
                stream_id=stream.id,
                started_at=dt.datetime(2026, 4, 25, 12, 0, tzinfo=dt.UTC),
                path=str(tmp_path / "buf" / "1"),
                status="recording",
                is_buffer=True,
            )
            s.add(rec)
            s.flush()
            rec_id = rec.id

    # Second boot: orphan recovery should fire on lifespan startup
    with TestClient(create_app()) as c:
        db = c.app.state.db
        with db.session() as s:
            rec = s.get(Recording, rec_id)
            yield rec.status, rec.ended_at


def test_orphan_marked_interrupted_on_restart(setup_with_orphan):
    status, ended_at = setup_with_orphan
    assert status == "interrupted"
    assert ended_at is not None


def test_unit_marks_interrupted(tmp_path):
    """Direct unit test of the helper."""
    from concertpvr.db import Database
    from concertpvr.models import Base
    from concertpvr.orphan_recovery import mark_interrupted_on_startup

    db = Database(f"sqlite:///{tmp_path / 'orphan.db'}")
    Base.metadata.create_all(db.engine)

    with db.session() as s:
        stream = Stream(kind="live", youtube_id="x", url="u", title="t", channel_name="c")
        s.add(stream)
        s.flush()
        s.add_all([
            Recording(stream_id=stream.id,
                      started_at=dt.datetime.now(dt.UTC),
                      path="/tmp/a", status="recording", is_buffer=True),
            Recording(stream_id=stream.id,
                      started_at=dt.datetime.now(dt.UTC),
                      path="/tmp/b", status="complete", is_buffer=False),
        ])

    count = mark_interrupted_on_startup(db)
    assert count == 1

    with db.session() as s:
        statuses = sorted(r.status for r in s.scalars(__import__("sqlalchemy").select(Recording)))
        assert statuses == ["complete", "interrupted"]
