"""Real-network integration tests against actual YouTube + yt-dlp.

Skipped unless `CPVR_INTEGRATION_TESTS=1` is set in the environment. These tests:
  - Hit the real YouTube API (yt-dlp's scrapes)
  - Take ~30s each
  - Need network access
  - Fail in flaky ways if YouTube changes

Run manually before tagging a release:
    CPVR_INTEGRATION_TESTS=1 ./.venv/Scripts/python.exe -m pytest tests/integration/ -v

These tests catch bugs that mocked tests cannot — wrong output paths, regex
mismatches against real yt-dlp stdout, response-shape changes from YouTube.
"""

from __future__ import annotations

import os

import pytest

from concertpvr.playlist_ingest import expand_playlist
from concertpvr.ytdlp import probe
from concertpvr.ytdlp_channels import list_recent_uploads, probe_channel

pytestmark = pytest.mark.skipif(
    os.environ.get("CPVR_INTEGRATION_TESTS") != "1",
    reason="Set CPVR_INTEGRATION_TESTS=1 to run real-network tests",
)

# Stable canonical test URL — Rick Astley, will likely outlive us all.
RICKROLL_URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
NPR_MUSIC_CHANNEL = "https://www.youtube.com/@nprmusic"


@pytest.mark.asyncio
async def test_probe_real_video_returns_full_streaminfo():
    info = await probe(RICKROLL_URL)
    assert info.youtube_id == "dQw4w9WgXcQ"
    assert info.title  # non-empty
    assert info.channel_name  # non-empty
    assert info.is_live is False
    assert info.thumbnail_url and info.thumbnail_url.startswith("http")
    # v0.3 fields:
    assert info.original_upload_date is not None
    assert info.original_upload_date.year == 2009  # known fact about this video
    assert info.description is not None
    assert info.duration_s is not None
    assert info.duration_s > 0


@pytest.mark.asyncio
async def test_probe_channel_real_returns_metadata():
    ch = await probe_channel(NPR_MUSIC_CHANNEL)
    assert ch.channel_name  # something like "NPR Music"
    assert ch.canonical_url.startswith("http")


@pytest.mark.asyncio
async def test_list_recent_uploads_real_channel():
    uploads = await list_recent_uploads(NPR_MUSIC_CHANNEL, limit=10)
    assert len(uploads) > 0
    first = uploads[0]
    assert first.youtube_id  # non-empty
    assert first.title  # non-empty
    assert first.is_live is False  # filtered out by the function
    # upload_date may be None for some entries; that's allowed.


@pytest.mark.asyncio
async def test_expand_playlist_real():
    # NPR Music Tiny Desk Concerts playlist (stable, well-known)
    playlist_url = "https://www.youtube.com/playlist?list=PLy2PCKGkKRVZWvD4yTyaxTucl8x3vBYAr"
    info = await expand_playlist(playlist_url, limit=10)
    assert info.playlist_id  # non-empty
    assert info.count > 0
    assert len(info.entries) > 0
    first = info.entries[0]
    assert first.youtube_id
    assert first.title
