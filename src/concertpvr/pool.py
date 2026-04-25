"""Pool of concurrent RecorderWorkers."""

from __future__ import annotations

import asyncio

from concertpvr.recorder import RecorderWorker


class RecorderPool:
    def __init__(self, max_concurrent: int) -> None:
        self.max_concurrent = max_concurrent
        self._workers: dict[int, RecorderWorker] = {}
        self._tasks: dict[int, asyncio.Task[int]] = {}

    async def start(self, worker: RecorderWorker) -> None:
        if worker.stream_id in self._workers:
            raise ValueError(f"already recording stream {worker.stream_id}")
        if len(self._workers) >= self.max_concurrent:
            raise RuntimeError(
                f"recorder pool at capacity ({self.max_concurrent})"
            )
        self._workers[worker.stream_id] = worker

        async def runner_task() -> int:
            try:
                return await worker.run()
            finally:
                self._workers.pop(worker.stream_id, None)
                self._tasks.pop(worker.stream_id, None)

        self._tasks[worker.stream_id] = asyncio.create_task(runner_task())

    async def stop(self, stream_id: int) -> None:
        worker = self._workers.get(stream_id)
        if worker is None:
            return
        worker.stop()
        task = self._tasks.get(stream_id)
        if task is not None:
            try:
                await task
            except Exception:
                pass

    def is_recording(self, stream_id: int) -> bool:
        return stream_id in self._workers

    def active_stream_ids(self) -> set[int]:
        return set(self._workers.keys())

    async def wait_all(self) -> None:
        if self._tasks:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)
