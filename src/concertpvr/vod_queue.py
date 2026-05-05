"""VOD download queue — concurrency-capped FIFO with cancellation.

State lives on Recording rows. enqueue() appends to an asyncio queue; workers
pull and call the handler. The handler is responsible for transitioning
status from vod_queued → vod_downloading → complete/vod_failed and writing
the source file. The queue itself only routes work and handles handler
exceptions defensively.

Cancellation: callers (API endpoint) call cancel(rec_id) which either
(a) marks the recording cancelled if it's still in the FIFO, or
(b) terminates the running yt-dlp subprocess if it's currently downloading.
The handler observes cancellation via VodCancelled raised from the downloader,
sets status='vod_cancelled' (transient), and the queue routes around it.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from sqlalchemy import select

from concertpvr.db import Database
from concertpvr.models import Recording
from concertpvr.process import ManagedProcess
from concertpvr.vod_downloader import VodCancelled

logger = logging.getLogger(__name__)


class VodQueue:
    def __init__(
        self,
        *,
        db: Database,
        handler: Callable[[int], Awaitable[None]],
        max_concurrent: int = 2,
    ) -> None:
        self._db = db
        self._handler = handler
        self._max_concurrent = max(1, max_concurrent)
        self._queue: asyncio.Queue[int] = asyncio.Queue()
        self._workers: list[asyncio.Task[None]] = []
        self._running = False
        # rec_id → live ManagedProcess. Populated when handler calls
        # register_running(); cleared on download completion or cancel.
        self._running_procs: dict[int, ManagedProcess] = {}
        # rec_ids the user explicitly cancelled while still in the FIFO. The
        # worker loop checks this set before invoking the handler.
        self._cancelled_queued: set[int] = set()

    async def enqueue(self, recording_id: int) -> None:
        await self._queue.put(recording_id)

    async def start_workers(self) -> None:
        if self._running:
            return
        self._running = True
        for i in range(self._max_concurrent):
            t = asyncio.create_task(self._worker_loop(i))
            self._workers.append(t)

    async def stop(self) -> None:
        self._running = False
        for _ in self._workers:
            await self._queue.put(-1)  # sentinel
        for t in self._workers:
            try:
                await asyncio.wait_for(t, timeout=5.0)
            except TimeoutError:
                t.cancel()
        self._workers.clear()

    def register_running(self, recording_id: int, proc: ManagedProcess) -> None:
        """Called by the handler when yt-dlp subprocess starts. Enables cancel()."""
        self._running_procs[recording_id] = proc

    def unregister_running(self, recording_id: int) -> None:
        """Called by the handler when the subprocess exits (success or failure)."""
        self._running_procs.pop(recording_id, None)

    def is_cancelled_queued(self, recording_id: int) -> bool:
        """Worker loop polls this to skip handler invocation for cancelled rows."""
        return recording_id in self._cancelled_queued

    def consume_cancelled_queued(self, recording_id: int) -> bool:
        """Atomically check-and-clear. True if the row was in the cancelled set."""
        if recording_id in self._cancelled_queued:
            self._cancelled_queued.discard(recording_id)
            return True
        return False

    async def cancel(self, recording_id: int) -> str:
        """Cancel a queued or running download.

        Returns:
            "queued" — was waiting in the FIFO; will be skipped when its turn comes
            "running" — was actively downloading; subprocess SIGTERMed
            "not_found" — neither queued nor running (already complete / never seen)
        """
        proc = self._running_procs.get(recording_id)
        if proc is not None:
            proc.terminate()
            return "running"
        # Not running — see whether it's still pending in the FIFO. We can't
        # peek the asyncio.Queue, so we use the persisted DB status as the source of truth.
        with self._db.session() as s:
            rec = s.get(Recording, recording_id)
            if rec is None:
                return "not_found"
            if rec.status == "vod_queued":
                self._cancelled_queued.add(recording_id)
                return "queued"
        return "not_found"

    async def cancel_by_youtube_id(self, youtube_id: str) -> None:
        """Cancel any queued/running recording for the given youtube_id.

        Used by /backlog/cancel after the Recording rows are deleted — best-effort
        cleanup of the in-memory queue state. Safe to call when the queue
        knows nothing about the id.
        """
        with self._db.session() as s:
            from concertpvr.models import Stream

            stream = s.scalar(select(Stream).where(Stream.youtube_id == youtube_id))
            if stream is None:
                return
            rec = s.scalar(
                select(Recording)
                .where(Recording.stream_id == stream.id)
                .where(Recording.status.in_(["vod_queued", "vod_downloading"]))
            )
            if rec is None:
                return
            rec_id = rec.id
        await self.cancel(rec_id)

    async def wait_for_idle(self) -> None:
        await self._queue.join()

    async def rehydrate_from_db(self) -> None:
        with self._db.session() as s:
            rows = list(
                s.scalars(
                    select(Recording).where(Recording.status == "vod_queued").order_by(Recording.id)
                )
            )
            ids = [r.id for r in rows]
        for rid in ids:
            await self._queue.put(rid)
        if ids:
            logger.info("vod_queue: rehydrated %d queued recording(s)", len(ids))

    async def _worker_loop(self, worker_id: int) -> None:
        while self._running:
            rec_id = await self._queue.get()
            if rec_id == -1:
                self._queue.task_done()
                return

            # Cancellation check before handler dispatch — the row may have
            # been cancelled while waiting in the FIFO.
            if self.consume_cancelled_queued(rec_id):
                with self._db.session() as s:
                    rec = s.get(Recording, rec_id)
                    if rec is not None and rec.status == "vod_queued":
                        rec.status = "vod_cancelled"
                self._queue.task_done()
                continue

            try:
                await self._handler(rec_id)
            except VodCancelled:
                # Handler observed mid-download cancel; mark cancelled and move on.
                with self._db.session() as s:
                    rec = s.get(Recording, rec_id)
                    if rec is not None:
                        rec.status = "vod_cancelled"
                        rec.error = None
                logger.info("vod_queue: rec %d cancelled mid-download", rec_id)
            except Exception as e:  # noqa: BLE001
                logger.exception(
                    "vod_queue worker %d: handler failed for rec %d", worker_id, rec_id
                )
                try:
                    with self._db.session() as s:
                        rec = s.get(Recording, rec_id)
                        if rec is not None:
                            rec.status = "vod_failed"
                            rec.error = f"{type(e).__name__}: {e}"[:500]
                except Exception:  # noqa: BLE001
                    logger.exception(
                        "vod_queue: failed to record vod_failed status for rec %d", rec_id
                    )
            finally:
                self.unregister_running(rec_id)
                self._queue.task_done()

    def is_idle(self) -> bool:
        return self._queue.empty()


__all__ = ["VodQueue", "VodCancelled"]
