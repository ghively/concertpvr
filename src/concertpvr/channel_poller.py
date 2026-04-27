"""Periodic channel poller — APScheduler job target."""

from __future__ import annotations

import datetime as _dt
import logging
import re
from pathlib import Path

from sqlalchemy import select

from concertpvr.artist_extractor import extract_artist
from concertpvr.buffer import BufferManager
from concertpvr.db import Database
from concertpvr.models import ChannelWatcher, Recording, Stream
from concertpvr.pool import RecorderPool
from concertpvr.recording_starter import _resolve_cookies_path, start_buffer_recording
from concertpvr.setlist_detector import (
    detect_in_chapters,
    detect_in_comments,
    detect_in_description,
)
from concertpvr.vod_queue import VodQueue
from concertpvr.ws import Broadcaster
from concertpvr.ytdlp import probe
from concertpvr.ytdlp_channels import (
    BroadcastInfo,
    fetch_channel_live_broadcasts,
    list_recent_uploads,
)

logger = logging.getLogger(__name__)


def _matches_filter(title: str, pattern: str | None) -> bool:
    if pattern is None or pattern.strip() == "":
        return True
    try:
        return re.search(pattern, title, re.IGNORECASE) is not None
    except re.error:
        return pattern.lower() in title.lower()


def _ensure_stream(db: Database, broadcast: BroadcastInfo) -> int:
    with db.session() as s:
        existing = s.scalar(select(Stream).where(Stream.youtube_id == broadcast.youtube_id))
        if existing is not None:
            return existing.id
        stream = Stream(
            kind="live",
            youtube_id=broadcast.youtube_id,
            url=broadcast.url,
            title=broadcast.title,
            channel_name=broadcast.channel_name,
        )
        s.add(stream)
        s.flush()
        return stream.id


