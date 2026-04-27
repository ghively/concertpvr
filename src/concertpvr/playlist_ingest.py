# src/concertpvr/playlist_ingest.py
"""Expand a YouTube playlist URL into a list of video metadata."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

import yt_dlp  # type: ignore[import-untyped]

from concertpvr.ytdlp import ProbeError, _parse_yt_date


@dataclass(frozen=True)
class PlaylistEntry:
    youtube_id: str
    title: str
    url: str
    channel_name: str
    thumbnail_url: str | None
    duration_s: int | None
    upload_date: object | None  # _dt.date


@dataclass(frozen=True)
class PlaylistInfo:
    playlist_id: str
    playlist_title: str
    count: int
    entries: list[PlaylistEntry]


def _extract_playlist_sync(url: str, cookies_path: str | None, limit: int) -> dict:  # type: ignore[type-arg]
    opts: dict[str, object] = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
        "playlistend": limit,
    }
    if cookies_path:
        opts["cookiefile"] = cookies_path
    with yt_dlp.YoutubeDL(opts) as ydl:
        result = ydl.extract_info(url, download=False)
        if result is None:
            raise ProbeError("no playlist info returned")
        return result  # type: ignore[no-any-return]


async def expand_playlist(
    url: str,
    *,
    cookies_path: Path | None = None,
    limit: int = 500,
) -> PlaylistInfo:
    cookies_str = str(cookies_path) if cookies_path and Path(cookies_path).exists() else None
    try:
        info = await asyncio.to_thread(_extract_playlist_sync, url, cookies_str, limit)
    except yt_dlp.utils.DownloadError as e:
        raise ProbeError(str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise ProbeError(f"unexpected error: {e}") from e

    entries_raw = info.get("entries") or []
    entries: list[PlaylistEntry] = []
    for entry in entries_raw:
        if entry is None:
            continue
        yid = entry.get("id") or ""
        if not yid:
            continue
        entries.append(PlaylistEntry(
            youtube_id=yid,
            title=entry.get("title") or "Untitled",
            url=entry.get("url") or entry.get("webpage_url") or f"https://www.youtube.com/watch?v={yid}",
            channel_name=entry.get("channel") or entry.get("uploader") or info.get("channel") or "Unknown",
            thumbnail_url=entry.get("thumbnail"),
            duration_s=int(entry["duration"]) if entry.get("duration") is not None else None,
            upload_date=_parse_yt_date(entry.get("upload_date") or entry.get("release_date")),
        ))

    return PlaylistInfo(
        playlist_id=info.get("id", ""),
        playlist_title=info.get("title", "Untitled Playlist"),
        count=info.get("playlist_count") or len(entries),
        entries=entries,
    )
