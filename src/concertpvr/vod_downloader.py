"""yt-dlp finite-file VOD download wrapper.

Different from recorder.py: targets a single output file, --continue for
resume, expects exit-0 on success. Progress lines have determinate %, eta_s,
and total bytes (vs live where total is unknown).
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from concertpvr.process import ProcessRunner

logger = logging.getLogger(__name__)


class VodDownloadError(Exception):
    """yt-dlp exited non-zero when downloading a VOD."""


@dataclass(frozen=True)
class VodProgress:
    pct: float  # 0..100
    bytes_total: int | None
    bitrate_bps: int | None
    eta_s: int | None


_PROGRESS_RE = re.compile(
    r"\[download\]\s+(?P<pct>[\d.]+)%\s+of\s+(?P<total>[\d.]+)(?P<unit>[KMG]?i?B)"
    r"(?:\s+at\s+(?P<rate>[\d.]+|Unknown)(?P<rate_unit>[KMG]?i?B/s)?)?"
    r"(?:\s+ETA\s+(?P<eta>\d+:\d+(?::\d+)?|Unknown))?"
)


def _parse_size(value: str, unit: str) -> int:
    n = float(value)
    mult = 1
    u = unit.upper()
    if u.startswith("K"):
        mult = 1024
    elif u.startswith("M"):
        mult = 1024**2
    elif u.startswith("G"):
        mult = 1024**3
    return int(n * mult)


def _parse_eta(s: str) -> int | None:
    if s == "Unknown":
        return None
    parts = s.split(":")
    if len(parts) == 2:
        return int(parts[0]) * 60 + int(parts[1])
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
    return None


def _parse_progress_line(line: str) -> VodProgress | None:
    m = _PROGRESS_RE.search(line)
    if not m:
        return None
    pct = float(m.group("pct"))
    total = _parse_size(m.group("total"), m.group("unit"))
    rate = m.group("rate")
    rate_unit = m.group("rate_unit")
    bitrate: int | None = None
    if rate and rate != "Unknown" and rate_unit:
        bitrate = _parse_size(rate, rate_unit) * 8  # bytes/s → bits/s
    eta = _parse_eta(m.group("eta")) if m.group("eta") else None
    return VodProgress(pct=pct, bytes_total=total, bitrate_bps=bitrate, eta_s=eta)


class VodDownloader:
    def __init__(self, *, runner: ProcessRunner) -> None:
        self._runner = runner

    async def download(
        self,
        *,
        url: str,
        output_path: Path,
        quality_format: str,
        cookies_path: Path | None,
        on_progress: Callable[[VodProgress], Awaitable[None]] | None,
    ) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)

        args: list[str] = [
            "yt-dlp",
            "--continue",
            "--no-part",
            "--no-playlist",
            "-f",
            quality_format,
            "-o",
            str(output_path),
        ]
        if cookies_path:
            args.extend(["--cookies", str(cookies_path)])
        args.append(url)

        last_stderr: list[str] = []
        last_stdout: list[str] = []

        proc = await self._runner.spawn(args)

        async def drain_stdout() -> None:
            async for line in proc.stdout_lines():
                last_stdout.append(line)
                progress = _parse_progress_line(line)
                if progress is not None and on_progress is not None:
                    await on_progress(progress)

        async def drain_stderr() -> None:
            async for line in proc.stderr_lines():
                if line:
                    last_stderr.append(line)
                    if len(last_stderr) > 50:
                        last_stderr.pop(0)

        await asyncio.gather(drain_stdout(), drain_stderr())
        exit_code = await proc.wait()

        if exit_code != 0:
            # Include stdout errors too (yt-dlp may write "ERROR:" to stdout)
            combined = last_stderr + last_stdout
            tail = "\n".join(combined[-10:]) or "yt-dlp exited %d" % exit_code
            raise VodDownloadError(tail)
