"""VOD download cancellation — vod_queued + vod_downloading paths.

Covers v0.4: cancel(rec_id) on a queued recording marks it vod_cancelled
without invoking the handler; cancel() on a running recording terminates
the registered subprocess so the handler observes VodCancelled.
"""

import asyncio
import datetime as _dt
import itertools

import pytest

from concertpvr.db import Database
from concertpvr.models import Base, Recording, Stream
from concertpvr.vod_downloader import VodCancelled
from concertpvr.vod_queue import VodQueue

_counter = itertools.count(1)


@pytest.fixture
def db(tmp_path):
    d = Database(f"sqlite:///{tmp_path / 'q.db'}")
    Base.metadata.create_all(d.engine)
    return d


def _seed_recording(db: Database, status: str = "vod_queued") -> int:
    uid = next(_counter)
    with db.session() as s:
        st = Stream(
            kind="video", youtube_id=f"vid{uid}", url=f"u{uid}", title="t", channel_name="c"
        )
        s.add(st)
        s.flush()
        rec = Recording(
            stream_id=st.id,
            started_at=_dt.datetime.now(_dt.UTC),
            path=f"/tmp/x{uid}",
            status=status,
            is_buffer=False,
        )
        s.add(rec)
        s.flush()
        return rec.id


@pytest.mark.asyncio
async def test_cancel_queued_skips_handler_and_marks_cancelled(db):
    processed: list[int] = []

    async def handler(rec_id: int) -> None:
        processed.append(rec_id)

    q = VodQueue(db=db, handler=handler, max_concurrent=1)

    r1 = _seed_recording(db)
    r2 = _seed_recording(db)

    # Cancel r1 before workers start. enqueue both, then start workers.
    await q.enqueue(r1)
    await q.enqueue(r2)

    result = await q.cancel(r1)
    assert result == "queued"

    await q.start_workers()
    await q.wait_for_idle()
    await q.stop()

    # Only r2 was processed; r1 was skipped.
    assert processed == [r2]
    with db.session() as s:
        assert s.get(Recording, r1).status == "vod_cancelled"
        assert s.get(Recording, r2).status == "vod_queued"  # handler is no-op so status unchanged


@pytest.mark.asyncio
async def test_cancel_running_terminates_subprocess(db):
    """Handler registers a fake proc, gets cancelled, raises VodCancelled."""

    handler_started = asyncio.Event()
    handler_completed = asyncio.Event()

    class FakeProc:
        def __init__(self) -> None:
            self.pid = 99
            self._terminated = asyncio.Event()
            self.terminate_called = False

        def terminate(self) -> None:
            self.terminate_called = True
            self._terminated.set()

        def kill(self) -> None:
            self._terminated.set()

        async def wait(self) -> int:
            await self._terminated.wait()
            return -15  # SIGTERM

        async def stdout_lines(self):  # type: ignore[no-untyped-def]
            return
            yield

        async def stderr_lines(self):  # type: ignore[no-untyped-def]
            return
            yield

    proc = FakeProc()

    async def handler(rec_id: int) -> None:
        q.register_running(rec_id, proc)
        handler_started.set()
        try:
            exit_code = await proc.wait()
            if exit_code < 0:
                raise VodCancelled(f"signalled {-exit_code}")
        finally:
            q.unregister_running(rec_id)
            handler_completed.set()

    q = VodQueue(db=db, handler=handler, max_concurrent=1)
    await q.start_workers()

    rid = _seed_recording(db)
    await q.enqueue(rid)
    await asyncio.wait_for(handler_started.wait(), timeout=2.0)

    result = await q.cancel(rid)
    assert result == "running"
    assert proc.terminate_called

    await asyncio.wait_for(handler_completed.wait(), timeout=2.0)
    await q.wait_for_idle()
    await q.stop()

    with db.session() as s:
        rec = s.get(Recording, rid)
        assert rec.status == "vod_cancelled"
        # cancel path clears any prior error
        assert rec.error is None


@pytest.mark.asyncio
async def test_cancel_unknown_returns_not_found(db):
    async def handler(rec_id: int) -> None:
        return

    q = VodQueue(db=db, handler=handler, max_concurrent=1)
    result = await q.cancel(99999)
    assert result == "not_found"


@pytest.mark.asyncio
async def test_cancel_complete_recording_returns_not_found(db):
    async def handler(rec_id: int) -> None:
        return

    q = VodQueue(db=db, handler=handler, max_concurrent=1)
    rid = _seed_recording(db, status="complete")
    result = await q.cancel(rid)
    # Not in FIFO, not running, status not 'vod_queued' → not_found.
    assert result == "not_found"
