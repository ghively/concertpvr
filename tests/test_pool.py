from pathlib import Path

import pytest

from concertpvr.pool import RecorderPool
from concertpvr.process import FakeProcessRunner
from concertpvr.recorder import RecorderWorker


def _make_worker(stream_id: int, tmp: Path, runner, *, blocking: bool = False) -> RecorderWorker:
    runner.queue("yt-dlp", [], exit_code=0, blocking=blocking)

    async def noop(_p):
        return None

    return RecorderWorker(
        stream_id=stream_id, url=f"u{stream_id}", output_dir=tmp / str(stream_id),
        quality_format="best", runner=runner, on_progress=noop,
    )


@pytest.mark.asyncio
async def test_pool_starts_worker_and_marks_recording(tmp_path):
    runner = FakeProcessRunner()
    pool = RecorderPool(max_concurrent=4)

    w = _make_worker(1, tmp_path, runner)
    await pool.start(w)
    assert pool.is_recording(1)
    assert 1 in pool.active_stream_ids()

    await pool.wait_all()
    assert not pool.is_recording(1)


@pytest.mark.asyncio
async def test_pool_stop_terminates_specific_worker(tmp_path, monkeypatch):
    monkeypatch.setattr("concertpvr.recorder.PROGRESS_POLL_S", 0.05)
    runner = FakeProcessRunner()
    pool = RecorderPool(max_concurrent=4)

    w = _make_worker(7, tmp_path, runner, blocking=True)
    await pool.start(w)
    assert pool.is_recording(7)

    await pool.stop(7)
    await pool.wait_all()
    assert not pool.is_recording(7)


@pytest.mark.asyncio
async def test_pool_rejects_duplicate_stream_id(tmp_path):
    runner = FakeProcessRunner()
    pool = RecorderPool(max_concurrent=4)

    w1 = _make_worker(1, tmp_path, runner)
    w2 = _make_worker(1, tmp_path, runner)
    await pool.start(w1)
    with pytest.raises(ValueError):
        await pool.start(w2)
    await pool.wait_all()


@pytest.mark.asyncio
async def test_pool_enforces_max_concurrent(tmp_path):
    runner = FakeProcessRunner()
    pool = RecorderPool(max_concurrent=2)

    w1 = _make_worker(1, tmp_path, runner)
    w2 = _make_worker(2, tmp_path, runner)
    w3 = _make_worker(3, tmp_path, runner)

    await pool.start(w1)
    await pool.start(w2)
    with pytest.raises(RuntimeError):
        await pool.start(w3)
    await pool.wait_all()
