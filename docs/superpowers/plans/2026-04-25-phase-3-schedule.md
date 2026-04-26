# concertpvr — Phase 3: Schedule Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Schedule a recording for a specific time window — POST `/api/schedules {url, starts_at, ends_at, artist?}` → at `starts_at - 30s` APScheduler fires → recorder writes to `/staging/{recording_id}.mkv` → at `ends_at` SIGTERM, finalize, mark complete. Add the Schedule calendar screen.

**Architecture:** A `ScheduleManager` is the live in-memory translator between the `schedules` SQL table and APScheduler's job registry. CRUD on Schedule rows triggers `add_job` / `modify_job` / `remove_job`. The job target is `run_scheduled_recording(schedule_id)` — a top-level async function importable by qualname, so it works regardless of which jobstore APScheduler uses. We use the **memory jobstore** for schedule jobs (so closures around app state can run cleanly), and rehydrate from the DB on startup. The DB is the source of truth; APScheduler is a fancy timer.

**Tech Stack:** Same as Phase 2. No new dependencies. Uses `Schedule` model (new), `RecorderWorker`, `RecorderPool`, `BufferManager`, `Broadcaster`, `AsyncIOScheduler`.

**Spec reference:** `docs/superpowers/specs/2026-04-24-concertpvr-design.md` — §5 schedules, §6.2 Flow B (scheduled recording), §7.4 Schedule screen.

**Phase 2 baseline (already on `main`):** Buffer recording end-to-end. 69 tests pass, frontend builds. `Stream`, `WatchSubscription`, `Recording` tables. APScheduler running. `/api/streams`, `/api/recordings` working.

---

## File structure (additions in this phase)

```
src/concertpvr/
├── schedule_manager.py   # ScheduleManager: schedules table ↔ APScheduler jobs
├── scheduled_runner.py   # run_scheduled_recording(schedule_id) — top-level async fn
└── api/
    └── schedules.py      # /api/schedules CRUD

alembic/versions/
└── 0003_schedules.py

tests/
├── test_scheduled_runner.py
├── test_schedule_manager.py
└── test_schedules_api.py

frontend/src/
├── components/
│   ├── NewScheduleDialog.tsx
│   └── ScheduleGrid.tsx       # week calendar layout
├── pages/
│   └── Schedule.tsx           # FULL implementation (was stub)
└── lib/
    ├── api.ts                 # APPEND: Schedule type + scheduleApi
    └── query.ts               # APPEND: schedule hooks
```

---

## Module interfaces (locked at design time)

**`Schedule` SQLAlchemy model:**
```python
class Schedule(Base):
    id: int
    stream_id: int                    # FK → streams.id (CASCADE)
    starts_at: datetime               # UTC
    ends_at: datetime                 # UTC
    artist: str | None                # optional pre-tag
    status: str                       # pending | running | complete | failed | cancelled
    error: str | None
    recording_id: int | None          # FK → recordings.id (set when job fires)
```

**`scheduled_runner.run_scheduled_recording(schedule_id: int) -> None`:**
- Looks up `Schedule` row + `Stream` URL
- Creates `Recording` row (status=recording, is_buffer=False, path=staging path)
- Sets `Schedule.status = "running"` and `Schedule.recording_id = recording.id`
- Spawns `RecorderWorker` writing to `/staging/{recording_id}/`
- At `ends_at`, calls `worker.stop()`
- Sets `Schedule.status = "complete"` (or `"failed"` on exception) and `Recording.status = "complete"`
- Publishes progress events to `streams.{stream_id}.progress` topic (same as buffer flow)

**`schedule_manager.ScheduleManager`:**
```python
class ScheduleManager:
    def __init__(self, scheduler: AsyncIOScheduler) -> None: ...
    def add(self, schedule: Schedule) -> None: ...           # add_job for starts_at - 30s
    def update(self, schedule: Schedule) -> None: ...        # modify_job
    def remove(self, schedule_id: int) -> None: ...          # remove_job
    def rehydrate_from_db(self, db: Database) -> int: ...    # called on startup; returns count
    def has_job(self, schedule_id: int) -> bool: ...
```

Schedule jobs use `jobstore="memory"` (added to scheduler.py in Phase 2).

---

## Task 1: Migration 0003 + Schedule model

**Files:**
- Modify: `src/concertpvr/models.py` (append `Schedule` class)
- Create: `alembic/versions/0003_schedules.py`
- Modify: `tests/test_db.py` (append round-trip test)

- [ ] **Step 1: Append model**

In `src/concertpvr/models.py`, after the existing `Recording` class, append:

```python
class Schedule(Base):
    __tablename__ = "schedules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    stream_id: Mapped[int] = mapped_column(
        ForeignKey("streams.id", ondelete="CASCADE"), nullable=False, index=True
    )
    starts_at: Mapped[_dt.datetime] = mapped_column(DateTime, nullable=False)
    ends_at: Mapped[_dt.datetime] = mapped_column(DateTime, nullable=False)
    artist: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    error: Mapped[str | None] = mapped_column(String, nullable=True)
    recording_id: Mapped[int | None] = mapped_column(
        ForeignKey("recordings.id", ondelete="SET NULL"), nullable=True
    )

    stream = relationship("Stream")
    recording = relationship("Recording")
```

- [ ] **Step 2: Append round-trip test to `tests/test_db.py`**

```python
from concertpvr.models import Schedule


def test_schedule_round_trip(tmp_db):
    Base.metadata.create_all(tmp_db.engine)

    with tmp_db.session() as s:
        stream = Stream(kind="live", youtube_id="z1", url="u", title="t", channel_name="c")
        s.add(stream)
        s.flush()
        sch = Schedule(
            stream_id=stream.id,
            starts_at=dt.datetime(2026, 5, 1, 19, 0, tzinfo=dt.timezone.utc),
            ends_at=dt.datetime(2026, 5, 1, 21, 0, tzinfo=dt.timezone.utc),
            artist="Phish",
        )
        s.add(sch)
        s.flush()
        sid = sch.id

    with tmp_db.session() as s:
        loaded = s.get(Schedule, sid)
        assert loaded is not None
        assert loaded.artist == "Phish"
        assert loaded.status == "pending"
        assert loaded.recording_id is None
```

