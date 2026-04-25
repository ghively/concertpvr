import asyncio

import pytest

from concertpvr.process import (
    AsyncSubprocessRunner,
    FakeProcessRunner,
    ProcessRunner,
)


@pytest.mark.asyncio
async def test_fake_runner_streams_stdout_lines():
    fake = FakeProcessRunner()
    fake.queue("echo", ["hello\n", "world\n"], exit_code=0)
    proc = await fake.spawn(["echo"])

    lines: list[str] = []
    async for line in proc.stdout_lines():
        lines.append(line)
    assert lines == ["hello", "world"]
    assert await proc.wait() == 0


@pytest.mark.asyncio
async def test_fake_runner_records_argv():
    fake = FakeProcessRunner()
    fake.queue("yt-dlp", [], exit_code=0)
    await fake.spawn(["yt-dlp", "https://example.com", "-f", "best"])
    assert fake.spawned == [["yt-dlp", "https://example.com", "-f", "best"]]


@pytest.mark.asyncio
async def test_fake_runner_terminate_short_circuits_wait():
    fake = FakeProcessRunner()
    fake.queue("sleep", [], exit_code=0)
    proc = await fake.spawn(["sleep"])
    proc.terminate()
    rc = await proc.wait()
    assert rc != 0


@pytest.mark.asyncio
async def test_async_subprocess_runner_runs_real_command():
    """Smoke test against a real subprocess. Uses python -c so it works on Windows + Linux."""
    runner = AsyncSubprocessRunner()
    proc = await runner.spawn(["python", "-c", "print('alpha'); print('beta')"])
    lines = [line async for line in proc.stdout_lines()]
    assert lines == ["alpha", "beta"]
    assert await proc.wait() == 0


def test_process_runner_protocol_is_satisfied():
    real: ProcessRunner = AsyncSubprocessRunner()
    fake: ProcessRunner = FakeProcessRunner()
    assert hasattr(real, "spawn")
    assert hasattr(fake, "spawn")
