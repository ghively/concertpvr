"""Recordings read API."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select

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
