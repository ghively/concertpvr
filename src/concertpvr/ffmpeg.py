"""ffmpeg subprocess wrapper for probing, cutting, and thumbnail extraction."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from concertpvr.process import ProcessRunner


@dataclass(frozen=True)
class ProbeInfo:
    duration_s: float
    width: int
    height: int
    fps: float


class FFmpegError(RuntimeError):
    pass


class Splitter:
    def __init__(self, runner: ProcessRunner) -> None:
        self._runner = runner

    async def probe(self, input_path: Path) -> ProbeInfo:
        argv = [
            "ffprobe", "-v", "error",
            "-print_format", "json",
            "-show_format", "-show_streams",
            str(input_path),
        ]
        proc = await self._runner.spawn(argv)
        stdout_chunks: list[str] = []
        async for line in proc.stdout_lines():
            stdout_chunks.append(line)
        rc = await proc.wait()
        if rc != 0:
            raise FFmpegError(f"ffprobe exited {rc} for {input_path}")
        data = json.loads("\n".join(stdout_chunks))
        video = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
        if video is None:
            raise FFmpegError(f"no video stream in {input_path}")

        duration_s = float(data.get("format", {}).get("duration", 0.0))
        width = int(video.get("width", 0))
        height = int(video.get("height", 0))
        fps_str = video.get("avg_frame_rate") or video.get("r_frame_rate") or "0/1"
        num, _, denom = fps_str.partition("/")
        denom_f = float(denom or "1") or 1.0
        fps = float(num) / denom_f

        return ProbeInfo(duration_s=duration_s, width=width, height=height, fps=fps)

    async def cut(
        self, input_path: Path, output_path: Path, start_s: float, end_s: float
    ) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        duration_s = end_s - start_s
        argv = [
            "ffmpeg", "-y",
            "-ss", f"{start_s:.3f}",
            "-i", str(input_path),
            "-t", f"{duration_s:.3f}",
            "-c:v", "libx264",
            "-c:a", "aac",
            str(output_path),
        ]
        proc = await self._runner.spawn(argv)
        async for _ in proc.stdout_lines():
            pass
        async for _ in proc.stderr_lines():
            pass
        rc = await proc.wait()
        if rc != 0:
            raise FFmpegError(f"ffmpeg exited {rc}")

    async def thumbnail(
        self, input_path: Path, output_path: Path, at_s: float
    ) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        argv = [
            "ffmpeg", "-y",
            "-ss", f"{at_s:.3f}",
            "-i", str(input_path),
            "-frames:v", "1",
            "-q:v", "2",
            str(output_path),
        ]
        proc = await self._runner.spawn(argv)
        async for _ in proc.stdout_lines():
            pass
        async for _ in proc.stderr_lines():
            pass
        rc = await proc.wait()
        if rc != 0:
            raise FFmpegError(f"ffmpeg thumbnail exited {rc}")
