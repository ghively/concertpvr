"""Channel watchers CRUD."""

from __future__ import annotations

import datetime as _dt
import logging
from pathlib import Path as _Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from concertpvr.backlog_cache import fetch_full_channel, is_stale
from concertpvr.db import Database
from concertpvr.deps import get_db
from concertpvr.models import ChannelBacklogCache, ChannelWatcher, Recording, Stream
from concertpvr.recording_starter import _resolve_cookies_path
from concertpvr.schemas import (
    BacklogCancelRequest,
    BacklogDownloadRequest,
    BacklogItem,
    ChannelWatcherCreate,
    ChannelWatcherPatch,
    ChannelWatcherRead,
)
from concertpvr.ytdlp import ProbeError, probe
from concertpvr.ytdlp_channels import ChannelProbeError, probe_channel

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
        kwargs: dict[str, object] = {
            "channel_url": info.canonical_url,
            "channel_name": info.channel_name,
            "avatar_url": info.avatar_url,
            "title_filter": payload.title_filter,
            "quality_cap": payload.quality_cap,
            "retention_days": payload.retention_days,
        }
        # Apply v0.3 toggles only when caller explicitly set them
        # (None = inherit the column's default).
        if payload.watch_live is not None:
            kwargs["watch_live"] = payload.watch_live
        if payload.watch_vod_uploads is not None:
            kwargs["watch_vod_uploads"] = payload.watch_vod_uploads
        if payload.auto_publish is not None:
            kwargs["auto_publish"] = payload.auto_publish
        w = ChannelWatcher(**kwargs)
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


@router.get("/channel-watchers/{watcher_id}/backlog/status")
def get_watcher_backlog_status(
    watcher_id: int,
    db: Database = Depends(get_db),  # noqa: B008
) -> dict[str, object]:
    """Cache state — frontend polls this while a refresh is in flight."""
    with db.session() as s:
        watcher = s.get(ChannelWatcher, watcher_id)
        if watcher is None:
            raise HTTPException(status_code=404, detail="watcher not found")
        cache = s.get(ChannelBacklogCache, watcher_id)
        if cache is None:
            return {
                "status": "never_fetched",
                "fetched_at": None,
                "total_count": 0,
                "progress_pct": 0,
                "error": None,
                "stale": True,
            }
        return {
            "status": cache.status,
            "fetched_at": cache.fetched_at.isoformat() if cache.fetched_at else None,
            "total_count": cache.total_count,
            "progress_pct": cache.progress_pct,
            "error": cache.error,
            "stale": is_stale(cache),
        }


@router.post(
    "/channel-watchers/{watcher_id}/backlog/refresh",
    status_code=status.HTTP_202_ACCEPTED,
)
async def refresh_watcher_backlog(
    watcher_id: int,
    request: Request,
    probe_views: bool = Query(False),
    db: Database = Depends(get_db),  # noqa: B008
) -> dict[str, object]:
    """Trigger an async full-channel cache refresh.

    Returns 202 immediately; cache populates in the background. Poll
    /backlog/status for progress. The client should re-GET /backlog
    once status flips to 'complete'.
    """
    import asyncio as _asyncio

    with db.session() as s:
        watcher = s.get(ChannelWatcher, watcher_id)
        if watcher is None:
            raise HTTPException(status_code=404, detail="watcher not found")
        cache = s.get(ChannelBacklogCache, watcher_id)
        if cache is not None and cache.status == "fetching":
            # Already in flight — don't queue another fetch.
            return {"status": "fetching", "started": False}

    # Fire-and-forget background fetch. Errors are caught + persisted to the
    # cache row by fetch_full_channel itself.
    async def _bg() -> None:
        try:
            if probe_views:
                from concertpvr.backlog_cache import fetch_full_channel_with_views

                await fetch_full_channel_with_views(db, watcher_id)
            else:
                await fetch_full_channel(db, watcher_id)
        except Exception:  # noqa: BLE001
            logger.exception("background fetch_full_channel failed for %d", watcher_id)

    _asyncio.create_task(_bg())
    return {"status": "fetching", "started": True}


