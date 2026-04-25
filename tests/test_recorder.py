import asyncio
from pathlib import Path

import pytest

from concertpvr.process import FakeProcessRunner
from concertpvr.recorder import RecorderProgress, RecorderWorker


@pytest.mark.asyncio
async def test_recorder_invokes_yt_dlp_with_correct_args(tmp_path: Path):
    fake = FakeProcessRunner()
    fake.queue("yt-dlp", [], exit_code=0)

    progress: list[RecorderProgress] = []

    async def cb(p: RecorderProgress) -> None:
        progress.append(p)

    worker = RecorderWorker(
        stream_id=42,
        url="https://www.youtube.com/watch?v=abc123",
        output_dir=tmp_path,
        quality_format="bestvideo*+bestaudio/best",
        runner=fake,
        on_progress=cb,
    )
    rc = await worker.run()
    assert rc == 0
    assert len(fake.spawned) == 1
    argv = fake.spawned[0]
    assert argv[0] == "yt-dlp"
    assert "--live-from-start" in argv
    assert "--hls-prefer-native" in argv
    assert "https://www.youtube.com/watch?v=abc123" in argv
    assert any(a == "-f" for a in argv)


@pytest.mark.asyncio
async def test_recorder_emits_progress_when_fragments_appear(tmp_path: Path, monkeypatch):
    """While yt-dlp is 'running', the recorder polls the output dir and emits progress."""
    monkeypatch.setattr("concertpvr.recorder.PROGRESS_POLL_S", 0.05)

    fake = FakeProcessRunner()
    fake.queue("yt-dlp", [], exit_code=0, blocking=True)

    progress: list[RecorderProgress] = []

    async def cb(p: RecorderProgress) -> None:
        progress.append(p)

    worker = RecorderWorker(
        stream_id=1,
        url="https://example.com",
        output_dir=tmp_path,
        quality_format="best",
        runner=fake,
        on_progress=cb,
    )

    async def write_fragments():
        await asyncio.sleep(0.06)
        (tmp_path / "00.ts").write_bytes(b"x" * 1000)
        await asyncio.sleep(0.06)
        (tmp_path / "01.ts").write_bytes(b"y" * 2000)
        await asyncio.sleep(0.06)  # allow one more poll to pick up both fragments
        worker.stop()

    await asyncio.gather(worker.run(), write_fragments())

    assert len(progress) >= 1
    last = progress[-1]
    assert last.bytes_total == 3000
    assert last.fragment_count == 2


@pytest.mark.asyncio
async def test_recorder_stop_triggers_terminate(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("concertpvr.recorder.PROGRESS_POLL_S", 0.05)

    fake = FakeProcessRunner()
    fake.queue("yt-dlp", [], exit_code=0, blocking=True)

    async def noop(_p):
        return None

    worker = RecorderWorker(
        stream_id=1, url="u", output_dir=tmp_path,
        quality_format="best", runner=fake, on_progress=noop,
    )

    async def stop_soon():
        await asyncio.sleep(0.05)
        worker.stop()

    rc, _ = await asyncio.gather(worker.run(), stop_soon())
    assert rc != 0
