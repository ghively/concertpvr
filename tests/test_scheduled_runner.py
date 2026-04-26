import datetime as dt
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from concertpvr.buffer import BufferManager
from concertpvr.db import Database
from concertpvr.models import Base, Recording, Schedule, Stream
from concertpvr.process import FakeProcessRunner
from concertpvr.scheduled_runner import register_app, run_scheduled_recording, unregister_app
from concertpvr.ws import Broadcaster


@pytest.fixture
def app_state(tmp_path: Path):
    db = Database(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(db.engine)
    pool = MagicMock()
    pool.is_recording = MagicMock(return_value=False)
    pool.start = AsyncMock()
    pool.stop = AsyncMock()
    buf = BufferManager(tmp_path / "buf")
    bc = Broadcaster()
    runner = FakeProcessRunner()

    register_app(
        db=db,
        pool=pool,
        buf=buf,
        bc=bc,
        runner_factory=lambda: runner,
        staging_root=tmp_path / "staging",
    )
    yield {
        "db": db,
        "pool": pool,
        "buf": buf,
        "bc": bc,
        "runner": runner,
        "staging": tmp_path / "staging",
    }
    unregister_app()


@pytest.mark.asyncio
async def test_run_creates_recording_and_starts_worker(app_state, monkeypatch):
    monkeypatch.setattr("concertpvr.recorder.PROGRESS_POLL_S", 0.05)

    db = app_state["db"]
    with db.session() as s:
        stream = Stream(
            kind="live", youtube_id="z1", url="https://example.com", title="t", channel_name="c"
        )
        s.add(stream)
        s.flush()
        now = dt.datetime.now(dt.UTC)
        sch = Schedule(
            stream_id=stream.id,
            starts_at=now,
            ends_at=now + dt.timedelta(milliseconds=200),
            artist="TestArtist",
        )
        s.add(sch)
        s.flush()
        schedule_id = sch.id

    app_state["runner"].queue("yt-dlp", [], exit_code=0)

    await run_scheduled_recording(schedule_id)

    with db.session() as s:
        loaded = s.get(Schedule, schedule_id)
        assert loaded.status == "complete"
        assert loaded.recording_id is not None

        rec = s.get(Recording, loaded.recording_id)
        assert rec is not None
        assert rec.status == "complete"
        assert rec.is_buffer is False
        assert "staging" in rec.path

    app_state["pool"].start.assert_awaited()


@pytest.mark.asyncio
async def test_run_marks_failed_when_stream_missing(app_state):
    db = app_state["db"]
    with db.session() as s:
        stream = Stream(kind="live", youtube_id="z2", url="u", title="t", channel_name="c")
        s.add(stream)
        s.flush()
        sch = Schedule(
            stream_id=stream.id,
            starts_at=dt.datetime.now(dt.UTC),
            ends_at=dt.datetime.now(dt.UTC) + dt.timedelta(seconds=1),
        )
        s.add(sch)
        s.flush()
        schedule_id = sch.id
        s.delete(stream)

    with pytest.raises(ValueError):
        await run_scheduled_recording(schedule_id)


@pytest.mark.asyncio
async def test_run_raises_when_schedule_missing(app_state):
    with pytest.raises(LookupError):
        await run_scheduled_recording(99999)
