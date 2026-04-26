"""Channel watchers CRUD."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from concertpvr.db import Database
from concertpvr.deps import get_db
from concertpvr.models import ChannelWatcher
from concertpvr.schemas import (
    ChannelWatcherCreate,
    ChannelWatcherPatch,
    ChannelWatcherRead,
)
from concertpvr.ytdlp_channels import ChannelProbeError, probe_channel

router = APIRouter()


@router.post(
    "/channel-watchers",
    response_model=ChannelWatcherRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_watcher(
    payload: ChannelWatcherCreate,
    db: Database = Depends(get_db),  # noqa: B008
) -> ChannelWatcher:
    try:
        info = await probe_channel(payload.channel_url)
    except ChannelProbeError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    with db.session() as s:
        existing = s.scalar(
            select(ChannelWatcher).where(ChannelWatcher.channel_url == info.canonical_url)
        )
        if existing is not None:
            raise HTTPException(status_code=409, detail="watcher already exists")
        w = ChannelWatcher(
            channel_url=info.canonical_url,
            channel_name=info.channel_name,
            avatar_url=info.avatar_url,
            title_filter=payload.title_filter,
            quality_cap=payload.quality_cap,
            retention_days=payload.retention_days,
        )
        s.add(w)
        try:
            s.flush()
        except IntegrityError as e:
            raise HTTPException(status_code=409, detail="watcher already exists") from e
        s.refresh(w)
        s.expunge(w)
    return w


@router.get("/channel-watchers", response_model=list[ChannelWatcherRead])
def list_watchers(db: Database = Depends(get_db)) -> list[ChannelWatcher]:  # noqa: B008
    with db.session() as s:
        rows = list(s.scalars(select(ChannelWatcher).order_by(ChannelWatcher.added_at.desc())))
        for r in rows:
            s.expunge(r)
    return rows


@router.get("/channel-watchers/{watcher_id}", response_model=ChannelWatcherRead)
def get_watcher(watcher_id: int, db: Database = Depends(get_db)) -> ChannelWatcher:  # noqa: B008
    with db.session() as s:
        row = s.get(ChannelWatcher, watcher_id)
        if row is None:
            raise HTTPException(status_code=404, detail="watcher not found")
        s.expunge(row)
    return row


@router.patch("/channel-watchers/{watcher_id}", response_model=ChannelWatcherRead)
def patch_watcher(
    watcher_id: int,
    patch: ChannelWatcherPatch,
    db: Database = Depends(get_db),  # noqa: B008
) -> ChannelWatcher:
    updates = patch.model_dump(exclude_unset=True)
    with db.session() as s:
        w = s.get(ChannelWatcher, watcher_id)
        if w is None:
            raise HTTPException(status_code=404, detail="watcher not found")
        for k, v in updates.items():
            setattr(w, k, v)
        s.flush()
        s.refresh(w)
        s.expunge(w)
    return w


@router.delete("/channel-watchers/{watcher_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_watcher(watcher_id: int, db: Database = Depends(get_db)) -> Response:  # noqa: B008
    with db.session() as s:
        w = s.get(ChannelWatcher, watcher_id)
        if w is None:
            raise HTTPException(status_code=404, detail="watcher not found")
        s.delete(w)
    return Response(status_code=204)
