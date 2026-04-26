import asyncio

import pytest

from concertpvr.db import Database
from concertpvr.scheduler import build_scheduler


# Module-level — APScheduler's SQLAlchemyJobStore pickles jobs by qualified name,
# so the callable and its mutable counter must live at module scope.
_fire_counter: list[bool] = []


async def _record_fire() -> None:
    _fire_counter.append(True)


async def _noop() -> None:
    pass


@pytest.mark.asyncio
async def test_scheduler_starts_and_runs_periodic_job(tmp_path):
    _fire_counter.clear()

    db = Database(f"sqlite:///{tmp_path / 'sched.db'}")
    sched = build_scheduler(db)

    sched.add_job(_record_fire, "interval", seconds=0.1, id="testjob")
    sched.start()
    await asyncio.sleep(0.35)
    sched.shutdown(wait=False)

    # ~3 expected firings in 350ms with 100ms interval; allow some scheduler latency.
    assert len(_fire_counter) >= 2, f"expected >= 2 firings, got {len(_fire_counter)}"


@pytest.mark.asyncio
async def test_scheduler_persists_jobs_in_db(tmp_path):
    """A job added before shutdown should survive a fresh scheduler boot from same DB."""
    db = Database(f"sqlite:///{tmp_path / 'sched.db'}")
    sched1 = build_scheduler(db)

    sched1.add_job(_noop, "interval", seconds=60, id="persistme", replace_existing=True)
    sched1.start()
    sched1.shutdown(wait=False)
    await asyncio.sleep(0.05)

    sched2 = build_scheduler(db)
    sched2.start()
    try:
        ids = {j.id for j in sched2.get_jobs()}
        assert "persistme" in ids
    finally:
        sched2.shutdown(wait=False)
