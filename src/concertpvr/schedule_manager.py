"""ScheduleManager: bridges the schedules DB table and APScheduler's job registry."""

from __future__ import annotations

import contextlib
import datetime as _dt

from apscheduler.schedulers.asyncio import AsyncIOScheduler  # type: ignore[import-untyped]
from sqlalchemy import select

from concertpvr.db import Database
from concertpvr.models import Schedule
from concertpvr.scheduled_runner import run_scheduled_recording

# Fire 30 seconds before starts_at to give yt-dlp time to negotiate.
LEAD_TIME_S: int = 30


def _job_id(schedule_id: int) -> str:
    return f"schedule_{schedule_id}"


def _trigger_time(schedule: Schedule) -> _dt.datetime:
    return schedule.starts_at - _dt.timedelta(seconds=LEAD_TIME_S)


class ScheduleManager:
    def __init__(self, scheduler: AsyncIOScheduler) -> None:
        self._sched = scheduler

    def add(self, schedule: Schedule) -> None:
        self._sched.add_job(
            run_scheduled_recording,
            trigger="date",
            run_date=_trigger_time(schedule),
            args=[schedule.id],
            id=_job_id(schedule.id),
            replace_existing=True,
            jobstore="memory",
        )

    def update(self, schedule: Schedule) -> None:
        self._sched.reschedule_job(
            _job_id(schedule.id),
            trigger="date",
            run_date=_trigger_time(schedule),
        )

    def remove(self, schedule_id: int) -> None:
        # idempotent — already gone
        with contextlib.suppress(Exception):  # noqa: BLE001
            self._sched.remove_job(_job_id(schedule_id))

    def has_job(self, schedule_id: int) -> bool:
        return self._sched.get_job(_job_id(schedule_id)) is not None

    def rehydrate_from_db(self, db: Database) -> int:
        """Re-add APScheduler jobs for every pending Schedule with starts_at in the future.

        Returns count of jobs added. Called once at app startup.
        """
        now = _dt.datetime.now(_dt.UTC)
        count = 0
        with db.session() as s:
            stmt = select(Schedule).where(
                Schedule.status == "pending",
                Schedule.starts_at > now,
            )
            for sch in s.scalars(stmt):
                self.add(sch)
                count += 1
        return count