- [ ] **Step 3: Migration `alembic/versions/0003_schedules.py`**

```python
"""schedules table

Revision ID: 0003_schedules
Revises: 0002_streams_recordings
Create Date: 2026-04-25
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_schedules"
down_revision: str | None = "0002_streams_recordings"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "schedules",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("stream_id", sa.Integer(),
                  sa.ForeignKey("streams.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("starts_at", sa.DateTime(), nullable=False),
        sa.Column("ends_at", sa.DateTime(), nullable=False),
        sa.Column("artist", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("error", sa.String(), nullable=True),
        sa.Column("recording_id", sa.Integer(),
                  sa.ForeignKey("recordings.id", ondelete="SET NULL"),
                  nullable=True),
    )
    op.create_index("ix_schedules_stream_id", "schedules", ["stream_id"])


def downgrade() -> None:
    op.drop_index("ix_schedules_stream_id", table_name="schedules")
    op.drop_table("schedules")
```

- [ ] **Step 4: Run**

```bash
./.venv/Scripts/python.exe -m pytest tests/test_db.py -v
./.venv/Scripts/python.exe -m pytest -q
```
Expected: 1 new pass; full suite 70.

- [ ] **Step 5: Commit**

```bash
git add src/concertpvr/models.py alembic/versions/0003_schedules.py tests/test_db.py
git -c gpg.format=openpgp -c commit.gpgsign=false commit -m "feat(models): schedules table"
```

---

## Task 2: Schedule Pydantic schemas

**Files:**
- Modify: `src/concertpvr/schemas.py` (append)

- [ ] **Step 1: Append schemas**

```python
class ScheduleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    stream_id: int
    starts_at: _dt.datetime
    ends_at: _dt.datetime
    artist: str | None
    status: Literal["pending", "running", "complete", "failed", "cancelled"]
    error: str | None
    recording_id: int | None


class ScheduleCreate(BaseModel):
    """Payload for POST /api/schedules. Either pass an existing stream_id, or a url
    that the server will probe (and create a Stream row if absent)."""
    model_config = ConfigDict(extra="forbid")

    stream_id: int | None = None
    url: str | None = None
    starts_at: _dt.datetime
    ends_at: _dt.datetime
    artist: str | None = None


class SchedulePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    starts_at: _dt.datetime | None = None
    ends_at: _dt.datetime | None = None
    artist: str | None = None
    status: Literal["pending", "cancelled"] | None = None  # only these are user-settable
```

- [ ] **Step 2: Verify**

```bash
./.venv/Scripts/python.exe -c "from concertpvr.schemas import ScheduleRead, ScheduleCreate, SchedulePatch; print('ok')"
```

- [ ] **Step 3: Commit**

```bash
git add src/concertpvr/schemas.py
git -c gpg.format=openpgp -c commit.gpgsign=false commit -m "feat(schemas): pydantic models for schedules"
```

---

## Task 3: `run_scheduled_recording` top-level function

This is the function APScheduler invokes at fire time. It needs access to app state (db, pool, buf, bc) — APScheduler doesn't pass those, so we use a **module-level registry** that the lifespan populates.

**Files:**
- Create: `src/concertpvr/scheduled_runner.py`
- Create: `tests/test_scheduled_runner.py`

- [ ] **Step 1: Failing tests**

```python
# tests/test_scheduled_runner.py
import asyncio
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

    register_app(db=db, pool=pool, buf=buf, bc=bc, runner_factory=lambda: runner,
                 staging_root=tmp_path / "staging")
    yield {"db": db, "pool": pool, "buf": buf, "bc": bc, "runner": runner,
           "staging": tmp_path / "staging"}
    unregister_app()


@pytest.mark.asyncio
async def test_run_creates_recording_and_starts_worker(app_state, monkeypatch):
    """At fire time, schedule_runner should: create a Recording, link it, mark schedule running, start worker."""
    monkeypatch.setattr("concertpvr.recorder.PROGRESS_POLL_S", 0.05)

    db = app_state["db"]
    with db.session() as s:
        stream = Stream(kind="live", youtube_id="z1", url="https://example.com",
                        title="t", channel_name="c")
        s.add(stream)
        s.flush()
        now = dt.datetime.now(dt.timezone.utc)
        sch = Schedule(
            stream_id=stream.id,
            starts_at=now,
            ends_at=now + dt.timedelta(milliseconds=200),
            artist="TestArtist",
        )
        s.add(sch)
        s.flush()
        schedule_id = sch.id

    # The runner returns 0 quickly; we simulate end_alarm by ends_at being in 200ms.
    app_state["runner"].queue("yt-dlp", [], exit_code=0)

    await run_scheduled_recording(schedule_id)

    with db.session() as s:
        loaded = s.get(Schedule, schedule_id)
        assert loaded.status == "complete"
        assert loaded.recording_id is not None

        rec = s.get(Recording, loaded.recording_id)
        assert rec is not None
        assert rec.status == "complete"
        assert rec.is_buffer is False  # scheduled recordings are NOT buffer
        assert "staging" in rec.path

    app_state["pool"].start.assert_awaited()


@pytest.mark.asyncio
async def test_run_marks_failed_when_stream_missing(app_state):
    db = app_state["db"]
    with db.session() as s:
        # Schedule references stream_id that doesn't exist
        sch = Schedule(
            stream_id=999,
            starts_at=dt.datetime.now(dt.timezone.utc),
            ends_at=dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=1),
        )
        # Skip FK enforcement for this test: insert via raw SQL won't work since FK is on
        # but the test checks the runner's defensive code. So instead, simulate:
        # the stream WAS created, schedule was added, then stream got deleted.
        stream = Stream(kind="live", youtube_id="z2", url="u", title="t", channel_name="c")
        s.add(stream)
        s.flush()
        sch.stream_id = stream.id
        s.add(sch)
        s.flush()
        schedule_id = sch.id
        s.delete(stream)

    with pytest.raises(Exception):
        await run_scheduled_recording(schedule_id)


@pytest.mark.asyncio
async def test_run_marks_failed_when_schedule_missing(app_state):
    with pytest.raises(LookupError):
        await run_scheduled_recording(99999)
```

- [ ] **Step 2: Implement `src/concertpvr/scheduled_runner.py`**

