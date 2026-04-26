import json
from pathlib import Path

import pytest

from concertpvr.ytdlp_channels import (
    BroadcastInfo,
    ChannelInfo,
    fetch_channel_live_broadcasts,
    probe_channel,
)

FIXTURE = Path(__file__).parent / "fixtures" / "ytdlp_channel_streams.json"


@pytest.fixture
def fake_extract(monkeypatch):
    info = json.loads(FIXTURE.read_text())

    def _fake_init(self, params=None):  # noqa: ARG001
        pass

    def _fake_extract(self, url, download=False):  # noqa: ARG001
        return info

    def _fake_close(self):
        pass

    import yt_dlp

    monkeypatch.setattr(yt_dlp.YoutubeDL, "__init__", _fake_init)
    monkeypatch.setattr(yt_dlp.YoutubeDL, "extract_info", _fake_extract)
    monkeypatch.setattr(yt_dlp.YoutubeDL, "close", _fake_close)
    return info


@pytest.mark.asyncio
async def test_fetch_returns_only_live_broadcasts(fake_extract):
    broadcasts = await fetch_channel_live_broadcasts("https://www.youtube.com/@nprmusic")
    assert len(broadcasts) == 1
    assert isinstance(broadcasts[0], BroadcastInfo)
    assert broadcasts[0].youtube_id == "live123"
    assert broadcasts[0].is_live is True
    assert broadcasts[0].channel_name == "NPR Music"


@pytest.mark.asyncio
async def test_fetch_returns_empty_on_extract_error(monkeypatch):
    import yt_dlp

    monkeypatch.setattr(yt_dlp.YoutubeDL, "__init__", lambda self, params=None: None)

    def _raise(self, url, download=False):  # noqa: ARG001
        raise yt_dlp.utils.DownloadError("channel unavailable")

    monkeypatch.setattr(yt_dlp.YoutubeDL, "extract_info", _raise)
    monkeypatch.setattr(yt_dlp.YoutubeDL, "close", lambda self: None)

    result = await fetch_channel_live_broadcasts("https://www.youtube.com/@bad")
    assert result == []


@pytest.mark.asyncio
async def test_fetch_returns_empty_when_no_entries(monkeypatch):
    import yt_dlp

    monkeypatch.setattr(yt_dlp.YoutubeDL, "__init__", lambda self, params=None: None)
    monkeypatch.setattr(
        yt_dlp.YoutubeDL,
        "extract_info",
        lambda self, url, download=False: {"_type": "playlist", "entries": []},
    )
    monkeypatch.setattr(yt_dlp.YoutubeDL, "close", lambda self: None)

    result = await fetch_channel_live_broadcasts("https://www.youtube.com/@empty")
    assert result == []


@pytest.mark.asyncio
async def test_probe_channel_returns_metadata(fake_extract):
    info = await probe_channel("https://www.youtube.com/@nprmusic")
    assert isinstance(info, ChannelInfo)
    assert info.channel_name == "NPR Music"
    assert info.avatar_url == "https://example.com/avatar.jpg"


@pytest.mark.asyncio
async def test_probe_channel_raises_on_error(monkeypatch):
    import yt_dlp

    from concertpvr.ytdlp_channels import ChannelProbeError

    monkeypatch.setattr(yt_dlp.YoutubeDL, "__init__", lambda self, params=None: None)

    def _raise(self, url, download=False):  # noqa: ARG001
        raise yt_dlp.utils.DownloadError("not a channel")

    monkeypatch.setattr(yt_dlp.YoutubeDL, "extract_info", _raise)
    monkeypatch.setattr(yt_dlp.YoutubeDL, "close", lambda self: None)

    with pytest.raises(ChannelProbeError):
        await probe_channel("https://www.youtube.com/@nope")
