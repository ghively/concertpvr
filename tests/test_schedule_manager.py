import datetime as dt

import pytest
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from concertpvr.db import Database
from concertpvr.models import Base, Schedule, Stream
from concertpvr.schedule_manager import ScheduleManager


def _make_scheduler() -> AsyncIOScheduler:
    return AsyncIOScheduler(jobstores={"default": MemoryJobStore(), "memory": MemoryJobStore()})


def _seed_stream(db: Database) -> int:
    with db.session() as s:
        stream = Stream(kind="live", youtube_id="x", url="u", title="t", channel_name="c")
        s.add(stream)
        s.flush()
        return stream.id


@pytest.mark.asyncio
async def test_add_creates_apscheduler_job(tmp_path):
    db = Database(f"sqlite:///{tmp_path / 'sm.db'}")
    Base.metadata.create_all(db.engine)
    sched = _make_scheduler()
    sched.start()
    try:
        mgr = ScheduleManager(sched)
        sid = _seed_stream(db)
        with db.session() as s:
            sch = Schedule(
                stream_id=sid,
                starts_at=dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1),
                ends_at=dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=2),
            )
            s.add(sch)
            s.flush()
            mgr.add(sch)
            schedule_id = sch.id
        assert mgr.has_job(schedule_id)
    finally:
        sched.shutdown(wait=False)


@pytest.mark.asyncio
async def test_remove_deletes_job(tmp_path):
    db = Database(f"sqlite:///{tmp_path / 'sm.db'}")
    Base.metadata.create_all(db.engine)
    sched = _make_scheduler()
    sched.start()
    try:
        mgr = ScheduleManager(sched)
        sid = _seed_stream(db)
        with db.session() as s:
            sch = Schedule(
                stream_id=sid,
                starts_at=dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1),
                ends_at=dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=2),
            )
            s.add(sch)
            s.flush()
            mgr.add(sch)
            schedule_id = sch.id

        mgr.remove(schedule_id)
        assert not mgr.has_job(schedule_id)
    finally:
        sched.shutdown(wait=False)


@pytest.mark.asyncio
async def test_update_changes_run_time(tmp_path):
    db = Database(f"sqlite:///{tmp_path / 'sm.db'}")
    Base.metadata.create_all(db.engine)
    sched = _make_scheduler()
    sched.start()
    try:
        mgr = ScheduleManager(sched)
        sid = _seed_stream(db)
        with db.session() as s:
            sch = Schedule(
                stream_id=sid,
                starts_at=dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1),
                ends_at=dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=2),
            )
            s.add(sch)
            s.flush()
            mgr.add(sch)
            sid2 = sch.id

            sch.starts_at = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=3)
            mgr.update(sch)

        job = sched.get_job(f"schedule_{sid2}")
        assert job is not None
        assert job.next_run_time is not None
    finally:
        sched.shutdown(wait=False)


@pytest.mark.asyncio
async def test_rehydrate_loads_pending_schedules_only(tmp_path):
    db = Database(f"sqlite:///{tmp_path / 'sm.db'}")
    Base.metadata.create_all(db.engine)
    sched = _make_scheduler()
    sched.start()
    try:
        mgr = ScheduleManager(sched)
        sid = _seed_stream(db)
        with db.session() as s:
            now = dt.datetime.now(dt.timezone.utc)
            future = Schedule(
                stream_id=sid, starts_at=now + dt.timedelta(hours=1),
                ends_at=now + dt.timedelta(hours=2), status="pending",
            )
            past_done = Schedule(
                stream_id=sid, starts_at=now - dt.timedelta(hours=2),
                ends_at=now - dt.timedelta(hours=1), status="complete",
            )
            cancelled = Schedule(
                stream_id=sid, starts_at=now + dt.timedelta(hours=1),
                ends_at=now + dt.timedelta(hours=2), status="cancelled",
            )
            s.add_all([future, past_done, cancelled])
            s.flush()
            future_id = future.id
            past_id = past_done.id
            cancelled_id = cancelled.id

        loaded = mgr.rehydrate_from_db(db)
        assert loaded == 1
        assert mgr.has_job(future_id)
        assert not mgr.has_job(past_id)
        assert not mgr.has_job(cancelled_id)
    finally:
        sched.shutdown(wait=False)
