"""SQLAlchemy event listener: derive draft segments when a Recording becomes complete."""

from __future__ import annotations

from sqlalchemy import event, inspect, select
from sqlalchemy.orm import Session

from concertpvr.models import Recording, Segment
from concertpvr.segmenter import derive_draft_segments_no_flush

_registered = False


def _before_flush(session: Session, flush_context, instances) -> None:  # noqa: ANN001, ARG001
    for obj in session.dirty:
        if not isinstance(obj, Recording):
            continue
        insp = inspect(obj)
        status_history = insp.attrs.status.history
        if not status_history.has_changes():
            continue
        if obj.status != "complete":
            continue
        existing = session.scalar(
            select(Segment.id).where(Segment.recording_id == obj.id).limit(1)
        )
        if existing is None:
            derive_draft_segments_no_flush(obj, session)


def register() -> None:
    """Call once at app startup to install the listener (idempotent)."""
    global _registered
    if _registered:
        return
    event.listen(Session, "before_flush", _before_flush)
    _registered = True
