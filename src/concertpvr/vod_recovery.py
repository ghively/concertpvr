"""On startup, transition crashed `vod_downloading` rows back to `vod_queued`.

Mirror of orphan_recovery.py but for the VOD path. Safe because the queue
hasn't started workers yet — any `vod_downloading` row is a real interrupt.
"""

from __future__ import annotations

import logging

from sqlalchemy import select

from concertpvr.db import Database
from concertpvr.models import Recording

logger = logging.getLogger(__name__)


def mark_vod_downloads_interrupted_on_startup(db: Database) -> int:
    count = 0
    with db.session() as s:
        rows = list(s.scalars(select(Recording).where(Recording.status == "vod_downloading")))
        for rec in rows:
            rec.status = "vod_queued"
            count += 1
    if count:
        logger.warning(
            "vod_recovery: requeued %d in-flight VOD download(s) interrupted by restart",
            count,
        )
    return count
