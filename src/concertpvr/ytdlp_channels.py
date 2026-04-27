"""yt-dlp helpers for channel polling."""

from __future__ import annotations

import asyncio
import datetime as _dt
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yt_dlp  # type: ignore[import-untyped]

logger = logging.getLogger(__name__)


class ChannelProbeError(Exception):
    """Raised when probe_channel cannot extract channel metadata."""


@dataclass(frozen=True)
class BroadcastInfo:
    youtube_id: str
    url: str
    title: str
    channel_name: str
    is_live: bool
    upload_date: _dt.date | None = field(default=None)
    duration_s: int | None = field(default=None)
    thumbnail_url: str | None = field(default=None)


@dataclass(frozen=True)
class ChannelInfo:
    channel_name: str
    canonical_url: str
    avatar_url: str | None


def _streams_url(channel_url: str) -> str:
    base = channel_url.rstrip("/")
    if base.endswith("/streams") or base.endswith("/videos") or base.endswith("/live"):
        return base
    return f"{base}/streams"


def _extract_sync(url: str) -> dict[str, Any]:  # noqa: B008
    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": True,
    }
    ydl = yt_dlp.YoutubeDL(opts)
    try:
        info = ydl.extract_info(url, download=False)
        return info if isinstance(info, dict) else {}
    finally:
        ydl.close()


async def fetch_channel_live_broadcasts(channel_url: str) -> list[BroadcastInfo]:
    streams_url = _streams_url(channel_url)
    try:
        data = await asyncio.to_thread(_extract_sync, streams_url)
    except Exception as e:  # noqa: BLE001
        logger.warning("channel poll for %s failed: %s", channel_url, e)
        return []

    if not data:
        return []
    entries = data.get("entries") or []
    out: list[BroadcastInfo] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if not entry.get("is_live"):
            continue
        out.append(
            BroadcastInfo(
                youtube_id=str(entry.get("id", "")),
                url=str(
                    entry.get("url")
                    or entry.get("webpage_url")
                    or f"https://www.youtube.com/watch?v={entry.get('id', '')}"
                ),
                title=str(entry.get("title", "")),
                channel_name=str(
                    entry.get("channel") or data.get("uploader") or data.get("title", "")
                ),
                is_live=True,
            )
        )
    return out


def _uploads_url(channel_url: str) -> str:
    """Return the /videos tab URL for upload listings."""
    base = channel_url.rstrip("/")
    # Strip any existing tab suffix and append /videos
    for suffix in ("/streams", "/videos", "/live"):
        if base.endswith(suffix):
            base = base[: -len(suffix)]
            break
    return f"{base}/videos"


def _parse_yt_date(s: str | None) -> _dt.date | None:
    """yt-dlp returns dates as YYYYMMDD strings."""
    if not s or len(s) != 8:
        return None
    try:
        return _dt.date(int(s[:4]), int(s[4:6]), int(s[6:8]))
    except (ValueError, TypeError):
        return None


async def list_recent_uploads(
    channel_url: str,
    *,
    cookies_path: Path | None = None,
    limit: int = 20,
) -> list[BroadcastInfo]:
    """Flat-extract the channel's /videos tab and return recent non-live uploads.

    Filters out entries where ``is_live`` is truthy (covered by the live path).
    Returns ``BroadcastInfo`` objects with ``is_live=False``.  ``upload_date`` is
    populated from yt-dlp's ``upload_date`` or ``release_date`` field.
    """
    uploads_url = _uploads_url(channel_url)
    opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": True,
        "playlistend": limit,
    }
    if cookies_path is not None and Path(cookies_path).exists():
        opts["cookiefile"] = str(cookies_path)

    def _run() -> dict[str, Any]:
        ydl = yt_dlp.YoutubeDL(opts)
        try:
            info = ydl.extract_info(uploads_url, download=False)
            return info if isinstance(info, dict) else {}
        finally:
            ydl.close()

    try:
        data = await asyncio.to_thread(_run)
    except Exception as e:  # noqa: BLE001
        logger.warning("list_recent_uploads for %s failed: %s", channel_url, e)
        return []

    if not data:
        return []

    entries = data.get("entries") or []
    channel_name = str(data.get("uploader") or data.get("channel") or data.get("title", ""))
    out: list[BroadcastInfo] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if entry.get("is_live"):
            continue
        raw_date = entry.get("release_date") or entry.get("upload_date")
        upload_date = _parse_yt_date(raw_date if isinstance(raw_date, str) else None)
        duration_raw = entry.get("duration")
        duration_s: int | None = (
            int(duration_raw) if isinstance(duration_raw, (int, float)) else None
        )
        out.append(
            BroadcastInfo(
                youtube_id=str(entry.get("id", "")),
                url=str(
                    entry.get("url")
                    or entry.get("webpage_url")
                    or f"https://www.youtube.com/watch?v={entry.get('id', '')}"
                ),
                title=str(entry.get("title", "")),
                channel_name=str(entry.get("channel") or channel_name),
                is_live=False,
                upload_date=upload_date,
                duration_s=duration_s,
                thumbnail_url=str(entry["thumbnail"]) if entry.get("thumbnail") else f"https://i.ytimg.com/vi/{entry.get('id', '')}/mqdefault.jpg",
            )
        )
        if len(out) >= limit:
            break
    return out


