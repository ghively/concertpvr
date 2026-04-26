"""Periodic buffer retention pruner."""

from collections.abc import Awaitable, Callable

from sqlalchemy import select

from concertpvr.buffer import BufferManager
from concertpvr.db import Database
from concertpvr.models import WatchSubscription


def build_prune_job(db: Database, buf: BufferManager) -> Callable[[], Awaitable[None]]:
    async def prune() -> None:
        with db.session() as s:
            subs = list(s.scalars(select(WatchSubscription)))
            pairs = [(sub.stream_id, sub.retention_days) for sub in subs]
        for stream_id, retention in pairs:
            buf.prune_older_than(stream_id, retention)

    return prune