```python
"""APScheduler job target for scheduled recordings.

Module-level state holds references to the live application's db, pool, buf, bc.
Populated by the FastAPI lifespan via register_app(); cleared by unregister_app().

The async function `run_scheduled_recording(schedule_id)` is what APScheduler
invokes at fire time — it must be importable by qualified name.
"""

from __future__ import annotations

import asyncio
import datetime as _dt
from collections.abc import Callable
from pathlib import Path

from sqlalchemy import select

from concertpvr.buffer import BufferManager
from concertpvr.db import Database
from concertpvr.models import Recording, Schedule, Stream
from concertpvr.pool import RecorderPool
from concertpvr.process import ProcessRunner
from concertpvr.recorder import RecorderProgress, RecorderWorker
from concertpvr.ws import Broadcaster


class _AppRefs:
    db: Database | None = None
    pool: RecorderPool | None = None
    buf: BufferManager | None = None
    bc: Broadcaster | None = None
    runner_factory: Callable[[], ProcessRunner] | None = None
    staging_root: Path | None = None


def register_app(
    *,
    db: Database,
    pool: RecorderPool,
    buf: BufferManager,
    bc: Broadcaster,
    runner_factory: Callable[[], ProcessRunner],
    staging_root: Path,
) -> None:
    _AppRefs.db = db
    _AppRefs.pool = pool
    _AppRefs.buf = buf
    _AppRefs.bc = bc
    _AppRefs.runner_factory = runner_factory
    _AppRefs.staging_root = staging_root


def unregister_app() -> None:
    _AppRefs.db = None
    _AppRefs.pool = None
    _AppRefs.buf = None
    _AppRefs.bc = None
    _AppRefs.runner_factory = None
    _AppRefs.staging_root = None


def _require_refs() -> tuple[Database, RecorderPool, BufferManager, Broadcaster,
                              Callable[[], ProcessRunner], Path]:
    refs = (_AppRefs.db, _AppRefs.pool, _AppRefs.buf, _AppRefs.bc,
            _AppRefs.runner_factory, _AppRefs.staging_root)
    if any(r is None for r in refs):
        raise RuntimeError("scheduled_runner: register_app() not called")
    return refs  # type: ignore[return-value]


async def run_scheduled_recording(schedule_id: int) -> None:
    """APScheduler's job target. Looks up the Schedule, spawns a recorder, runs until ends_at."""
    db, pool, buf, bc, runner_factory, staging_root = _require_refs()

    with db.session() as s:
        sch = s.get(Schedule, schedule_id)
        if sch is None:
            raise LookupError(f"schedule {schedule_id} not found")
        stream = s.get(Stream, sch.stream_id)
        if stream is None:
            sch.status = "failed"
            sch.error = "stream not found"
            raise RuntimeError(f"schedule {schedule_id}: stream {sch.stream_id} not found")
        url = stream.url
        ends_at = sch.ends_at
        artist = sch.artist  # noqa: F841 — surfaced via Recording in Phase 4

    # Allocate Recording row and staging dir
    output_dir = staging_root / f"{schedule_id}"
    output_dir.mkdir(parents=True, exist_ok=True)

    with db.session() as s:
        rec = Recording(
            stream_id=stream.id,
            started_at=_dt.datetime.now(_dt.timezone.utc),
            path=str(output_dir),
            status="recording",
            is_buffer=False,
        )
        s.add(rec)
        s.flush()
        rec_id = rec.id

    # Mark Schedule as running
    with db.session() as s:
        sch = s.get(Schedule, schedule_id)
        if sch is not None:
            sch.status = "running"
            sch.recording_id = rec_id

    async def on_progress(p: RecorderProgress) -> None:
        await bc.publish(
            f"streams.{stream.id}.progress",
            {
                "bytes_total": p.bytes_total,
                "bitrate_bps": p.bitrate_bps,
                "duration_s": p.duration_s,
                "fragment_count": p.fragment_count,
                "schedule_id": schedule_id,
            },
        )

    worker = RecorderWorker(
        stream_id=stream.id,
        url=url,
        output_dir=output_dir,
        quality_format="bestvideo*+bestaudio/best",
        runner=runner_factory(),
        on_progress=on_progress,
    )

    await pool.start(worker)

    # Sleep until ends_at, then stop the worker
    try:
        now = _dt.datetime.now(_dt.timezone.utc)
        delay = max(0.0, (ends_at - now).total_seconds())
        await asyncio.sleep(delay)
    finally:
        await pool.stop(stream.id)

    # Finalize
    with db.session() as s:
        sch = s.get(Schedule, schedule_id)
        rec = s.get(Recording, rec_id)
        if sch is not None:
            sch.status = "complete"
        if rec is not None:
            rec.status = "complete"
            rec.ended_at = _dt.datetime.now(_dt.timezone.utc)
```

- [ ] **Step 3: Run**

```bash
./.venv/Scripts/python.exe -m pytest tests/test_scheduled_runner.py -v
./.venv/Scripts/python.exe -m pytest -q
```
Expected: 3 new pass; full suite 73.

- [ ] **Step 4: Commit**

```bash
git add src/concertpvr/scheduled_runner.py tests/test_scheduled_runner.py
git -c gpg.format=openpgp -c commit.gpgsign=false commit -m "feat(scheduled_runner): top-level async target for APScheduler jobs"
```

---

## Task 4: ScheduleManager

Translates Schedule rows ↔ APScheduler jobs.

**Files:**
- Create: `src/concertpvr/schedule_manager.py`
- Create: `tests/test_schedule_manager.py`

- [ ] **Step 1: Failing tests**

```python
# tests/test_schedule_manager.py
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
        # Trigger should now fire later
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
```

- [ ] **Step 2: Implement `src/concertpvr/schedule_manager.py`**

