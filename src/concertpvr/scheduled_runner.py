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
        stream_id = stream.id

    output_dir = staging_root / f"{schedule_id}"
    output_dir.mkdir(parents=True, exist_ok=True)

    with db.session() as s:
        rec = Recording(
            stream_id=stream_id,
            started_at=_dt.datetime.now(_dt.timezone.utc),
            path=str(output_dir),
            status="recording",
            is_buffer=False,
        )
        s.add(rec)
        s.flush()
        rec_id = rec.id

    with db.session() as s:
        sch = s.get(Schedule, schedule_id)
        if sch is not None:
            sch.status = "running"
            sch.recording_id = rec_id

    async def on_progress(p: RecorderProgress) -> None:
        await bc.publish(
            f"streams.{stream_id}.progress",
            {
                "bytes_total": p.bytes_total,
                "bitrate_bps": p.bitrate_bps,
                "duration_s": p.duration_s,
                "fragment_count": p.fragment_count,
                "schedule_id": schedule_id,
            },
        )

    worker = RecorderWorker(
        stream_id=stream_id,
        url=url,
        output_dir=output_dir,
        quality_format="bestvideo*+bestaudio/best",
        runner=runner_factory(),
        on_progress=on_progress,
    )

    await pool.start(worker)

    try:
        now = _dt.datetime.now(_dt.timezone.utc)
        # Both starts_at and ends_at should be timezone-aware UTC.
        # If ends_at lacks tz, treat as UTC.
        if ends_at.tzinfo is None:
            ends_at = ends_at.replace(tzinfo=_dt.timezone.utc)
        delay = max(0.0, (ends_at - now).total_seconds())
        await asyncio.sleep(delay)
    finally:
        await pool.stop(stream_id)

    with db.session() as s:
        sch = s.get(Schedule, schedule_id)
        rec = s.get(Recording, rec_id)
        if sch is not None:
            sch.status = "complete"
        if rec is not None:
            rec.status = "complete"
            rec.ended_at = _dt.datetime.now(_dt.timezone.utc)
