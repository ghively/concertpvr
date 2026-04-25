"""yt-dlp metadata probe.

Uses yt-dlp as a Python library (not subprocess) for metadata-only fetches.
Recording (downloading live fragments) uses the subprocess CLI via process.py.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import yt_dlp


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


def _extract_sync(url: str) -> dict:
    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        return ydl.extract_info(url, download=False)


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

    if info is None:
        raise ProbeError("no info returned")

    return StreamInfo(
        youtube_id=info["id"],
        url=info.get("webpage_url", url),
        title=info.get("title", "Untitled"),
        channel_name=info.get("channel") or info.get("uploader") or "Unknown",
        is_live=bool(info.get("is_live", False)),
        thumbnail_url=info.get("thumbnail"),
    )
