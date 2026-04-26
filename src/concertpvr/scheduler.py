"""APScheduler factory bound to our SQLite Database."""

from __future__ import annotations

from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from concertpvr.db import Database


def build_scheduler(db: Database) -> AsyncIOScheduler:
    """Build an AsyncIOScheduler that persists jobs in our SQLite db."""
    jobstore = SQLAlchemyJobStore(engine=db.engine)
    sched = AsyncIOScheduler(jobstores={"default": jobstore})
    return sched
