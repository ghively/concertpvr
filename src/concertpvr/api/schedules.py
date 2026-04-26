"""Schedules CRUD."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from concertpvr.db import Database
from concertpvr.deps import get_db
from concertpvr.models import Schedule, Stream
from concertpvr.schedule_manager import ScheduleManager
from concertpvr.schemas import ScheduleCreate, SchedulePatch, ScheduleRead
from concertpvr.ytdlp import ProbeError, probe

router = APIRouter()


def _get_manager(request: Request) -> ScheduleManager:
    return request.app.state.schedule_manager  # type: ignore[no-any-return]


@router.post("/schedules", response_model=ScheduleRead, status_code=status.HTTP_201_CREATED)
async def create_schedule(
    payload: ScheduleCreate,
    request: Request,
    db: Database = Depends(get_db),  # noqa: B008
) -> Schedule:
    if payload.stream_id is None and not payload.url:
        raise HTTPException(status_code=422, detail="must provide stream_id or url")
    if payload.ends_at <= payload.starts_at:
        raise HTTPException(status_code=400, detail="ends_at must be after starts_at")

    stream_id: int
    if payload.stream_id is not None:
        with db.session() as s:
            if s.get(Stream, payload.stream_id) is None:
                raise HTTPException(status_code=404, detail="stream not found")
        stream_id = payload.stream_id
    else:
        try:
            info = await probe(payload.url)  # type: ignore[arg-type]
        except ProbeError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

        with db.session() as s:
            existing = s.scalar(select(Stream).where(Stream.youtube_id == info.youtube_id))
            if existing is not None:
                stream_id = existing.id
            else:
                stream = Stream(
                    kind="live" if info.is_live else "video",
                    youtube_id=info.youtube_id,
                    url=info.url,
                    title=info.title,
                    channel_name=info.channel_name,
                    thumbnail_url=info.thumbnail_url,
                )
                s.add(stream)
                try:
                    s.flush()
                except IntegrityError as e:
                    raise HTTPException(status_code=409, detail="stream already added") from e
                stream_id = stream.id

    with db.session() as s:
        sch = Schedule(
            stream_id=stream_id,
            starts_at=payload.starts_at,
            ends_at=payload.ends_at,
            artist=payload.artist,
        )
        s.add(sch)
        s.flush()
        s.refresh(sch)
        _get_manager(request).add(sch)
        s.expunge(sch)
    return sch


@router.get("/schedules", response_model=list[ScheduleRead])
def list_schedules(db: Database = Depends(get_db)) -> list[Schedule]:  # noqa: B008
    with db.session() as s:
        rows = list(s.scalars(select(Schedule).order_by(Schedule.starts_at.asc())))
        for r in rows:
            s.expunge(r)
    return rows


@router.get("/schedules/{schedule_id}", response_model=ScheduleRead)
def get_schedule(schedule_id: int, db: Database = Depends(get_db)) -> Schedule:  # noqa: B008
    with db.session() as s:
        row = s.get(Schedule, schedule_id)
        if row is None:
            raise HTTPException(status_code=404, detail="schedule not found")
        s.expunge(row)
    return row


@router.patch("/schedules/{schedule_id}", response_model=ScheduleRead)
def patch_schedule(
    schedule_id: int,
    patch: SchedulePatch,
    request: Request,
    db: Database = Depends(get_db),  # noqa: B008
) -> Schedule:
    updates = patch.model_dump(exclude_unset=True)
    with db.session() as s:
        sch = s.get(Schedule, schedule_id)
        if sch is None:
            raise HTTPException(status_code=404, detail="schedule not found")
        for k, v in updates.items():
            setattr(sch, k, v)
        if "ends_at" in updates or "starts_at" in updates:
            ends = sch.ends_at.replace(tzinfo=None) if sch.ends_at.tzinfo else sch.ends_at
            starts = sch.starts_at.replace(tzinfo=None) if sch.starts_at.tzinfo else sch.starts_at
            if ends <= starts:
                raise HTTPException(status_code=400, detail="ends_at must be after starts_at")
        s.flush()
        s.refresh(sch)
        mgr = _get_manager(request)
        if sch.status == "cancelled":
            mgr.remove(schedule_id)
        elif "starts_at" in updates and mgr.has_job(schedule_id):
            mgr.update(sch)
        s.expunge(sch)
    return sch


@router.delete("/schedules/{schedule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_schedule(
    schedule_id: int,
    request: Request,
    db: Database = Depends(get_db),  # noqa: B008
) -> Response:
    with db.session() as s:
        row = s.get(Schedule, schedule_id)
        if row is None:
            raise HTTPException(status_code=404, detail="schedule not found")
        s.delete(row)
    _get_manager(request).remove(schedule_id)
    return Response(status_code=204)
