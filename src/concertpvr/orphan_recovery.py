"""On startup, mark any Recording rows still in 'recording' state as 'interrupted'.

Spec §9 promises this resilience guarantee. If the app crashes mid-record, the row
stays `recording` forever and the UI shows it as live. This module fixes that
on every cold start. Safe because `register_app` runs after this — the recorder
pool is empty at startup, so any `status='recording'` row is a real orphan.
"""

from __future__ import annotations

import datetime as _dt
import logging

from sqlalchemy import select

from concertpvr.db import Database
from concertpvr.models import Recording

logger = logging.getLogger(__name__)


def mark_interrupted_on_startup(db: Database) -> int:
    """Mark all recordings still in 'recording' state as 'interrupted'.

    Returns count of rows updated.
    """
    count = 0
    with db.session() as s:
        rows = list(s.scalars(select(Recording).where(Recording.status == "recording")))
        now = _dt.datetime.now(_dt.UTC)
        for rec in rows:
            rec.status = "interrupted"
            if rec.ended_at is None:
                rec.ended_at = now
            count += 1
    if count:
        logger.warning("orphan_recovery: marked %d recording(s) as interrupted", count)
    return count
