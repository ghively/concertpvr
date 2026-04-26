"""yt-dlp helpers for channel polling."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

import yt_dlp

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


def _extract_sync(url: str) -> dict:
    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": True,
    }
    ydl = yt_dlp.YoutubeDL(opts)
    try:
        return ydl.extract_info(url, download=False)
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
    for e in entries:
        if not isinstance(e, dict):
            continue
        if not e.get("is_live"):
            continue
        out.append(BroadcastInfo(
            youtube_id=e.get("id", ""),
            url=e.get("url") or e.get("webpage_url") or f"https://www.youtube.com/watch?v={e.get('id', '')}",
            title=e.get("title", ""),
            channel_name=e.get("channel") or data.get("uploader") or data.get("title", ""),
            is_live=True,
        ))
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
        channel_name=data.get("uploader") or data.get("title", "Unknown"),
        canonical_url=data.get("webpage_url", streams_url),
        avatar_url=data.get("thumbnail"),
    )
