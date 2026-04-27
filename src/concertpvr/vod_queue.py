"""VOD download queue — concurrency-capped FIFO.

State lives on Recording rows. enqueue() appends to an asyncio queue; workers
pull and call the handler. The handler is responsible for transitioning
status from vod_queued → vod_downloading → complete/vod_failed and writing
the source file. The queue itself only routes work and handles handler
exceptions defensively.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from sqlalchemy import select

from concertpvr.db import Database
from concertpvr.models import Recording

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
            try:
                await self._handler(rec_id)
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
                self._queue.task_done()

    def is_idle(self) -> bool:
        return self._queue.empty()