async def list_all_uploads(
    channel_url: str,
    *,
    cookies_path: Path | None = None,
) -> list[BroadcastInfo]:
    """Flat-extract the entire channel uploads tab (no playlistend cap).

    For large channels this can return thousands of entries and take 30-60s.
    Caller should run this in a background task and surface progress via
    a status field on the cache row.
    """
    uploads_url = _uploads_url(channel_url)
    opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": True,
        # No playlistend = full channel
    }
    if cookies_path is not None and Path(cookies_path).exists():
        opts["cookiefile"] = str(cookies_path)

    def _run() -> dict[str, Any]:
        ydl = yt_dlp.YoutubeDL(opts)
        try:
            info = ydl.extract_info(uploads_url, download=False)
            return info if isinstance(info, dict) else {}
        finally:
            ydl.close()

    try:
        data = await asyncio.to_thread(_run)
    except Exception as e:  # noqa: BLE001
        logger.warning("list_all_uploads for %s failed: %s", channel_url, e)
        raise

    entries = data.get("entries") or []
    channel_name = str(data.get("uploader") or data.get("channel") or data.get("title", ""))
    out: list[BroadcastInfo] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if entry.get("is_live"):
            continue
        raw_date = entry.get("release_date") or entry.get("upload_date")
        upload_date = _parse_yt_date(raw_date if isinstance(raw_date, str) else None)
        duration_raw = entry.get("duration")
        duration_s: int | None = (
            int(duration_raw) if isinstance(duration_raw, (int, float)) else None
        )
        yid = str(entry.get("id", ""))
        if not yid:
            continue
        # Thumbnail fallback: if flat-extract didn't return one, use YouTube's
        # canonical mqdefault URL — guaranteed to exist for any public video.
        thumb = entry.get("thumbnail")
        thumbnail_url = str(thumb) if thumb else f"https://i.ytimg.com/vi/{yid}/mqdefault.jpg"
        out.append(
            BroadcastInfo(
                youtube_id=yid,
                url=str(
                    entry.get("url")
                    or entry.get("webpage_url")
                    or f"https://www.youtube.com/watch?v={yid}"
                ),
                title=str(entry.get("title", "")),
                channel_name=str(entry.get("channel") or channel_name),
                is_live=False,
                upload_date=upload_date,
                duration_s=duration_s,
                thumbnail_url=thumbnail_url,
            )
        )
    return out


async def probe_channel(channel_url: str) -> ChannelInfo:
    streams_url = _streams_url(channel_url)
    try:
        data = await asyncio.to_thread(_extract_sync, streams_url)
    except yt_dlp.utils.DownloadError as e:
        raise ChannelProbeError(str(e)) from e
    except Exception as e:
        raise ChannelProbeError(f"unexpected error: {e}") from e

    if not data:
        raise ChannelProbeError("no info returned")

    return ChannelInfo(
        channel_name=str(data.get("uploader") or data.get("title", "Unknown")),
        canonical_url=str(data.get("webpage_url", streams_url)),
        avatar_url=str(data.get("thumbnail")) if data.get("thumbnail") else None,
    )