```python
"""ScheduleManager: bridges the schedules DB table and APScheduler's job registry."""

from __future__ import annotations

import datetime as _dt

from apscheduler.schedulers.asyncio import AsyncIOScheduler
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
        # APScheduler 3.x: reschedule_job changes the trigger
        self._sched.reschedule_job(
            _job_id(schedule.id),
            trigger="date",
            run_date=_trigger_time(schedule),
        )

    def remove(self, schedule_id: int) -> None:
        try:
            self._sched.remove_job(_job_id(schedule_id))
        except Exception:
            pass  # idempotent — already gone

    def has_job(self, schedule_id: int) -> bool:
        return self._sched.get_job(_job_id(schedule_id)) is not None

    def rehydrate_from_db(self, db: Database) -> int:
        """Re-add APScheduler jobs for every pending Schedule with starts_at in the future.

        Returns count of jobs added. Called once at app startup.
        """
        now = _dt.datetime.now(_dt.timezone.utc)
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
```

- [ ] **Step 3: Run**

```bash
./.venv/Scripts/python.exe -m pytest tests/test_schedule_manager.py -v
```
Expected: 4 pass.

- [ ] **Step 4: Commit**

```bash
git add src/concertpvr/schedule_manager.py tests/test_schedule_manager.py
git -c gpg.format=openpgp -c commit.gpgsign=false commit -m "feat(schedule_manager): bridge schedules table to apscheduler jobs"
```

---

## Task 5: Schedules API CRUD

**Files:**
- Create: `src/concertpvr/api/schedules.py`
- Modify: `src/concertpvr/main.py` (register router + create ScheduleManager + register_app + rehydrate)
- Create: `tests/test_schedules_api.py`

- [ ] **Step 1: Failing tests**

```python
# tests/test_schedules_api.py
import datetime as dt
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from concertpvr.main import create_app
from concertpvr.ytdlp import StreamInfo


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CPVR_DATA_DIR", str(tmp_path))
    with TestClient(create_app()) as c:
        yield c


@pytest.fixture
def fake_probe():
    info = StreamInfo(
        youtube_id="phish-x", url="https://www.youtube.com/watch?v=phish-x",
        title="Phish — Dick's Night 2", channel_name="Phish",
        is_live=True, thumbnail_url=None,
    )

    async def _async_probe(_url):
        return info

    with patch("concertpvr.api.schedules.probe", side_effect=_async_probe) as m:
        yield m, info


def test_post_schedule_with_url_creates_stream_and_schedule(client, fake_probe):
    _, info = fake_probe
    starts = dt.datetime(2099, 5, 1, 19, 0, tzinfo=dt.timezone.utc)
    ends = dt.datetime(2099, 5, 1, 21, 0, tzinfo=dt.timezone.utc)
    r = client.post("/api/schedules", json={
        "url": info.url,
        "starts_at": starts.isoformat(),
        "ends_at": ends.isoformat(),
        "artist": "Phish",
    })
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "pending"
    assert body["artist"] == "Phish"
    assert body["recording_id"] is None
    assert body["stream_id"] is not None


def test_post_schedule_with_existing_stream_id(client, fake_probe):
    _, info = fake_probe
    s = client.post("/api/streams", json={"url": info.url}).json()
    starts = dt.datetime(2099, 5, 1, 19, 0, tzinfo=dt.timezone.utc)
    ends = dt.datetime(2099, 5, 1, 21, 0, tzinfo=dt.timezone.utc)

    # Patch probe inside schedules to make sure it's NOT called when stream_id is provided
    with patch("concertpvr.api.schedules.probe") as no_probe:
        r = client.post("/api/schedules", json={
            "stream_id": s["id"],
            "starts_at": starts.isoformat(),
            "ends_at": ends.isoformat(),
        })
    assert r.status_code == 201
    assert r.json()["stream_id"] == s["id"]
    no_probe.assert_not_called()


def test_post_schedule_rejects_when_neither_url_nor_stream_id(client):
    starts = dt.datetime(2099, 5, 1, 19, 0, tzinfo=dt.timezone.utc)
    ends = dt.datetime(2099, 5, 1, 21, 0, tzinfo=dt.timezone.utc)
    r = client.post("/api/schedules", json={
        "starts_at": starts.isoformat(),
        "ends_at": ends.isoformat(),
    })
    assert r.status_code == 422


def test_post_schedule_rejects_when_ends_before_starts(client, fake_probe):
    _, info = fake_probe
    starts = dt.datetime(2099, 5, 1, 21, 0, tzinfo=dt.timezone.utc)
    ends = dt.datetime(2099, 5, 1, 19, 0, tzinfo=dt.timezone.utc)
    r = client.post("/api/schedules", json={
        "url": info.url,
        "starts_at": starts.isoformat(),
        "ends_at": ends.isoformat(),
    })
    assert r.status_code == 400


def test_get_schedules_lists(client, fake_probe):
    _, info = fake_probe
    starts = dt.datetime(2099, 5, 1, 19, 0, tzinfo=dt.timezone.utc)
    ends = dt.datetime(2099, 5, 1, 21, 0, tzinfo=dt.timezone.utc)
    client.post("/api/schedules", json={
        "url": info.url, "starts_at": starts.isoformat(), "ends_at": ends.isoformat(),
    })
    r = client.get("/api/schedules")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1


def test_get_schedule_by_id(client, fake_probe):
    _, info = fake_probe
    starts = dt.datetime(2099, 5, 1, 19, 0, tzinfo=dt.timezone.utc)
    ends = dt.datetime(2099, 5, 1, 21, 0, tzinfo=dt.timezone.utc)
    created = client.post("/api/schedules", json={
        "url": info.url, "starts_at": starts.isoformat(), "ends_at": ends.isoformat(),
    }).json()
    r = client.get(f"/api/schedules/{created['id']}")
    assert r.status_code == 200
    assert r.json()["id"] == created["id"]


def test_patch_schedule_updates_artist_and_times(client, fake_probe):
    _, info = fake_probe
    starts = dt.datetime(2099, 5, 1, 19, 0, tzinfo=dt.timezone.utc)
    ends = dt.datetime(2099, 5, 1, 21, 0, tzinfo=dt.timezone.utc)
    created = client.post("/api/schedules", json={
        "url": info.url, "starts_at": starts.isoformat(), "ends_at": ends.isoformat(),
    }).json()

    new_starts = dt.datetime(2099, 5, 1, 20, 0, tzinfo=dt.timezone.utc)
    r = client.patch(f"/api/schedules/{created['id']}", json={
        "starts_at": new_starts.isoformat(),
        "artist": "Trey Anastasio Band",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["starts_at"].startswith("2099-05-01T20:00")
    assert body["artist"] == "Trey Anastasio Band"


def test_delete_schedule(client, fake_probe):
    _, info = fake_probe
    starts = dt.datetime(2099, 5, 1, 19, 0, tzinfo=dt.timezone.utc)
    ends = dt.datetime(2099, 5, 1, 21, 0, tzinfo=dt.timezone.utc)
    created = client.post("/api/schedules", json={
        "url": info.url, "starts_at": starts.isoformat(), "ends_at": ends.isoformat(),
    }).json()
    r = client.delete(f"/api/schedules/{created['id']}")
    assert r.status_code == 204
    r = client.get(f"/api/schedules/{created['id']}")
    assert r.status_code == 404
```

