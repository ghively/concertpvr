"""APScheduler factory bound to our SQLite Database."""

from __future__ import annotations

from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from concertpvr.db import Database


def build_scheduler(db: Database) -> AsyncIOScheduler:
    """Build an AsyncIOScheduler that persists jobs in our SQLite db.

    Two jobstores:
    - ``default`` (SQLAlchemy) -- persisted, for externally-defined jobs.
    - ``memory`` -- in-process closures that cannot be pickled (e.g. the
      buffer retention pruner).
    """
    jobstores = {
        "default": SQLAlchemyJobStore(engine=db.engine),
        "memory": MemoryJobStore(),
    }
    sched = AsyncIOScheduler(jobstores=jobstores)
    return sched
