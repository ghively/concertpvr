"""Per-watcher full-channel backlog cache.

Stores a one-shot snapshot of the entire channel (via yt-dlp flat-extract)
so the backlog browser can sort/filter/paginate locally over the whole
channel instead of the most-recent 50.
"""

from __future__ import annotations

import datetime as _dt
import logging
from typing import Any

from concertpvr.db import Database
from concertpvr.models import ChannelBacklogCache, ChannelWatcher
from concertpvr.ytdlp_channels import list_all_uploads

logger = logging.getLogger(__name__)

CACHE_TTL_HOURS = 24


async def fetch_full_channel(db: Database, watcher_id: int) -> int:
    """Run a full channel flat-extract, store in cache. Returns row count.

    On error: sets status='error' with error message, raises.
    On success: sets status='complete' with items_json populated.
    """
    with db.session() as s:
        watcher = s.get(ChannelWatcher, watcher_id)
        if watcher is None:
            raise ValueError(f"watcher {watcher_id} not found")
        channel_url = watcher.channel_url

        cache = s.get(ChannelBacklogCache, watcher_id)
        if cache is None:
            cache = ChannelBacklogCache(watcher_id=watcher_id)
            s.add(cache)
        cache.status = "fetching"
        cache.error = None
        cache.progress_pct = 0
        s.flush()

    # Cookies path resolution
    from concertpvr.recording_starter import _resolve_cookies_path

    cookies_path = _resolve_cookies_path(db)

    try:
        items = await list_all_uploads(channel_url, cookies_path=cookies_path)
    except Exception as e:  # noqa: BLE001
        with db.session() as s:
            cache = s.get(ChannelBacklogCache, watcher_id)
            if cache is not None:
                cache.status = "error"
                cache.error = str(e)[:500]
        logger.exception("fetch_full_channel failed for watcher %d", watcher_id)
        raise

    items_payload: list[dict[str, Any]] = [
        {
            "youtube_id": it.youtube_id,
            "title": it.title,
            "url": it.url,
            "thumbnail_url": it.thumbnail_url,
            "duration_s": it.duration_s,
            "upload_date": it.upload_date.isoformat() if it.upload_date else None,
        }
        for it in items
    ]

    with db.session() as s:
        cache = s.get(ChannelBacklogCache, watcher_id)
        if cache is None:
            cache = ChannelBacklogCache(watcher_id=watcher_id)
            s.add(cache)
        cache.status = "complete"
        cache.fetched_at = _dt.datetime.now(_dt.UTC)
        cache.total_count = len(items_payload)
        cache.items_json = items_payload
        cache.error = None
        cache.progress_pct = 100

    return len(items_payload)


def is_stale(cache: ChannelBacklogCache | None) -> bool:
    if cache is None or cache.fetched_at is None or cache.status != "complete":
        return True
    age = _dt.datetime.now(_dt.UTC) - cache.fetched_at.replace(tzinfo=_dt.UTC)
    return age.total_seconds() > CACHE_TTL_HOURS * 3600