async def _check_for_new_vod_uploads(
    watcher: ChannelWatcher,
    *,
    db: Database,
    vod_queue: VodQueue,
    cookies_path: Path | None,
    staging_root: Path,
) -> None:
    """Check for new VOD uploads for *watcher* and enqueue downloads."""
    try:
        uploads = await list_recent_uploads(
            watcher.channel_url,
            cookies_path=cookies_path,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("watcher %s: list_recent_uploads failed: %s", watcher.id, e)
        return

    # Pre-fetch known youtube_ids for this channel's streams to skip duplicates
    with db.session() as s:
        known_ids: set[str] = set(s.scalars(select(Stream.youtube_id)))

    new_rec_ids: list[int] = []

    for upload in uploads:
        # Filter: skip live entries
        if upload.is_live:
            continue

        # Filter: skip already-known youtube_ids
        if upload.youtube_id in known_ids:
            continue

        # Filter: forward-only — skip uploads older than watcher.created_at / added_at
        watcher_created: _dt.datetime | None = getattr(watcher, "added_at", None)
        if watcher_created is not None and upload.upload_date is not None:
            # Compare date portion only
            watcher_date = watcher_created.date() if hasattr(watcher_created, "date") else None
            if watcher_date is not None and upload.upload_date < watcher_date:
                logger.debug(
                    "watcher %s: skipping upload %s (upload_date %s < watcher created %s)",
                    watcher.id,
                    upload.youtube_id,
                    upload.upload_date,
                    watcher_date,
                )
                continue

        # Filter: apply vod_title_filter regex if set
        if not _matches_filter(upload.title, watcher.vod_title_filter):
            logger.debug(
                "watcher %s: upload %s title %r did not match vod_title_filter %r",
                watcher.id,
                upload.youtube_id,
                upload.title,
                watcher.vod_title_filter,
            )
            continue

        # Full probe
        try:
            info = await probe(
                upload.url,
                cookies_path=cookies_path,
                fetch_comments=watcher.extract_setlist_from_comments,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("watcher %s: probe failed for %s: %s", watcher.id, upload.youtube_id, e)
            continue

        # Skip live entries from full probe
        if info.is_live:
            continue

        # Detect setlist — priority: chapters → description → comments
        detected_setlist = (
            detect_in_chapters(info.chapters)
            or detect_in_description(info.description)
            or detect_in_comments(info.comments)
        )

        # Determine auto_publish flag
        auto_pub = bool(
            watcher.auto_publish
            and extract_artist(info.title, watcher.vod_artist_regex) is not None
        )

        # Create Stream + Recording within a single session
        with db.session() as s:
            # Re-check in case another poll created it concurrently
            existing_stream = s.scalar(select(Stream).where(Stream.youtube_id == info.youtube_id))
            if existing_stream is not None:
                logger.debug(
                    "watcher %s: stream %s created concurrently; skipping",
                    watcher.id,
                    info.youtube_id,
                )
                continue

            stream = Stream(
                kind="video",
                youtube_id=info.youtube_id,
                url=info.url,
                title=info.title,
                channel_name=info.channel_name,
                thumbnail_url=info.thumbnail_url,
                watcher_id=watcher.id,
                original_upload_date=info.original_upload_date,
                description=info.description,
                youtube_tags=info.tags,
                detected_setlist_text=detected_setlist.raw_text if detected_setlist else None,
                detected_setlist_source=detected_setlist.source if detected_setlist else None,
            )
            s.add(stream)
            s.flush()

            # Build output path under staging root
            output_path = staging_root / f"vod-{info.youtube_id}.%(ext)s"

            rec = Recording(
                stream_id=stream.id,
                started_at=_dt.datetime.now(_dt.UTC),
                path=str(output_path),
                status="vod_queued",
                auto_publish_after_download=auto_pub,
            )
            s.add(rec)
            s.flush()
            rec_id = rec.id

        new_rec_ids.append(rec_id)
        # Mark as known so subsequent uploads in same poll cycle don't duplicate
        known_ids.add(info.youtube_id)
        logger.info(
            "watcher %s: queued VOD %s (auto_publish=%s)", watcher.id, info.youtube_id, auto_pub
        )

    # Enqueue AFTER the DB sessions are closed so rows are committed
    for rec_id in new_rec_ids:
        await vod_queue.enqueue(rec_id)


async def poll_all_channel_watchers(
    *,
    db: Database,
    pool: RecorderPool,
    buf: BufferManager,
    bc: Broadcaster,
    default_quality: str,
    vod_queue: VodQueue | None = None,
    staging_root: Path | None = None,
) -> None:
    with db.session() as s:
        enabled = list(s.scalars(select(ChannelWatcher).where(ChannelWatcher.enabled == True)))  # noqa: E712
        watcher_data = [
            (
                w.id,
                w.channel_url,
                w.title_filter,
                w.quality_cap,
                w.last_live_id,
                w.watch_live,
                w.watch_vod_uploads,
                w.added_at,
                w.vod_title_filter,
                w.vod_artist_regex,
                w.auto_publish,
                w.extract_setlist_from_comments,
            )
            for w in enabled
        ]

    cookies_path = _resolve_cookies_path(db)

    for (
        w_id,
        channel_url,
        title_filter,
        quality_cap,
        last_live_id,
        watch_live,
        watch_vod_uploads,
        _added_at,
        _vod_title_filter,
        _vod_artist_regex,
        _auto_publish,
        _extract_setlist_from_comments,
    ) in watcher_data:
        # --- Live broadcast path (sacred, unchanged) ---
        if watch_live:
            try:
                broadcasts = await fetch_channel_live_broadcasts(channel_url)
            except Exception as e:  # noqa: BLE001
                logger.warning("watcher %s: fetch failed: %s", w_id, e)
                broadcasts = []

            triggered_id: str | None = None
            for b in broadcasts:
                if b.youtube_id == last_live_id:
                    continue
                if not _matches_filter(b.title, title_filter):
                    continue
                try:
                    stream_id = _ensure_stream(db, b)
                    quality = quality_cap or default_quality
                    await start_buffer_recording(
                        stream_id=stream_id,
                        url=b.url,
                        quality_format=quality,
                        db=db,
                        pool=pool,
                        buf=buf,
                        bc=bc,
                    )
                    triggered_id = b.youtube_id
                    break
                except Exception as e:  # noqa: BLE001
                    if "capacity" in str(e).lower():
                        logger.info("watcher %s: pool full; skipping %s", w_id, b.youtube_id)
                    else:
                        logger.warning(
                            "watcher %s: failed to start recording for %s: %s",
                            w_id,
                            b.youtube_id,
                            e,
                        )

            with db.session() as s:
                w = s.get(ChannelWatcher, w_id)
                if w is not None:
                    w.last_polled = _dt.datetime.now(_dt.UTC)
                    if triggered_id is not None:
                        w.last_live_id = triggered_id

        # --- VOD uploads path ---
        if watch_vod_uploads and vod_queue is not None:
            # Reconstruct a lightweight watcher-like object for _check_for_new_vod_uploads
            with db.session() as s:
                watcher_row = s.get(ChannelWatcher, w_id)
                if watcher_row is None:
                    continue
                s.expunge(watcher_row)

            _staging = staging_root or Path("/tmp/concertpvr/staging")  # noqa: S108
            await _check_for_new_vod_uploads(
                watcher_row,
                db=db,
                vod_queue=vod_queue,
                cookies_path=cookies_path,
                staging_root=_staging,
            )

        # Update last_polled when only VOD mode is enabled (live path already updated it)
        if not watch_live and watch_vod_uploads:
            with db.session() as s:
                w = s.get(ChannelWatcher, w_id)
                if w is not None:
                    w.last_polled = _dt.datetime.now(_dt.UTC)
