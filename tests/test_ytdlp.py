import json
from pathlib import Path

import pytest

from concertpvr.ytdlp import StreamInfo, ProbeError, probe

FIXTURE = Path(__file__).parent / "fixtures" / "ytdlp_live_info.json"


@pytest.fixture
def fake_extract(monkeypatch):
    info = json.loads(FIXTURE.read_text())

    def _fake_init(self, params=None):  # noqa: ARG001
        self.params = params or {}

    def _fake_extract(self, url, download=False):  # noqa: ARG001
        return info

    def _fake_close(self):
        pass

    def _fake_enter(self):
        return self

    def _fake_exit(self, *args):  # noqa: ARG001
        pass

    import yt_dlp
    monkeypatch.setattr(yt_dlp.YoutubeDL, "__init__", _fake_init)
    monkeypatch.setattr(yt_dlp.YoutubeDL, "extract_info", _fake_extract)
    monkeypatch.setattr(yt_dlp.YoutubeDL, "close", _fake_close)
    monkeypatch.setattr(yt_dlp.YoutubeDL, "__enter__", _fake_enter)
    monkeypatch.setattr(yt_dlp.YoutubeDL, "__exit__", _fake_exit)
    return info


@pytest.mark.asyncio
async def test_probe_returns_stream_info(fake_extract):
    info = await probe("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    assert isinstance(info, StreamInfo)
    assert info.youtube_id == "dQw4w9WgXcQ"
    assert info.url == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    assert info.title == fake_extract["title"]
    assert info.channel_name == "Coachella"
    assert info.is_live is True
    assert info.thumbnail_url is not None


@pytest.mark.asyncio
async def test_probe_raises_on_extract_failure(monkeypatch):
    import yt_dlp

    def _fake_init(self, params=None):  # noqa: ARG001
        self.params = params or {}

    def _fake_extract(self, url, download=False):  # noqa: ARG001
        raise yt_dlp.utils.DownloadError("video unavailable")

    def _fake_enter(self):
        return self

    def _fake_exit(self, *args):  # noqa: ARG001
        pass

    monkeypatch.setattr(yt_dlp.YoutubeDL, "__init__", _fake_init)
    monkeypatch.setattr(yt_dlp.YoutubeDL, "extract_info", _fake_extract)
    monkeypatch.setattr(yt_dlp.YoutubeDL, "close", lambda self: None)
    monkeypatch.setattr(yt_dlp.YoutubeDL, "__enter__", _fake_enter)
    monkeypatch.setattr(yt_dlp.YoutubeDL, "__exit__", _fake_exit)

    with pytest.raises(ProbeError) as exc:
        await probe("https://www.youtube.com/watch?v=missing")
    assert "video unavailable" in str(exc.value).lower()


@pytest.mark.asyncio
async def test_probe_handles_missing_optional_fields(monkeypatch):
    import yt_dlp

    minimal = {
        "id": "abc123",
        "webpage_url": "https://www.youtube.com/watch?v=abc123",
        "title": "Untitled",
        "uploader": "Unknown",
    }

    def _fake_init(self, params=None):  # noqa: ARG001
        self.params = params or {}

    def _fake_enter(self):
        return self

    def _fake_exit(self, *args):  # noqa: ARG001
        pass

    monkeypatch.setattr(yt_dlp.YoutubeDL, "__init__", _fake_init)
    monkeypatch.setattr(yt_dlp.YoutubeDL, "extract_info", lambda self, url, download=False: minimal)
    monkeypatch.setattr(yt_dlp.YoutubeDL, "close", lambda self: None)
    monkeypatch.setattr(yt_dlp.YoutubeDL, "__enter__", _fake_enter)
    monkeypatch.setattr(yt_dlp.YoutubeDL, "__exit__", _fake_exit)

    info = await probe("https://www.youtube.com/watch?v=abc123")
    assert info.channel_name == "Unknown"
    assert info.thumbnail_url is None
    assert info.is_live is False
