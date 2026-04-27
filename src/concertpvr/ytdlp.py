"""yt-dlp metadata probe.

Uses yt-dlp as a Python library (not subprocess) for metadata-only fetches.
Recording (downloading live fragments) uses the subprocess CLI via process.py.
"""

from __future__ import annotations

import asyncio
import datetime as _dt
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yt_dlp  # type: ignore[import-untyped]

logger = logging.getLogger(__name__)


class ProbeError(Exception):
    """Raised when yt-dlp cannot extract info for a URL."""


@dataclass(frozen=True)
class StreamInfo:
    youtube_id: str
    url: str
    title: str
    channel_name: str
    is_live: bool
    thumbnail_url: str | None
    # v0.3 VOD metadata fields:
    original_upload_date: _dt.date | None = None
    description: str | None = None
    tags: list[str] | None = None
    chapters: list[dict[str, Any]] | None = None
    comments: list[dict[str, Any]] | None = None
    duration_s: int | None = None


def _parse_yt_date(s: str | None) -> _dt.date | None:
    """yt-dlp returns dates as YYYYMMDD strings."""
    if not s or len(s) != 8:
        return None
    try:
        return _dt.date(int(s[:4]), int(s[4:6]), int(s[6:8]))
    except (ValueError, TypeError):
        return None


def _extract_sync(
    url: str, cookies_path: str | None, fetch_comments: bool = False
) -> dict[str, object]:
    opts: dict[str, object] = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
    }
    if cookies_path:
        opts["cookiefile"] = cookies_path
    if fetch_comments:
        opts["getcomments"] = True
    with yt_dlp.YoutubeDL(opts) as ydl:
        result = ydl.extract_info(url, download=False)
        if result is None:
            raise ProbeError("no info returned")
        return result  # type: ignore[no-any-return]


async def probe(
    url: str,
    *,
    cookies_path: Path | None = None,
    fetch_comments: bool = False,
) -> StreamInfo:
    """Fetch metadata for a YouTube URL. Runs yt-dlp in a thread to avoid blocking.

    `cookies_path` is the optional Netscape-format cookies file for member-only
    or age-gated content. `fetch_comments=True` triggers yt-dlp's `getcomments=True`
    (slower probe, ~3-5s extra) — used by VOD watchers with
    extract_setlist_from_comments=True. Raises ProbeError on extraction failure.
    """
    cookies_str = str(cookies_path) if cookies_path and Path(cookies_path).exists() else None
    try:
        info = await asyncio.to_thread(_extract_sync, url, cookies_str, fetch_comments)
    except yt_dlp.utils.DownloadError as e:
        raise ProbeError(str(e)) from e
    except Exception as e:
        raise ProbeError(f"unexpected error: {e}") from e

    youtube_id: str = info["id"]  # type: ignore[assignment]
    webpage_url: str = info.get("webpage_url", url) or url  # type: ignore[assignment]
    title: str = info.get("title", "Untitled") or "Untitled"  # type: ignore[assignment]
    channel: str = (
        info.get("channel") or info.get("uploader") or "Unknown"  # type: ignore[assignment]
    )
    is_live: bool = bool(info.get("is_live", False))
    thumbnail_url: str | None = info.get("thumbnail")  # type: ignore[assignment]

    upload_date_str = info.get("release_date") or info.get("upload_date")
    upload_date = _parse_yt_date(upload_date_str if isinstance(upload_date_str, str) else None)

    description_raw = info.get("description")
    description: str | None = description_raw if isinstance(description_raw, str) else None
    if description and len(description) > 2_000_000:
        logger.warning(
            "description for %s truncated from %d to 2MB", youtube_id, len(description)
        )
        description = description[:2_000_000]

    tags_raw = info.get("tags")
    tags: list[str] | None = list(tags_raw) if isinstance(tags_raw, list) else None

    chapters_raw = info.get("chapters")
    chapters: list[dict[str, Any]] | None = (
        list(chapters_raw) if isinstance(chapters_raw, list) else None
    )

    comments_raw = info.get("comments") if fetch_comments else None
    comments: list[dict[str, Any]] | None = (
        list(comments_raw) if isinstance(comments_raw, list) else None
    )

    duration_raw = info.get("duration")
    duration_s: int | None = (
        int(duration_raw) if isinstance(duration_raw, (int, float)) else None
    )

    return StreamInfo(
        youtube_id=youtube_id,
        url=webpage_url,
        title=title,
        channel_name=channel,
        is_live=is_live,
        thumbnail_url=thumbnail_url,
        original_upload_date=upload_date,
        description=description,
        tags=tags,
        chapters=chapters,
        comments=comments,
        duration_s=duration_s,
    )
