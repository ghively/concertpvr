"""yt-dlp helpers for channel polling."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
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
