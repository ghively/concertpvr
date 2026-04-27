"""Streams CRUD."""

from __future__ import annotations

import datetime as _dt
import re
from pathlib import Path as _Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

# Smart-paste URL classification — detected before the single-video probe so
# channel and playlist URLs short-circuit to their proper handlers (avoids
# yt-dlp trying to enumerate every video on a channel like @nprmusic).
_CHANNEL_URL_RE = re.compile(
    r"youtube\.com/(?:@[^/?#]+|channel/[A-Za-z0-9_-]+|c/[^/?#]+|user/[^/?#]+)(?:/[^?#]*)?/?$"
)
_PLAYLIST_URL_RE = re.compile(r"[?&]list=(?P<playlist_id>[A-Za-z0-9_-]+)")

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


@router.post("/streams", status_code=status.HTTP_201_CREATED, response_model=None)
async def create_stream(
    payload: StreamCreate,
    request: Request,
    db: Database = Depends(get_db),  # noqa: B008
) -> Stream | dict[str, object]:
    """Smart-paste entry point: probes a YouTube URL and routes by type.

    - Single video URL → creates `Stream` (kind=live or kind=video) and queues
      a VOD download for non-live videos. Returns the Stream JSON (201).
    - Channel URL → returns `{type:"channel", channel_name, channel_id, url}`
      payload (200). Frontend's smart-paste modal then offers the subscribe flow.
    - Playlist URL → returns `{type:"playlist", playlist_id, playlist_title,
      count, items}` payload (200). Frontend's modal offers the bulk-add flow.
    """
    cookies = _resolve_cookies_path(db)

    # Channel URL — short-circuit, don't run the single-video probe.
    if _CHANNEL_URL_RE.search(payload.url) and "watch?v=" not in payload.url:
        from concertpvr.ytdlp_channels import ChannelProbeError, probe_channel

        try:
            ch = await probe_channel(payload.url)
        except ChannelProbeError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        return {
            "type": "channel",
            "channel_name": ch.channel_name,
            "avatar_url": ch.avatar_url,
            "url": ch.canonical_url,
        }

    # Playlist URL — short-circuit too.
    if _PLAYLIST_URL_RE.search(payload.url) and "watch?v=" not in payload.url:
        from concertpvr.playlist_ingest import expand_playlist
        from concertpvr.ytdlp import ProbeError as _ProbeError

        try:
            playlist_info = await expand_playlist(payload.url, cookies_path=cookies)
        except _ProbeError as ex:
            raise HTTPException(status_code=400, detail=str(ex)) from ex
        playlist_youtube_ids = [entry.youtube_id for entry in playlist_info.entries]
        with db.session() as s:
            existing_rows = list(
                s.scalars(select(Stream).where(Stream.youtube_id.in_(playlist_youtube_ids)))
            )
            existing_ids: set[str] = {row.youtube_id for row in existing_rows}
        return {
            "type": "playlist",
            "playlist_id": playlist_info.playlist_id,
            "playlist_title": playlist_info.playlist_title,
            "count": playlist_info.count,
            "items": [
                {
                    "youtube_id": entry.youtube_id,
                    "title": entry.title,
                    "channel_name": entry.channel_name,
                    "thumbnail_url": entry.thumbnail_url,
                    "duration_s": entry.duration_s,
                    "upload_date": (
                        entry.upload_date.isoformat()  # type: ignore[attr-defined]
                        if entry.upload_date is not None
                        else None
                    ),
                    "is_already_known": entry.youtube_id in existing_ids,
                }
                for entry in playlist_info.entries
            ],
        }

    # Single video — existing flow.
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