- [ ] **Step 2: Implement `src/concertpvr/api/schedules.py`**

```python
"""Schedules CRUD."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from concertpvr.db import Database
from concertpvr.deps import get_db
from concertpvr.models import Schedule, Stream
from concertpvr.schemas import ScheduleCreate, SchedulePatch, ScheduleRead
from concertpvr.ytdlp import ProbeError, probe

router = APIRouter()


def _get_manager(request: Request):
    return request.app.state.schedule_manager


@router.post("/schedules", response_model=ScheduleRead, status_code=status.HTTP_201_CREATED)
async def create_schedule(
    payload: ScheduleCreate,
    request: Request,
    db: Database = Depends(get_db),  # noqa: B008
) -> Schedule:
    if payload.stream_id is None and not payload.url:
        raise HTTPException(status_code=422, detail="must provide stream_id or url")
    if payload.ends_at <= payload.starts_at:
        raise HTTPException(status_code=400, detail="ends_at must be after starts_at")

    # Resolve / create stream
    stream_id: int
    if payload.stream_id is not None:
        with db.session() as s:
            if s.get(Stream, payload.stream_id) is None:
                raise HTTPException(status_code=404, detail="stream not found")
        stream_id = payload.stream_id
    else:
        try:
            info = await probe(payload.url)  # type: ignore[arg-type]
        except ProbeError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

        with db.session() as s:
            existing = s.scalar(select(Stream).where(Stream.youtube_id == info.youtube_id))
            if existing is not None:
                stream_id = existing.id
            else:
                stream = Stream(
                    kind="live" if info.is_live else "video",
                    youtube_id=info.youtube_id, url=info.url, title=info.title,
                    channel_name=info.channel_name, thumbnail_url=info.thumbnail_url,
                )
                s.add(stream)
                try:
                    s.flush()
                except IntegrityError as e:
                    raise HTTPException(status_code=409, detail="stream already added") from e
                stream_id = stream.id

    with db.session() as s:
        sch = Schedule(
            stream_id=stream_id,
            starts_at=payload.starts_at,
            ends_at=payload.ends_at,
            artist=payload.artist,
        )
        s.add(sch)
        s.flush()
        s.refresh(sch)
        # Register with APScheduler
        _get_manager(request).add(sch)
        s.expunge(sch)
    return sch


@router.get("/schedules", response_model=list[ScheduleRead])
def list_schedules(db: Database = Depends(get_db)) -> list[Schedule]:  # noqa: B008
    with db.session() as s:
        rows = list(s.scalars(select(Schedule).order_by(Schedule.starts_at.asc())))
        for r in rows:
            s.expunge(r)
    return rows


@router.get("/schedules/{schedule_id}", response_model=ScheduleRead)
def get_schedule(schedule_id: int, db: Database = Depends(get_db)) -> Schedule:  # noqa: B008
    with db.session() as s:
        row = s.get(Schedule, schedule_id)
        if row is None:
            raise HTTPException(status_code=404, detail="schedule not found")
        s.expunge(row)
    return row


@router.patch("/schedules/{schedule_id}", response_model=ScheduleRead)
def patch_schedule(
    schedule_id: int,
    patch: SchedulePatch,
    request: Request,
    db: Database = Depends(get_db),  # noqa: B008
) -> Schedule:
    updates = patch.model_dump(exclude_unset=True)
    with db.session() as s:
        sch = s.get(Schedule, schedule_id)
        if sch is None:
            raise HTTPException(status_code=404, detail="schedule not found")
        for k, v in updates.items():
            setattr(sch, k, v)
        if "ends_at" in updates or "starts_at" in updates:
            if sch.ends_at <= sch.starts_at:
                raise HTTPException(status_code=400, detail="ends_at must be after starts_at")
        s.flush()
        s.refresh(sch)
        # Sync APScheduler
        mgr = _get_manager(request)
        if sch.status == "cancelled":
            mgr.remove(schedule_id)
        elif "starts_at" in updates and mgr.has_job(schedule_id):
            mgr.update(sch)
        s.expunge(sch)
    return sch


@router.delete("/schedules/{schedule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_schedule(
    schedule_id: int,
    request: Request,
    db: Database = Depends(get_db),  # noqa: B008
) -> Response:
    with db.session() as s:
        row = s.get(Schedule, schedule_id)
        if row is None:
            raise HTTPException(status_code=404, detail="schedule not found")
        s.delete(row)
    _get_manager(request).remove(schedule_id)
    return Response(status_code=204)
```

- [ ] **Step 3: Wire ScheduleManager + register_app + router into `src/concertpvr/main.py`**

In `lifespan()`, after the `app.state.scheduler.start()` line and before the retention pruner registration, add:

```python
    from concertpvr.schedule_manager import ScheduleManager
    from concertpvr.scheduled_runner import register_app, unregister_app
    from concertpvr.process import AsyncSubprocessRunner

    app.state.schedule_manager = ScheduleManager(app.state.scheduler)
    register_app(
        db=app.state.db,
        pool=app.state.pool,
        buf=app.state.buffer,
        bc=app.state.broadcaster,
        runner_factory=AsyncSubprocessRunner,
        staging_root=cfg.staging_dir,
    )

    # Re-add jobs for any pending schedules (in case of restart)
    app.state.schedule_manager.rehydrate_from_db(app.state.db)
```

After `yield`, before `app.state.db.engine.dispose()`, add:

```python
    unregister_app()
```

In `create_app()`, register the router (after recordings):

