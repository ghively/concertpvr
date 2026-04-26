"""Streams CRUD."""

from __future__ import annotations

import datetime as _dt

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from concertpvr.buffer import BufferManager
from concertpvr.db import Database
from concertpvr.deps import get_broadcaster, get_buffer, get_db, get_pool
from concertpvr.models import Recording, Settings as SettingsModel, Stream, WatchSubscription
from concertpvr.pool import RecorderPool
from concertpvr.process import AsyncSubprocessRunner
from concertpvr.recorder import RecorderProgress, RecorderWorker
from concertpvr.schemas import StreamCreate, StreamRead, WatchSubscriptionPatch, WatchSubscriptionRead
from concertpvr.ws import Broadcaster
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
        await _start_recording(stream_id, url, quality, db, pool, buf, bc)
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
    output_dir = buf.stream_dir(stream_id)
    runner = AsyncSubprocessRunner()

    async def on_progress(p: RecorderProgress) -> None:
        await bc.publish(
            f"streams.{stream_id}.progress",
            {
                "bytes_total": p.bytes_total,
                "bitrate_bps": p.bitrate_bps,
                "duration_s": p.duration_s,
                "fragment_count": p.fragment_count,
            },
        )

    worker = RecorderWorker(
        stream_id=stream_id,
        url=url,
        output_dir=output_dir,
        quality_format=quality,
        runner=runner,
        on_progress=on_progress,
    )

    with db.session() as s:
        rec = Recording(
            stream_id=stream_id,
            started_at=_dt.datetime.now(_dt.timezone.utc),
            path=str(output_dir),
            status="recording",
            is_buffer=True,
        )
        s.add(rec)

    await pool.start(worker)
