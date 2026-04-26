"""yt-dlp metadata probe.

Uses yt-dlp as a Python library (not subprocess) for metadata-only fetches.
Recording (downloading live fragments) uses the subprocess CLI via process.py.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import yt_dlp  # type: ignore[import-untyped]


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


def _extract_sync(url: str) -> dict[str, object]:
    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        result = ydl.extract_info(url, download=False)
        if result is None:
            raise ProbeError("no info returned")
        return result  # type: ignore[no-any-return]


async def probe(url: str) -> StreamInfo:
    """Fetch metadata for a YouTube URL. Runs yt-dlp in a thread to avoid blocking.

    Raises ProbeError on extraction failure.
    """
    try:
        info = await asyncio.to_thread(_extract_sync, url)
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

    return StreamInfo(
        youtube_id=youtube_id,
        url=webpage_url,
        title=title,
        channel_name=channel,
        is_live=is_live,
        thumbnail_url=thumbnail_url,
    )
