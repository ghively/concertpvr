"""Per-watcher full-channel backlog cache.

Stores a one-shot snapshot of the entire channel (via yt-dlp flat-extract)
so the backlog browser can sort/filter/paginate locally over the whole
channel instead of the most-recent 50.

DESIGN INVARIANT: this module NEVER triggers downloads. It populates a
metadata-only cache for the browse view. Downloads happen only when the user
explicitly selects video_ids and POSTs to the backlog/download endpoint. The
channel poller's forward-only auto-pull is a separate code path that does not
read this cache and is gated on `watcher.created_at` to skip backlog uploads.
Do not add download/queue logic here — it would couple two systems that the
v0.3 spec deliberately keeps independent.

Slow-refresh (`fetch_full_channel_with_views`):
- Resumable: skips items whose `view_count` is already populated. So if a
  user cancels mid-refresh and clicks Refresh again, we pick up where we
  stopped instead of re-probing every video.
- Cancellable: callers register watcher_ids in the module-level
  `_cancel_requests` set via `request_cancel()`. The probe loop checks the
  set between batches and exits cleanly with `cache.status='cancelled'`.
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

# In-memory cancel-flag set. Populated by request_cancel(); cleared by the
# slow-refresh loop on its next batch iteration.
_cancel_requests: set[int] = set()


def request_cancel(watcher_id: int) -> None:
    """Ask the running slow-refresh for `watcher_id` to stop after the next batch."""
    _cancel_requests.add(watcher_id)


def consume_cancel(watcher_id: int) -> bool:
    """Atomically check-and-clear. True iff a cancel was pending for this watcher."""
    if watcher_id in _cancel_requests:
        _cancel_requests.discard(watcher_id)
        return True
    return False


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


BATCH_SIZE = 20


async def fetch_full_channel_with_views(db: Database, watcher_id: int) -> int:
    """Slow-refresh: flat-extract first for IDs, then per-video probes for view_count.

    Resumable: items that already have a non-null `view_count` in the cache
    are skipped, so a cancel-then-refresh cycle picks up where it stopped.

    Cancellable: callers `request_cancel(watcher_id)` to stop after the next
    batch. On cancel the cache transitions to status='cancelled' with the
    partial progress preserved.
    """
    # Step 1: flat-extract (reuses existing path, gets the IDs). This wipes
    # any existing items_json including previously-probed view_counts — which
    # is correct: a fresh flat-extract may have new videos. Resumption only
    # makes sense WITHIN a single slow-refresh, not across them.
    #
    # ...except: if the cache is already populated and the user clicked
    # Refresh again to retry a cancelled slow-refresh, we want to keep the
    # view_counts we already paid for. Detect that case and skip step 1.
    with db.session() as s:
        existing = s.get(ChannelBacklogCache, watcher_id)
        existing_items = list(existing.items_json) if existing and existing.items_json else []
        existing_status = existing.status if existing else "never_fetched"

    has_partial_views = any(
        isinstance(it.get("view_count"), (int, float))
        or isinstance(it.get("like_count"), (int, float))
        for it in existing_items
    )
    skip_flat_extract = (
        existing_status == "cancelled" and has_partial_views and len(existing_items) > 0
    )

    if skip_flat_extract:
        # Resume: keep existing items + view_counts; just flip status to fetching.
        count = len(existing_items)
        with db.session() as s:
            cache = s.get(ChannelBacklogCache, watcher_id)
            if cache is not None:
                cache.status = "fetching"
                cache.error = None
    else:
        count = await fetch_full_channel(db, watcher_id)

    # Step 2: per-video probes in batches, skipping already-probed items.
    # An item is "probed" once it has either a view_count or like_count (the
    # probe sets both at once; either being a number means we ran it).
    def _is_probed(it: dict[str, object]) -> bool:
        return isinstance(it.get("view_count"), (int, float)) or isinstance(
            it.get("like_count"), (int, float)
        )

    with db.session() as s:
        cache = s.get(ChannelBacklogCache, watcher_id)
        if cache is None or cache.items_json is None:
            return count
        items = list(cache.items_json)
        ids_to_probe = [str(it["youtube_id"]) for it in items if not _is_probed(it)]
        cache.status = "fetching"
        already_probed = len(items) - len(ids_to_probe)
        total_items = len(items)
        cache.progress_pct = int(already_probed / max(total_items, 1) * 100) if total_items else 0

    if not ids_to_probe:
        with db.session() as s:
            cache = s.get(ChannelBacklogCache, watcher_id)
            if cache is not None:
                cache.status = "complete"
                cache.fetched_at = _dt.datetime.now(_dt.UTC)
                cache.progress_pct = 100
        return count

    import asyncio

    from concertpvr.recording_starter import _resolve_cookies_path
    from concertpvr.ytdlp_channels import ProbeResult, probe_video_metadata

    cookies_path = _resolve_cookies_path(db)
    cookies_str = str(cookies_path) if cookies_path else None

    view_counts: dict[str, int | None] = {}
    like_counts: dict[str, int | None] = {}
    cancelled = False

    for i in range(0, len(ids_to_probe), BATCH_SIZE):
        if consume_cancel(watcher_id):
            cancelled = True
            break

        batch = ids_to_probe[i : i + BATCH_SIZE]
        results = await asyncio.gather(
            *(probe_video_metadata(yid, cookies_path=cookies_str) for yid in batch),
            return_exceptions=False,
        )
        for r in results:
            if isinstance(r, ProbeResult):
                view_counts[r.youtube_id] = r.view_count
                like_counts[r.youtube_id] = r.like_count

        with db.session() as s:
            cache = s.get(ChannelBacklogCache, watcher_id)
            if cache is None:
                return count
            merged = []
            for it in cache.items_json or []:
                yid = str(it["youtube_id"])
                if yid in view_counts or yid in like_counts:
                    it = {
                        **it,
                        "view_count": view_counts.get(yid, it.get("view_count")),
                        "like_count": like_counts.get(yid, it.get("like_count")),
                    }
                merged.append(it)
            cache.items_json = merged
            done_so_far = sum(1 for it in merged if _is_probed(it))
            cache.progress_pct = int(done_so_far / max(total_items, 1) * 100)

    with db.session() as s:
        cache = s.get(ChannelBacklogCache, watcher_id)
        if cache is not None:
            if cancelled:
                cache.status = "cancelled"
            else:
                cache.status = "complete"
                cache.fetched_at = _dt.datetime.now(_dt.UTC)
                cache.progress_pct = 100

    return count


def is_stale(cache: ChannelBacklogCache | None) -> bool:
    if cache is None or cache.fetched_at is None or cache.status != "complete":
        return True
    age = _dt.datetime.now(_dt.UTC) - cache.fetched_at.replace(tzinfo=_dt.UTC)
    return age.total_seconds() > CACHE_TTL_HOURS * 3600
