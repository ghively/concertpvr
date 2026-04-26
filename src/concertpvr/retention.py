"""Periodic buffer retention pruner."""

import logging
import shutil
from collections.abc import Awaitable, Callable

from sqlalchemy import select

from concertpvr.buffer import BufferManager
from concertpvr.db import Database
from concertpvr.models import Settings, WatchSubscription

logger = logging.getLogger(__name__)

# When auto_prune_when_full is enabled, kick in once free space drops below
# this fraction of the filesystem (5%).
LOW_FREE_THRESHOLD: float = 0.05
# Target this much free space after pruning (10%) — gives some headroom so we
# don't trigger again on every tick.
TARGET_FREE_RATIO: float = 0.10


def build_prune_job(db: Database, buf: BufferManager) -> Callable[[], Awaitable[None]]:
    async def prune() -> None:
        # Per-subscription retention pruning (always runs).
        with db.session() as s:
            subs = list(s.scalars(select(WatchSubscription)))
            pairs = [(sub.stream_id, sub.retention_days) for sub in subs]
            row = s.get(Settings, 1)
            auto_prune = row.auto_prune_when_full if row is not None else False
        for stream_id, retention in pairs:
            buf.prune_older_than(stream_id, retention)

        # Auto-prune when disk is critically full, ignoring per-stream retention.
        if auto_prune and buf.free_space_ratio() < LOW_FREE_THRESHOLD:
            try:
                total = shutil.disk_usage(buf.root).total
            except OSError:
                return
            target = int(total * TARGET_FREE_RATIO)
            freed = buf.prune_oldest_until_free(target)
            if freed > 0:
                logger.warning(
                    "auto-prune-when-full freed %d bytes (target free: %d)", freed, target
                )

    return prune