@router.get(
    "/channel-watchers/{watcher_id}/backlog",
    response_model=list[BacklogItem],
)
async def get_watcher_backlog(
    watcher_id: int,
    request: Request,
    limit: int = Query(50, ge=1, le=200),  # noqa: B008
    offset: int = Query(0, ge=0),  # noqa: B008
    sort: Literal["newest", "longest", "oldest", "most_viewed"] = Query("newest"),  # noqa: B008
    q: str | None = Query(None),  # noqa: B008
    db: Database = Depends(get_db),  # noqa: B008
) -> list[BacklogItem]:
    """Browse the channel's backlog. Reads from per-watcher cache.

    Sort/filter/paginate runs against the WHOLE channel snapshot (not just
    the most recent N). On first call (or when cache is stale), auto-triggers
    a background refresh and returns whatever cached data exists (possibly
    empty). Frontend should poll /backlog/status to know when to re-GET.

    NEVER triggers downloads. Backlog browse is metadata-only; downloads
    happen exclusively via /backlog/download with explicit user-selected ids.
    """
    import asyncio as _asyncio

    with db.session() as s:
        watcher = s.get(ChannelWatcher, watcher_id)
        if watcher is None:
            raise HTTPException(status_code=404, detail="watcher not found")
        cache = s.get(ChannelBacklogCache, watcher_id)
        items_raw: list[dict[str, object]] = (
            list(cache.items_json) if cache is not None and cache.items_json else []
        )
        cache_status = cache.status if cache is not None else "never_fetched"
        cache_stale = is_stale(cache)

    # Auto-trigger background refresh on first hit / stale cache.
    if cache_stale and cache_status != "fetching":

        async def _bg() -> None:
            try:
                await fetch_full_channel(db, watcher_id)
            except Exception:  # noqa: BLE001
                logger.exception("background fetch_full_channel (auto) failed for %d", watcher_id)

        _asyncio.create_task(_bg())

    # Optional title filter (substring, case-insensitive).
    if q:
        q_lower = q.lower()
        items_raw = [it for it in items_raw if q_lower in str(it.get("title", "")).lower()]

    # Sort across the WHOLE cached list. yt-dlp returns newest-first by default.
    if sort == "oldest":
        items_raw = sorted(items_raw, key=lambda it: str(it.get("upload_date") or ""))
    elif sort == "longest":

        def _dur(it: dict[str, object]) -> int:
            d = it.get("duration_s")
            return int(d) if isinstance(d, (int, float)) else 0

        items_raw = sorted(items_raw, key=_dur, reverse=True)
    elif sort == "most_viewed":

        def _vc(it: dict[str, object]) -> int:
            v = it.get("view_count")
            return int(v) if isinstance(v, (int, float)) else -1

        items_raw = sorted(items_raw, key=_vc, reverse=True)
    # "newest" — preserve existing order (yt-dlp returns newest first).

    page = items_raw[offset : offset + limit]

    # State classification: join against existing Streams + active Recordings.
    youtube_ids = [str(it["youtube_id"]) for it in page]
    known_stream_ids: dict[str, int] = {}
    queued_stream_ids: set[int] = set()
    if youtube_ids:
        with db.session() as s:
            stream_rows = list(s.scalars(select(Stream).where(Stream.youtube_id.in_(youtube_ids))))
            known_stream_ids = {row.youtube_id: row.id for row in stream_rows}
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
    for it in page:
        yid = str(it["youtube_id"])
        if yid not in known_stream_ids:
            state: Literal["downloaded", "queued", "not_downloaded"] = "not_downloaded"
        elif known_stream_ids[yid] in queued_stream_ids:
            state = "queued"
        else:
            state = "downloaded"

        upload_date_str = it.get("upload_date")
        upload_date_val: _dt.date | None = None
        if isinstance(upload_date_str, str) and upload_date_str:
            try:
                upload_date_val = _dt.date.fromisoformat(upload_date_str)
            except ValueError:
                upload_date_val = None

        duration_s_raw = it.get("duration_s")
        duration_s_val: int | None = (
            int(duration_s_raw) if isinstance(duration_s_raw, (int, float)) else None
        )

        view_count_raw = it.get("view_count")
        view_count_val: int | None = (
            int(view_count_raw) if isinstance(view_count_raw, (int, float)) else None
        )

        result.append(
            BacklogItem(
                youtube_id=yid,
                title=str(it.get("title", "")),
                url=str(it.get("url", "")),
                thumbnail_url=(str(it["thumbnail_url"]) if it.get("thumbnail_url") else None),
                upload_date=upload_date_val,
                duration_s=duration_s_val,
                view_count=view_count_val,
                state=state,
            )
        )
    return result


@router.post(
    "/channel-watchers/{watcher_id}/backlog/cancel",
)
async def cancel_backlog_downloads(
    watcher_id: int,
    payload: BacklogCancelRequest,
    request: Request,
    db: Database = Depends(get_db),  # noqa: B008
) -> dict[str, list[str]]:
    """Cancel queued backlog downloads for the given video_ids.

    Only affects recordings in vod_queued state — running downloads must be
    stopped via the recording-level retry/cancel surface (separate concern).
    Returns the list of youtube_ids that were actually cancelled.
    """
    with db.session() as s:
        watcher = s.get(ChannelWatcher, watcher_id)
        if watcher is None:
            raise HTTPException(404, "watcher not found")
        streams = list(s.scalars(select(Stream).where(Stream.youtube_id.in_(payload.video_ids))))
        stream_ids = [st.id for st in streams]
        recs = list(
            s.scalars(
                select(Recording).where(
                    Recording.stream_id.in_(stream_ids),
                    Recording.status == "vod_queued",
                )
            )
        )
        cancelled_youtube_ids = []
        for rec in recs:
            s.delete(rec)
            # also delete the stream if no other recording exists for it
            other = s.scalar(
                select(Recording).where(
                    Recording.stream_id == rec.stream_id,
                    Recording.id != rec.id,
                )
            )
            if other is None:
                st = next((x for x in streams if x.id == rec.stream_id), None)
                if st is not None:
                    cancelled_youtube_ids.append(st.youtube_id)
                    s.delete(st)

    # also drop from the queue if it's there
    for yid in cancelled_youtube_ids:
        await request.app.state.vod_queue.cancel_by_youtube_id(yid)
    return {"cancelled": cancelled_youtube_ids}


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

            # %(ext)s template — yt-dlp picks the actual container; queue
            # handler resolves to the real filename post-download.
            output_path = _Path(staging_dir) / f"vod-{info.youtube_id}.%(ext)s"
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