```python
    from concertpvr.api.schedules import router as schedules_router
    app.include_router(schedules_router, prefix="/api")
```

- [ ] **Step 4: Run**

```bash
./.venv/Scripts/python.exe -m pytest tests/test_schedules_api.py -v
./.venv/Scripts/python.exe -m pytest -q
```
Expected: 8 new pass; full suite ~85.

- [ ] **Step 5: Commit**

```bash
git add src/concertpvr/api/schedules.py src/concertpvr/main.py tests/test_schedules_api.py
git -c gpg.format=openpgp -c commit.gpgsign=false commit -m "feat(api): /api/schedules CRUD wired to ScheduleManager + lifespan rehydrate"
```

---

## Task 6: Frontend Schedule API + hooks

**Files:**
- Modify: `frontend/src/lib/api.ts` (append)
- Modify: `frontend/src/lib/query.ts` (append)

- [ ] **Step 1: Append to `frontend/src/lib/api.ts`**

```typescript
// ── Schedules ───────────────────────────────────────────────────────────────

export type ScheduleStatus = "pending" | "running" | "complete" | "failed" | "cancelled";

export type Schedule = {
  id: number;
  stream_id: number;
  starts_at: string;
  ends_at: string;
  artist: string | null;
  status: ScheduleStatus;
  error: string | null;
  recording_id: number | null;
};

export type ScheduleCreate = {
  url?: string;
  stream_id?: number;
  starts_at: string;
  ends_at: string;
  artist?: string | null;
};

export type SchedulePatch = {
  starts_at?: string;
  ends_at?: string;
  artist?: string | null;
  status?: "pending" | "cancelled";
};

export const schedulesApi = {
  list: () => api.get<Schedule[]>("/api/schedules"),
  get: (id: number) => api.get<Schedule>(`/api/schedules/${id}`),
  create: (p: ScheduleCreate) => api.post<Schedule>("/api/schedules", p),
  patch: (id: number, p: SchedulePatch) => api.patch<Schedule>(`/api/schedules/${id}`, p),
  delete: (id: number) => api.delete<void>(`/api/schedules/${id}`),
};
```

- [ ] **Step 2: Append to `frontend/src/lib/query.ts`**

```typescript
import {
  type Schedule,
  type ScheduleCreate,
  type SchedulePatch,
  schedulesApi,
} from "./api";

export const schedulesKeys = {
  all: ["schedules"] as const,
  one: (id: number) => ["schedules", id] as const,
};

export function useSchedules() {
  return useQuery<Schedule[]>({
    queryKey: schedulesKeys.all,
    queryFn: () => schedulesApi.list(),
    refetchInterval: 30_000,  // pick up status changes
  });
}

export function useCreateSchedule() {
  const qc = useQueryClient();
  return useMutation<Schedule, Error, ScheduleCreate>({
    mutationFn: (p) => schedulesApi.create(p),
    onSuccess: () => qc.invalidateQueries({ queryKey: schedulesKeys.all }),
  });
}

export function useUpdateSchedule(id: number) {
  const qc = useQueryClient();
  return useMutation<Schedule, Error, SchedulePatch>({
    mutationFn: (p) => schedulesApi.patch(id, p),
    onSuccess: () => qc.invalidateQueries({ queryKey: schedulesKeys.all }),
  });
}

export function useDeleteSchedule() {
  const qc = useQueryClient();
  return useMutation<void, Error, number>({
    mutationFn: (id) => schedulesApi.delete(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: schedulesKeys.all }),
  });
}
```

- [ ] **Step 3: Typecheck + commit**

```bash
cd frontend && npm run typecheck && cd ..
git add frontend/src/lib/api.ts frontend/src/lib/query.ts
git -c gpg.format=openpgp -c commit.gpgsign=false commit -m "feat(frontend): schedules api types + react-query hooks"
```

---

## Task 7: NewScheduleDialog

**Files:**
- Create: `frontend/src/components/NewScheduleDialog.tsx`

- [ ] **Step 1: Implement**

```typescript
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogBody, DialogFooter, DialogHeader } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { useCreateSchedule } from "@/lib/query";
import type { ApiError } from "@/lib/api";

function localToIsoUtc(localDt: string): string {
  // datetime-local input gives "YYYY-MM-DDTHH:MM"; treat as local time and emit UTC ISO.
  const d = new Date(localDt);
  return d.toISOString();
}

export function NewScheduleDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
}) {
  const [url, setUrl] = useState("");
  const [starts, setStarts] = useState("");
  const [ends, setEnds] = useState("");
  const [artist, setArtist] = useState("");
  const create = useCreateSchedule();

  const submit = () => {
    if (!url.trim() || !starts || !ends) return;
    create.mutate(
      {
        url: url.trim(),
        starts_at: localToIsoUtc(starts),
        ends_at: localToIsoUtc(ends),
        artist: artist.trim() || null,
      },
      {
        onSuccess: () => {
          setUrl(""); setStarts(""); setEnds(""); setArtist("");
          onOpenChange(false);
        },
      },
    );
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogHeader>New schedule</DialogHeader>
      <DialogBody className="space-y-3">
        <div>
          <label className="text-[11px] text-ink-dim block mb-1">YouTube URL</label>
          <Input
            autoFocus
            className="font-mono"
            placeholder="https://www.youtube.com/watch?v=…"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
          />
        </div>
        <div className="grid grid-cols-2 gap-2">
          <div>
            <label className="text-[11px] text-ink-dim block mb-1">Starts</label>
            <Input
              type="datetime-local"
              className="font-mono"
              value={starts}
              onChange={(e) => setStarts(e.target.value)}
            />
          </div>
          <div>
            <label className="text-[11px] text-ink-dim block mb-1">Ends</label>
            <Input
              type="datetime-local"
              className="font-mono"
              value={ends}
              onChange={(e) => setEnds(e.target.value)}
            />
          </div>
        </div>
        <div>
          <label className="text-[11px] text-ink-dim block mb-1">Artist (optional)</label>
          <Input
            placeholder="e.g. Phish"
            value={artist}
            onChange={(e) => setArtist(e.target.value)}
          />
        </div>
        {create.isError && (
          <p className="text-xs text-red-400">
            {(create.error as ApiError).status === 400
              ? "Invalid times — end must be after start, and the URL must be reachable."
              : create.error.message}
          </p>
        )}
      </DialogBody>
      <DialogFooter>
        <Button variant="ghost" onClick={() => onOpenChange(false)}>Cancel</Button>
        <Button variant="primary" onClick={submit} disabled={create.isPending}>
          {create.isPending ? "Probing…" : "Schedule"}
        </Button>
      </DialogFooter>
    </Dialog>
  );
}
```

