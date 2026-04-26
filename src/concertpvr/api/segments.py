"""Segments CRUD + publish."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import select

from concertpvr.db import Database
from concertpvr.deps import get_db
from concertpvr.models import Recording, Segment
from concertpvr.schemas import (
    PublishOptions, SegmentCreate, SegmentPatch, SegmentRead,
)

router = APIRouter()


@router.post("/segments", response_model=SegmentRead, status_code=status.HTTP_201_CREATED)
def create_segment(
    payload: SegmentCreate,
    db: Database = Depends(get_db),  # noqa: B008
) -> Segment:
    if payload.end_s <= payload.start_s:
        raise HTTPException(status_code=400, detail="end_s must be after start_s")
    with db.session() as s:
        if s.get(Recording, payload.recording_id) is None:
            raise HTTPException(status_code=404, detail="recording not found")
        seg = Segment(
            recording_id=payload.recording_id,
            artist=payload.artist,
            title=payload.title,
            start_s=payload.start_s,
            end_s=payload.end_s,
            source=payload.source,
            status="draft",
        )
        s.add(seg)
        s.flush()
        s.refresh(seg)
        s.expunge(seg)
    return seg


@router.get("/segments", response_model=list[SegmentRead])
def list_segments(
    recording_id: int | None = Query(None),
    db: Database = Depends(get_db),  # noqa: B008
) -> list[Segment]:
    with db.session() as s:
        stmt = select(Segment).order_by(Segment.start_s.asc())
        if recording_id is not None:
            stmt = stmt.where(Segment.recording_id == recording_id)
        rows = list(s.scalars(stmt))
        for r in rows:
            s.expunge(r)
    return rows


@router.get("/segments/{segment_id}", response_model=SegmentRead)
def get_segment(segment_id: int, db: Database = Depends(get_db)) -> Segment:  # noqa: B008
    with db.session() as s:
        row = s.get(Segment, segment_id)
        if row is None:
            raise HTTPException(status_code=404, detail="segment not found")
        s.expunge(row)
    return row


@router.patch("/segments/{segment_id}", response_model=SegmentRead)
def patch_segment(
    segment_id: int,
    patch: SegmentPatch,
    db: Database = Depends(get_db),  # noqa: B008
) -> Segment:
    updates = patch.model_dump(exclude_unset=True)
    with db.session() as s:
        seg = s.get(Segment, segment_id)
        if seg is None:
            raise HTTPException(status_code=404, detail="segment not found")
        for k, v in updates.items():
            setattr(seg, k, v)
        if seg.end_s <= seg.start_s:
            raise HTTPException(status_code=400, detail="end_s must be after start_s")
        s.flush()
        s.refresh(seg)
        s.expunge(seg)
    return seg


@router.delete("/segments/{segment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_segment(segment_id: int, db: Database = Depends(get_db)) -> Response:  # noqa: B008
    with db.session() as s:
        seg = s.get(Segment, segment_id)
        if seg is None:
            raise HTTPException(status_code=404, detail="segment not found")
        s.delete(seg)
    return Response(status_code=204)


@router.post("/segments/{segment_id}/publish", response_model=SegmentRead)
async def publish_segment(
    segment_id: int,
    options: PublishOptions,
    request: Request,
    db: Database = Depends(get_db),  # noqa: B008
) -> Segment:
    publisher = request.app.state.publisher_factory()
    try:
        await publisher.publish(
            segment_id,
            festival=options.festival,
            venue=options.venue,
            year=options.year,
        )
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    with db.session() as s:
        seg = s.get(Segment, segment_id)
        if seg is None:
            raise HTTPException(status_code=404, detail="segment not found post-publish")
        s.expunge(seg)
    return seg
