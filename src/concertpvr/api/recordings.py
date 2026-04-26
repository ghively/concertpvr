"""Recordings read API."""

from __future__ import annotations

import datetime as _dt
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select

from concertpvr.chapters import extract_chapters_json
from concertpvr.db import Database
from concertpvr.deps import get_db
from concertpvr.models import Recording
from concertpvr.schemas import RecordingRead

router = APIRouter()


@router.get("/recordings", response_model=list[RecordingRead])
def list_recordings(
    stream_id: int | None = Query(None),
    db: Database = Depends(get_db),  # noqa: B008
) -> list[Recording]:
    with db.session() as s:
        stmt = select(Recording).order_by(Recording.started_at.desc())
        if stream_id is not None:
            stmt = stmt.where(Recording.stream_id == stream_id)
        rows = list(s.scalars(stmt))
        for r in rows:
            s.expunge(r)
    return rows


@router.get("/recordings/{recording_id}", response_model=RecordingRead)
def get_recording(
    recording_id: int,
    db: Database = Depends(get_db),  # noqa: B008
) -> Recording:
    with db.session() as s:
        row = s.get(Recording, recording_id)
        if row is None:
            raise HTTPException(status_code=404, detail="recording not found")
        s.expunge(row)
    return row


@router.post("/recordings/{recording_id}/finalize", response_model=RecordingRead)
def finalize_recording(
    recording_id: int,
    db: Database = Depends(get_db),  # noqa: B008
) -> Recording:
    """Mark a recording complete + capture chapter metadata from its path.

    Triggers the auto_segment listener which creates draft Segments.
    """
    with db.session() as s:
        rec = s.get(Recording, recording_id)
        if rec is None:
            raise HTTPException(status_code=404, detail="recording not found")
        chapters = extract_chapters_json(Path(rec.path))
        if chapters is not None:
            rec.raw_chapters_json = chapters
        rec.status = "complete"
        rec.ended_at = _dt.datetime.now(_dt.UTC)
        s.flush()
        s.refresh(rec)
        s.expunge(rec)
    return rec