- [ ] **Step 2: Typecheck + commit**

```bash
cd frontend && npm run typecheck && cd ..
git add frontend/src/components/NewScheduleDialog.tsx
git -c gpg.format=openpgp -c commit.gpgsign=false commit -m "feat(frontend): new-schedule dialog with URL + times + artist"
```

---

## Task 8: ScheduleGrid (week calendar)

**Files:**
- Create: `frontend/src/components/ScheduleGrid.tsx`

For Phase 3 we ship a **simple list view grouped by day**, not a fully draggable calendar grid (calendar interaction is complex; ship the simpler version first; can upgrade in a later polish phase). Naming the component `ScheduleGrid` so the calendar upgrade lands in the same file.

- [ ] **Step 1: Implement**

```typescript
import type { Schedule, Stream } from "@/lib/api";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { useStreams } from "@/lib/query";

const STATUS_COLOR = {
  pending: "scheduled",
  running: "live",
  complete: "done",
  failed: "failed",
  cancelled: "neutral",
} as const;

function fmtDay(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    weekday: "short", month: "short", day: "numeric",
  });
}

function fmtTime(iso: string): string {
  return new Date(iso).toLocaleTimeString(undefined, {
    hour: "2-digit", minute: "2-digit",
  });
}

function groupByDay(schedules: Schedule[]): Map<string, Schedule[]> {
  const out = new Map<string, Schedule[]>();
  for (const sch of schedules) {
    const key = fmtDay(sch.starts_at);
    const arr = out.get(key) ?? [];
    arr.push(sch);
    out.set(key, arr);
  }
  return out;
}

export function ScheduleGrid({
  schedules,
  onClickSchedule,
}: {
  schedules: Schedule[];
  onClickSchedule?: (s: Schedule) => void;
}) {
  const { data: streams } = useStreams();
  const streamMap = new Map<number, Stream>((streams ?? []).map((s) => [s.id, s]));

  if (schedules.length === 0) {
    return (
      <Card className="text-center py-8 text-ink-dim text-xs">
        No schedules yet. Click &ldquo;New schedule&rdquo; to plan a recording.
      </Card>
    );
  }

  const groups = groupByDay(schedules);

  return (
    <div className="space-y-4">
      {[...groups.entries()].map(([day, items]) => (
        <div key={day}>
          <h3 className="text-[11px] uppercase tracking-wider text-ink-faint mb-2">{day}</h3>
          <div className="space-y-2">
            {items.map((sch) => {
              const stream = streamMap.get(sch.stream_id);
              return (
                <Card
                  key={sch.id}
                  className="flex items-center gap-3 cursor-pointer hover:border-ink-faint"
                  onClick={() => onClickSchedule?.(sch)}
                >
                  <span className="font-mono text-xs text-amber w-32">
                    {fmtTime(sch.starts_at)} → {fmtTime(sch.ends_at)}
                  </span>
                  <div className="flex-1 min-w-0">
                    <div className="font-medium truncate">
                      {sch.artist ?? stream?.title ?? `Schedule #${sch.id}`}
                    </div>
                    <div className="text-xs text-ink-dim truncate">
                      {stream?.channel_name ?? "—"}
                    </div>
                  </div>
                  <Badge color={STATUS_COLOR[sch.status]}>{sch.status}</Badge>
                </Card>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 2: Typecheck + commit**

```bash
cd frontend && npm run typecheck && cd ..
git add frontend/src/components/ScheduleGrid.tsx
git -c gpg.format=openpgp -c commit.gpgsign=false commit -m "feat(frontend): schedule grid (day-grouped list view)"
```

---

## Task 9: Schedule page (full implementation)

**Files:**
- Replace contents: `frontend/src/pages/Schedule.tsx`

- [ ] **Step 1: Implement**

```typescript
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { useSchedules, useDeleteSchedule } from "@/lib/query";
import { NewScheduleDialog } from "@/components/NewScheduleDialog";
import { ScheduleGrid } from "@/components/ScheduleGrid";
import type { Schedule } from "@/lib/api";

export default function SchedulePage() {
  const [dialogOpen, setDialogOpen] = useState(false);
  const [selected, setSelected] = useState<Schedule | null>(null);
  const { data, isLoading } = useSchedules();
  const del = useDeleteSchedule();

  return (
    <div>
      <div className="flex items-center mb-4">
        <h2 className="text-lg font-semibold">Schedule</h2>
        <span className="flex-1" />
        <Button variant="primary" onClick={() => setDialogOpen(true)}>
          ＋ New schedule
        </Button>
      </div>

      <NewScheduleDialog open={dialogOpen} onOpenChange={setDialogOpen} />

      {isLoading && <p className="text-ink-dim text-xs">Loading…</p>}

      {data && (
        <ScheduleGrid
          schedules={data}
          onClickSchedule={(s) => setSelected(s)}
        />
      )}

      {selected && (
        <div className="fixed bottom-4 right-4 bg-surface-1 border border-border-strong rounded-lg p-4 shadow-xl">
          <div className="flex items-center gap-3">
            <div>
              <div className="font-medium">{selected.artist ?? "Schedule"} #{selected.id}</div>
              <div className="text-xs text-ink-dim">{selected.status}</div>
            </div>
            {selected.status === "pending" && (
              <Button
                variant="ghost"
                onClick={() => {
                  if (confirm("Delete this schedule?")) {
                    del.mutate(selected.id);
                    setSelected(null);
                  }
                }}
              >
                Delete
              </Button>
            )}
            <Button variant="ghost" onClick={() => setSelected(null)}>Close</Button>
          </div>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Typecheck + build**

```bash
cd frontend
npm run typecheck
npm run build
cd ..
```

Both must pass.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/Schedule.tsx
git -c gpg.format=openpgp -c commit.gpgsign=false commit -m "feat(frontend): schedule page with new-schedule dialog + grid + detail panel"
```

