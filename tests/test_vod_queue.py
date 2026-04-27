"""VodQueue — concurrency cap, FIFO, rehydration."""

import asyncio
import datetime as _dt
import itertools

import pytest

from concertpvr.db import Database
from concertpvr.models import Base, Recording, Stream
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
        st = Stream(kind="video", youtube_id=f"vid{uid}", url=f"u{uid}", title="t", channel_name="c")
        s.add(st)
        s.flush()
        rec = Recording(
            stream_id=st.id, started_at=_dt.datetime.now(_dt.UTC),
            path=f"/tmp/x{uid}", status=status, is_buffer=False,
        )
        s.add(rec)
        s.flush()
        return rec.id


@pytest.mark.asyncio
async def test_queue_enqueues_and_processes_in_fifo_order(db):
    processed: list[int] = []

    async def fake_handler(rec_id: int) -> None:
        processed.append(rec_id)

    q = VodQueue(db=db, handler=fake_handler, max_concurrent=1)
    await q.start_workers()

    r1 = _seed_recording(db)
    r2 = _seed_recording(db)
    r3 = _seed_recording(db)
    await q.enqueue(r1)
    await q.enqueue(r2)
    await q.enqueue(r3)

    await q.wait_for_idle()
    await q.stop()
    assert processed == [r1, r2, r3]


@pytest.mark.asyncio
async def test_queue_respects_concurrency_cap(db):
    in_flight = 0
    max_seen = 0

    async def slow_handler(rec_id: int) -> None:
        nonlocal in_flight, max_seen
        in_flight += 1
        max_seen = max(max_seen, in_flight)
        await asyncio.sleep(0.05)
        in_flight -= 1

    q = VodQueue(db=db, handler=slow_handler, max_concurrent=2)
    await q.start_workers()

    for _ in range(6):
        await q.enqueue(_seed_recording(db))

    await q.wait_for_idle()
    await q.stop()
    assert max_seen == 2


@pytest.mark.asyncio
async def test_queue_rehydrate_picks_up_existing_vod_queued(db):
    processed: list[int] = []

    async def handler(rec_id: int) -> None:
        processed.append(rec_id)

    r1 = _seed_recording(db, status="vod_queued")
    r2 = _seed_recording(db, status="vod_queued")

    q = VodQueue(db=db, handler=handler, max_concurrent=2)
    await q.start_workers()
    await q.rehydrate_from_db()

    await q.wait_for_idle()
    await q.stop()
    assert sorted(processed) == sorted([r1, r2])


@pytest.mark.asyncio
async def test_queue_handler_exception_marks_failed(db):
    async def failing_handler(rec_id: int) -> None:
        raise RuntimeError("boom")

    q = VodQueue(db=db, handler=failing_handler, max_concurrent=1)
    await q.start_workers()

    rid = _seed_recording(db)
    await q.enqueue(rid)
    await q.wait_for_idle()
    await q.stop()

    with db.session() as s:
        rec = s.get(Recording, rid)
        assert rec.status == "vod_failed"
        assert "boom" in (rec.error or "")
