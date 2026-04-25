"""yt-dlp recording worker."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from time import monotonic

from concertpvr.process import ManagedProcess, ProcessRunner

PROGRESS_POLL_S: float = 1.0


@dataclass(frozen=True)
class RecorderProgress:
    bytes_total: int
    bitrate_bps: float
    duration_s: int
    fragment_count: int


class RecorderWorker:
    def __init__(
        self,
        *,
        stream_id: int,
        url: str,
        output_dir: Path,
        quality_format: str,
        runner: ProcessRunner,
        on_progress: Callable[[RecorderProgress], Awaitable[None]],
    ) -> None:
        self.stream_id = stream_id
        self.url = url
        self.output_dir = output_dir
        self.quality_format = quality_format
        self._runner = runner
        self._on_progress = on_progress
        self._proc: ManagedProcess | None = None
        self._stop_requested = False

    def _build_argv(self) -> list[str]:
        return [
            "yt-dlp",
            "--live-from-start",
            "--hls-prefer-native",
            "--newline",
            "--no-part",
            "-f", self.quality_format,
            "-o", str(self.output_dir / "%(epoch)s_%(id)s.%(ext)s"),
            self.url,
        ]

    async def run(self) -> int:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._proc = await self._runner.spawn(self._build_argv())
        # Handle stop() called before this coroutine had a chance to run.
        if self._stop_requested:
            self._proc.terminate()

        wait_task = asyncio.create_task(self._proc.wait())
        progress_task = asyncio.create_task(self._poll_progress())

        try:
            rc = await wait_task
        finally:
            progress_task.cancel()
            try:
                await progress_task
            except asyncio.CancelledError:
                pass

        return rc

    def stop(self) -> None:
        self._stop_requested = True
        if self._proc is not None:
            self._proc.terminate()

    async def _poll_progress(self) -> None:
        started = monotonic()
        last_bytes = 0
        last_emit = monotonic()
        while True:
            await asyncio.sleep(PROGRESS_POLL_S)
            now = monotonic()
            files = sorted(p for p in self.output_dir.glob("*") if p.is_file())
            total = sum(p.stat().st_size for p in files)
            elapsed = now - last_emit
            bitrate = ((total - last_bytes) * 8) / elapsed if elapsed > 0 else 0.0
            duration = int(now - started)
            await self._on_progress(
                RecorderProgress(
                    bytes_total=total,
                    bitrate_bps=bitrate,
                    duration_s=duration,
                    fragment_count=len(files),
                )
            )
            last_bytes = total
            last_emit = now
