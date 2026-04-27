"""Streams CRUD."""

from __future__ import annotations

import datetime as _dt
from pathlib import Path as _Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from concertpvr.buffer import BufferManager
from concertpvr.db import Database
from concertpvr.deps import get_broadcaster, get_buffer, get_db, get_pool
from concertpvr.models import Recording, Stream, WatchSubscription
from concertpvr.models import Settings as SettingsModel
from concertpvr.pool import RecorderPool
from concertpvr.recording_starter import _resolve_cookies_path
from concertpvr.schemas import (
    StreamCreate,
    StreamRead,
    WatchSubscriptionPatch,
    WatchSubscriptionRead,
)
from concertpvr.ws import Broadcaster
from concertpvr.ytdlp import ProbeError, probe

router = APIRouter()


@router.post("/streams", response_model=StreamRead, status_code=status.HTTP_201_CREATED)
async def create_stream(
    payload: StreamCreate,
    request: Request,
    db: Database = Depends(get_db),  # noqa: B008
) -> Stream:
    cookies = _resolve_cookies_path(db)

    try:
        info = await probe(payload.url, cookies_path=cookies)
    except ProbeError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    kind = "live" if info.is_live else "video"

    # For VODs, run setlist detection on description/chapters
    detected_text: str | None = None
    detected_source: str | None = None
    if not info.is_live:
        from concertpvr.setlist_detector import detect_in_chapters, detect_in_description

        chap = detect_in_chapters(info.chapters)
        if chap is not None:
            detected_text = ""
            detected_source = "chapters"
        else:
            desc = detect_in_description(info.description)
            if desc is not None:
                detected_text = desc.raw_text
                detected_source = "description"

    rec_id: int | None = None

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
            original_upload_date=info.original_upload_date if not info.is_live else None,
            description=info.description if not info.is_live else None,
            youtube_tags=info.tags if not info.is_live else None,
            detected_setlist_text=detected_text,
            detected_setlist_source=detected_source,
        )
        s.add(row)
        try:
            s.flush()
        except IntegrityError as e:
            raise HTTPException(status_code=409, detail="stream already added") from e

        sid = row.id

        # For VODs, also create the Recording row
        if kind == "video":
            staging_dir = _Path(request.app.state.config.staging_dir)
            output_path = staging_dir / f"vod-{info.youtube_id}.mkv"
            rec = Recording(
                stream_id=sid,
                started_at=_dt.datetime.now(_dt.UTC),
                path=str(output_path),
                status="vod_queued",
                is_buffer=False,
            )
            s.add(rec)
            s.flush()
            rec_id = rec.id

        s.refresh(row)
        s.expunge(row)

    # Enqueue AFTER the DB session closes so the row is committed first
    if kind == "video" and rec_id is not None:
        await request.app.state.vod_queue.enqueue(rec_id)

    return row


@router.get("/streams", response_model=list[StreamRead])
def list_streams(
    limit: int | None = Query(None, ge=1, le=10000),  # noqa: B008
    offset: int = Query(0, ge=0),  # noqa: B008
    db: Database = Depends(get_db),  # noqa: B008
) -> list[Stream]:
    with db.session() as s:
        stmt = select(Stream).order_by(Stream.added_at.desc())
        if limit is not None:
            stmt = stmt.limit(limit).offset(offset)
        elif offset > 0:
            stmt = stmt.offset(offset)
        rows = list(s.scalars(stmt))
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
        sub = s.scalar(select(WatchSubscription).where(WatchSubscription.stream_id == stream_id))
        if sub is None:
            raise HTTPException(status_code=404, detail="no subscription")
        s.expunge(sub)
    return sub


@router.patch("/streams/{stream_id}/watch", response_model=WatchSubscriptionRead)
async def patch_watch(
    stream_id: int,
    patch: WatchSubscriptionPatch,
    db: Database = Depends(get_db),  # noqa: B008
    pool: RecorderPool = Depends(get_pool),  # noqa: B008
    buf: BufferManager = Depends(get_buffer),  # noqa: B008
    bc: Broadcaster = Depends(get_broadcaster),  # noqa: B008
) -> WatchSubscription:
    updates = patch.model_dump(exclude_unset=True)
    with db.session() as s:
        stream = s.get(Stream, stream_id)
        if stream is None:
            raise HTTPException(status_code=404, detail="stream not found")

        sub = s.scalar(select(WatchSubscription).where(WatchSubscription.stream_id == stream_id))
        if sub is None:
            sub = WatchSubscription(stream_id=stream_id)
            s.add(sub)
        for k, v in updates.items():
            setattr(sub, k, v)
        s.flush()
        s.refresh(sub)

        enabled = sub.enabled
        quality = sub.quality_cap
        url = stream.url
        s.expunge(sub)
        s.expunge(stream)

    if quality is None:
        with db.session() as s:
            settings_row = s.get(SettingsModel, 1)
            quality = settings_row.default_quality if settings_row else "bestvideo*+bestaudio/best"

    if enabled and not pool.is_recording(stream_id):
        try:
            await _start_recording(stream_id, url, quality, db, pool, buf, bc)
        except RuntimeError as e:
            if "capacity" in str(e).lower():
                raise HTTPException(
                    status_code=507,
                    detail="Max concurrent recordings reached. Stop one before starting another.",
                ) from e
            raise
    elif not enabled and pool.is_recording(stream_id):
        await pool.stop(stream_id)

    return sub


async def _start_recording(
    stream_id: int,
    url: str,
    quality: str,
    db: Database,
    pool: RecorderPool,
    buf: BufferManager,
    bc: Broadcaster,
) -> None:
    from concertpvr.recording_starter import start_buffer_recording

    await start_buffer_recording(
        stream_id=stream_id,
        url=url,
        quality_format=quality,
        db=db,
        pool=pool,
        buf=buf,
        bc=bc,
    )
