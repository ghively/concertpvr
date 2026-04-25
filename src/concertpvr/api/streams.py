"""Streams CRUD."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from concertpvr.db import Database
from concertpvr.deps import get_db
from concertpvr.models import Stream, WatchSubscription
from concertpvr.schemas import StreamCreate, StreamRead, WatchSubscriptionPatch, WatchSubscriptionRead
from concertpvr.ytdlp import ProbeError, probe

router = APIRouter()


@router.post("/streams", response_model=StreamRead, status_code=status.HTTP_201_CREATED)
async def create_stream(
    payload: StreamCreate,
    db: Database = Depends(get_db),  # noqa: B008
) -> Stream:
    try:
        info = await probe(payload.url)
    except ProbeError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    kind = "live" if info.is_live else "video"

    with db.session() as s:
        existing = s.scalar(select(Stream).where(Stream.youtube_id == info.youtube_id))
        if existing is not None:
            raise HTTPException(status_code=409, detail="stream already added")

        row = Stream(
            kind=kind,
            youtube_id=info.youtube_id,
            url=info.url,
            title=info.title,
            channel_name=info.channel_name,
            thumbnail_url=info.thumbnail_url,
        )
        s.add(row)
        try:
            s.flush()
        except IntegrityError as e:
            raise HTTPException(status_code=409, detail="stream already added") from e
        s.refresh(row)
        s.expunge(row)
    return row


@router.get("/streams", response_model=list[StreamRead])
def list_streams(db: Database = Depends(get_db)) -> list[Stream]:  # noqa: B008
    with db.session() as s:
        rows = list(s.scalars(select(Stream).order_by(Stream.added_at.desc())))
        for r in rows:
            s.expunge(r)
    return rows


@router.get("/streams/{stream_id}", response_model=StreamRead)
def get_stream(stream_id: int, db: Database = Depends(get_db)) -> Stream:  # noqa: B008
    with db.session() as s:
        row = s.get(Stream, stream_id)
        if row is None:
            raise HTTPException(status_code=404, detail="stream not found")
        s.expunge(row)
    return row


@router.delete("/streams/{stream_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_stream(stream_id: int, db: Database = Depends(get_db)) -> Response:  # noqa: B008
    with db.session() as s:
        row = s.get(Stream, stream_id)
        if row is None:
            raise HTTPException(status_code=404, detail="stream not found")
        s.delete(row)
    return Response(status_code=204)


@router.get("/streams/{stream_id}/watch", response_model=WatchSubscriptionRead)
def get_watch(stream_id: int, db: Database = Depends(get_db)) -> WatchSubscription:  # noqa: B008
    with db.session() as s:
        if s.get(Stream, stream_id) is None:
            raise HTTPException(status_code=404, detail="stream not found")
        sub = s.scalar(
            select(WatchSubscription).where(WatchSubscription.stream_id == stream_id)
        )
        if sub is None:
            raise HTTPException(status_code=404, detail="no subscription")
        s.expunge(sub)
    return sub


@router.patch("/streams/{stream_id}/watch", response_model=WatchSubscriptionRead)
def patch_watch(
    stream_id: int,
    patch: WatchSubscriptionPatch,
    db: Database = Depends(get_db),  # noqa: B008
) -> WatchSubscription:
    updates = patch.model_dump(exclude_unset=True)
    with db.session() as s:
        if s.get(Stream, stream_id) is None:
            raise HTTPException(status_code=404, detail="stream not found")
        sub = s.scalar(
            select(WatchSubscription).where(WatchSubscription.stream_id == stream_id)
        )
        if sub is None:
            sub = WatchSubscription(stream_id=stream_id)
            s.add(sub)
        for k, v in updates.items():
            setattr(sub, k, v)
        s.flush()
        s.refresh(sub)
        s.expunge(sub)
    return sub
