"""Channel watchers CRUD."""

from __future__ import annotations

import datetime as _dt
import logging
from pathlib import Path as _Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from concertpvr.db import Database
from concertpvr.deps import get_db
from concertpvr.models import ChannelWatcher, Recording, Stream
from concertpvr.recording_starter import _resolve_cookies_path
from concertpvr.schemas import (
    BacklogDownloadRequest,
    BacklogItem,
    ChannelWatcherCreate,
    ChannelWatcherPatch,
    ChannelWatcherRead,
)
from concertpvr.ytdlp import ProbeError, probe
from concertpvr.ytdlp_channels import ChannelProbeError, list_recent_uploads, probe_channel

logger = logging.getLogger(__name__)

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


@router.get(
    "/channel-watchers/{watcher_id}/backlog",
    response_model=list[BacklogItem],
)
async def get_watcher_backlog(
    watcher_id: int,
    limit: int = Query(50, ge=1, le=200),  # noqa: B008
    offset: int = Query(0, ge=0),  # noqa: B008
    sort: Literal["newest", "most_viewed", "longest", "oldest"] = Query("newest"),  # noqa: B008
    db: Database = Depends(get_db),  # noqa: B008
) -> list[BacklogItem]:
    with db.session() as s:
        watcher = s.get(ChannelWatcher, watcher_id)
        if watcher is None:
            raise HTTPException(status_code=404, detail="watcher not found")
        channel_url = watcher.channel_url

    cookies_path = _resolve_cookies_path(db)

    raw_items = await list_recent_uploads(
        channel_url, cookies_path=cookies_path, limit=offset + limit
    )

    # Sort before slicing
    if sort == "oldest":
        raw_items = sorted(
            raw_items,
            key=lambda b: b.upload_date or _dt.date.min,
        )
    elif sort == "longest":
        raw_items = sorted(
            raw_items,
            key=lambda b: b.duration_s if b.duration_s is not None else -1,
            reverse=True,
        )
    # "newest" is the default yt-dlp upload order (already sorted newest-first)
    # "most_viewed" — yt-dlp flat-extract doesn't return view counts cheaply;
    # returning default order as a no-op

    page = raw_items[offset : offset + limit]

    # Build a set of known youtube_ids for state classification
    youtube_ids = [b.youtube_id for b in page]
    with db.session() as s:
        stream_rows = list(s.scalars(select(Stream).where(Stream.youtube_id.in_(youtube_ids))))
        known_stream_ids = {row.youtube_id: row.id for row in stream_rows}

        # Find recordings that are in queued/downloading state for these streams
        queued_stream_ids: set[int] = set()
        if known_stream_ids:
            rec_rows = list(
                s.scalars(
                    select(Recording).where(
                        Recording.stream_id.in_(known_stream_ids.values()),
                        Recording.status.in_(["vod_queued", "vod_downloading"]),
                    )
                )
            )
            queued_stream_ids = {r.stream_id for r in rec_rows}

    result: list[BacklogItem] = []
    for b in page:
        if b.youtube_id not in known_stream_ids:
            state: Literal["downloaded", "queued", "not_downloaded"] = "not_downloaded"
        elif known_stream_ids[b.youtube_id] in queued_stream_ids:
            state = "queued"
        else:
            state = "downloaded"

        result.append(
            BacklogItem(
                youtube_id=b.youtube_id,
                title=b.title,
                url=b.url,
                thumbnail_url=b.thumbnail_url,
                upload_date=b.upload_date,
                duration_s=b.duration_s,
                view_count=None,  # flat-extract doesn't return view counts cheaply
                state=state,
            )
        )
    return result


@router.post(
    "/channel-watchers/{watcher_id}/backlog/download",
    status_code=status.HTTP_201_CREATED,
)
async def download_backlog_items(
    watcher_id: int,
    body: BacklogDownloadRequest,
    request: Request,
    db: Database = Depends(get_db),  # noqa: B008
) -> dict[str, list[int]]:
    with db.session() as s:
        watcher = s.get(ChannelWatcher, watcher_id)
        if watcher is None:
            raise HTTPException(status_code=404, detail="watcher not found")
        watcher_id_val = watcher.id

    cookies_path = _resolve_cookies_path(db)
    staging_dir = request.app.state.config.staging_dir

    new_rec_ids: list[int] = []

    for yid in body.video_ids:
        # Skip already-existing youtube_ids
        with db.session() as s:
            existing = s.scalar(select(Stream).where(Stream.youtube_id == yid))
            if existing is not None:
                continue

        url = f"https://www.youtube.com/watch?v={yid}"
        try:
            info = await probe(url, cookies_path=cookies_path)
        except ProbeError as e:
            logger.warning("backlog download: probe failed for %s: %s", yid, e)
            continue

        with db.session() as s:
            # Double-check in case of concurrent requests
            existing2 = s.scalar(select(Stream).where(Stream.youtube_id == info.youtube_id))
            if existing2 is not None:
                continue

            stream = Stream(
                kind="video",
                youtube_id=info.youtube_id,
                url=info.url,
                title=info.title,
                channel_name=info.channel_name,
                thumbnail_url=info.thumbnail_url,
                watcher_id=watcher_id_val,
                original_upload_date=info.original_upload_date,
                description=info.description,
                youtube_tags=info.tags,
            )
            s.add(stream)
            s.flush()

            output_path = _Path(staging_dir) / f"vod-{info.youtube_id}.mkv"
            rec = Recording(
                stream_id=stream.id,
                started_at=_dt.datetime.now(_dt.UTC),
                path=str(output_path),
                status="vod_queued",
                is_buffer=False,
                # Backlog-browser-curated downloads do NOT auto-publish,
                # even if watcher.auto_publish is True.
                auto_publish_after_download=False,
            )
            s.add(rec)
            s.flush()
            new_rec_ids.append(rec.id)

    # Enqueue AFTER all DB sessions are closed so rows are committed
    for rid in new_rec_ids:
        await request.app.state.vod_queue.enqueue(rid)

    return {"queued_recording_ids": new_rec_ids}