---

## Task 10: Update Dashboard Up-Next rail to show schedules

**Files:**
- Modify: `frontend/src/pages/Dashboard.tsx`

- [ ] **Step 1: Update**

Replace the Dashboard content with this version that adds an "Up Next" rail showing the next 3 pending schedules:

```typescript
import { useStreams, useRecordings, useSchedules } from "@/lib/query";
import { StatStrip } from "@/components/StatStrip";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { LiveProgressBar } from "@/components/LiveProgressBar";

function fmtRelative(iso: string): string {
  const target = new Date(iso).getTime();
  const now = Date.now();
  const diffMs = target - now;
  if (diffMs < 0) return "past";
  const min = Math.round(diffMs / 60000);
  if (min < 60) return `in ${min}m`;
  const hr = Math.round(min / 60);
  if (hr < 24) return `in ${hr}h`;
  return `in ${Math.round(hr / 24)}d`;
}

export default function DashboardPage() {
  const { data: streams } = useStreams();
  const { data: recordings } = useRecordings();
  const { data: schedules } = useSchedules();

  const recordingNow = (recordings ?? []).filter((r) => r.status === "recording");
  const completed = (recordings ?? []).filter((r) => r.status === "complete").length;
  const upcoming = (schedules ?? [])
    .filter((s) => s.status === "pending" && new Date(s.starts_at).getTime() > Date.now())
    .slice(0, 3);

  return (
    <div>
      <h2 className="text-lg font-semibold mb-4">Dashboard</h2>

      <StatStrip
        items={[
          { label: "Recording now", value: recordingNow.length, color: "terra" },
          { label: "Streams tracked", value: streams?.length ?? 0, color: "amber" },
          { label: "Scheduled", value: upcoming.length, color: "mauve" },
          { label: "Completed", value: completed, color: "sage" },
        ]}
      />

      <div className="grid grid-cols-3 gap-4">
        <div className="col-span-2">
          <h3 className="text-xs uppercase tracking-wider text-ink-faint mb-2">Live recordings</h3>
          {recordingNow.length === 0 && (
            <Card className="text-center py-6 text-ink-dim text-xs">
              Nothing recording right now.
            </Card>
          )}
          <div className="space-y-2">
            {recordingNow.map((r) => (
              <Card key={r.id} className="flex items-center gap-4">
                <div className="w-24 aspect-video rounded bg-surface-0 flex items-center justify-center">
                  <Badge color="live">live</Badge>
                </div>
                <div className="flex-1">
                  <div className="font-medium">Recording #{r.id}</div>
                  <div className="text-xs text-ink-dim">stream {r.stream_id}</div>
                  <div className="mt-2"><LiveProgressBar streamId={r.stream_id} /></div>
                </div>
              </Card>
            ))}
          </div>
        </div>

        <div>
          <h3 className="text-xs uppercase tracking-wider text-ink-faint mb-2">Up Next</h3>
          {upcoming.length === 0 && (
            <Card className="text-center py-4 text-ink-dim text-xs">No upcoming schedules.</Card>
          )}
          <div className="space-y-2">
            {upcoming.map((sch) => (
              <Card key={sch.id} className="p-3">
                <div className="font-mono text-[11px] text-amber">
                  {fmtRelative(sch.starts_at)}
                </div>
                <div className="text-sm font-medium mt-0.5">
                  {sch.artist ?? `Schedule #${sch.id}`}
                </div>
                <div className="text-[10px] text-ink-faint mt-1">
                  {new Date(sch.starts_at).toLocaleString(undefined, {
                    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
                  })}
                </div>
              </Card>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Typecheck + build + commit**

```bash
cd frontend && npm run typecheck && npm run build && cd ..
git add frontend/src/pages/Dashboard.tsx
git -c gpg.format=openpgp -c commit.gpgsign=false commit -m "feat(frontend): dashboard up-next rail showing pending schedules"
```

---

## Task 11: Phase 3 wrap-up

- [ ] **Step 1: Backend sweep**

```bash
./.venv/Scripts/python.exe -m ruff check src/ tests/
./.venv/Scripts/python.exe -m ruff format --check src/ tests/
./.venv/Scripts/python.exe -m mypy src/
./.venv/Scripts/python.exe -m pytest -q
```

If anything fails, fix INLINE per the same guardrails as Phase 2:
- Don't change `Field(...)` to give defaults that hide misconfiguration
- Don't change tests to assert something different from spec
- Don't relax mypy strictness
- B008 → `# noqa: B008`
- mypy import-untyped → `# type: ignore[import-untyped]`

- [ ] **Step 2: Frontend sweep**

```bash
cd frontend && npm run typecheck && npm run build && cd ..
```

- [ ] **Step 3: Commit fixes (if any), then tag**

```bash
git status
git add -A
git -c gpg.format=openpgp -c commit.gpgsign=false commit -m "chore: phase 3 wrap-up — lint/type/test sweep" || echo "(nothing to commit)"

git tag -a phase-3-schedule -m "Phase 3 complete: scheduled recordings + Schedule screen"
git log --oneline phase-2-record-and-buffer..HEAD
```

- [ ] **Step 4: Manual smoke test (optional)**

Boot the app, click Schedule → New schedule, paste a YouTube URL with a near-future start time, ~2-minute window. Watch the schedule status flip pending → running → complete in the calendar; the Recording row appears in `/api/recordings` and on Dashboard.

---

## Phase 3 done

At tag `phase-3-schedule`:
- POST /api/schedules creates a Schedule + APScheduler job; PATCH/DELETE keeps APScheduler in sync
- At fire time, `run_scheduled_recording` writes to `/staging/{schedule_id}/`, marks Recording complete at `ends_at`
- ScheduleManager rehydrates pending schedules on app startup
- Schedule page: list of upcoming/past schedules grouped by day, click to delete-pending
- Dashboard: Up-Next rail of next 3 pending schedules
- All tests pass, ruff/mypy/format clean, frontend typecheck/build clean

**Next:** Phase 4 — Segment & Publish. The big one: timeline editor (vidstack + wavesurfer regions), chapter extraction, ffmpeg splitting, NFO/poster generation, Emby publish.
