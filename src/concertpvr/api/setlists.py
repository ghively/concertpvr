"""Setlist replace + paste endpoints."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, cast, runtime_checkable

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import delete, select

from concertpvr.db import Database
from concertpvr.deps import get_db
from concertpvr.models import Recording, Setlist
from concertpvr.schemas import SetlistRead, SetlistReplaceRequest
from concertpvr.setlist_parser import ParseError, parse_setlist_paste

router = APIRouter()


@runtime_checkable
class _Entry(Protocol):
    artist: str
    start_s: int
    end_s: int


def _replace_entries(db: Database, recording_id: int, entries: Sequence[_Entry]) -> list[Setlist]:
    with db.session() as s:
        if s.get(Recording, recording_id) is None:
            raise HTTPException(status_code=404, detail="recording not found")
        s.execute(delete(Setlist).where(Setlist.recording_id == recording_id))
        rows: list[Setlist] = []
        for e in entries:
            row = Setlist(
                recording_id=recording_id,
                artist=e.artist,
                start_s=e.start_s,
                end_s=e.end_s,
            )
            s.add(row)
            rows.append(row)
        s.flush()
        for r in rows:
            s.refresh(r)
            s.expunge(r)
    return rows


@router.get("/recordings/{recording_id}/setlist", response_model=list[SetlistRead])
def get_setlist(
    recording_id: int,
    db: Database = Depends(get_db),  # noqa: B008
) -> list[Setlist]:
    with db.session() as s:
        if s.get(Recording, recording_id) is None:
            raise HTTPException(status_code=404, detail="recording not found")
        rows = list(
            s.scalars(
                select(Setlist)
                .where(Setlist.recording_id == recording_id)
                .order_by(Setlist.start_s)
            )
        )
        for r in rows:
            s.expunge(r)
    return rows


@router.post("/recordings/{recording_id}/setlist", response_model=list[SetlistRead])
def post_setlist(
    recording_id: int,
    payload: SetlistReplaceRequest,
    db: Database = Depends(get_db),  # noqa: B008
) -> list[Setlist]:
    return _replace_entries(db, recording_id, payload.entries)


@router.post("/recordings/{recording_id}/setlist/paste", response_model=list[SetlistRead])
def post_setlist_paste(
    recording_id: int,
    body: bytes = Body(..., media_type="text/plain"),
    db: Database = Depends(get_db),  # noqa: B008
) -> list[Setlist]:
    text = body.decode("utf-8", errors="replace")
    try:
        parsed = parse_setlist_paste(text)
    except ParseError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return _replace_entries(db, recording_id, cast(Sequence[_Entry], parsed))
