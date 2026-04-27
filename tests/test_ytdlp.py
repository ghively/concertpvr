import json
from pathlib import Path

import pytest

from concertpvr.ytdlp import ProbeError, StreamInfo, probe

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


def test_parse_yt_date_valid():
    import datetime as _dt

    from concertpvr.ytdlp import _parse_yt_date

    assert _parse_yt_date("20200902") == _dt.date(2020, 9, 2)
    assert _parse_yt_date("19991231") == _dt.date(1999, 12, 31)


def test_parse_yt_date_invalid_returns_none():
    from concertpvr.ytdlp import _parse_yt_date

    assert _parse_yt_date(None) is None
    assert _parse_yt_date("") is None
    assert _parse_yt_date("not-a-date") is None
    assert _parse_yt_date("20201301") is None  # invalid month


@pytest.mark.asyncio
async def test_probe_captures_vod_metadata(monkeypatch):
    """When yt-dlp returns vod-style metadata, StreamInfo carries it."""
    import datetime as _dt

    import yt_dlp

    fake_info = {
        "id": "abc123",
        "webpage_url": "https://www.youtube.com/watch?v=abc123",
        "title": "Khruangbin: Tiny Desk Concert",
        "channel": "NPR Music",
        "is_live": False,
        "thumbnail": "https://example.com/t.jpg",
        "upload_date": "20200902",
        "description": "For Khruangbin's debut Tiny Desk...",
        "tags": ["khruangbin", "tiny desk", "indie"],
        "chapters": [{"start_time": 0, "end_time": 80, "title": "Intro"}],
        "duration": 1122,
    }

    def _fake_init(self, params=None):  # noqa: ARG001
        self.params = params or {}

    def _fake_enter(self):
        return self

    def _fake_exit(self, *args):  # noqa: ARG001
        pass

    monkeypatch.setattr(yt_dlp.YoutubeDL, "__init__", _fake_init)
    monkeypatch.setattr(
        yt_dlp.YoutubeDL,
        "extract_info",
        lambda self, url, download=False: fake_info,  # noqa: ARG005
    )
    monkeypatch.setattr(yt_dlp.YoutubeDL, "close", lambda self: None)
    monkeypatch.setattr(yt_dlp.YoutubeDL, "__enter__", _fake_enter)
    monkeypatch.setattr(yt_dlp.YoutubeDL, "__exit__", _fake_exit)

    info = await probe("https://www.youtube.com/watch?v=abc123")

    assert info.youtube_id == "abc123"
    assert info.is_live is False
    assert info.original_upload_date == _dt.date(2020, 9, 2)
    assert info.description is not None
    assert info.description.startswith("For Khruangbin")
    assert info.tags == ["khruangbin", "tiny desk", "indie"]
    assert info.chapters == [{"start_time": 0, "end_time": 80, "title": "Intro"}]
    assert info.duration_s == 1122
    assert info.comments is None  # not requested


@pytest.mark.asyncio
async def test_probe_passes_getcomments_when_fetch_comments_true(monkeypatch):
    """fetch_comments=True must set getcomments=True in yt-dlp opts."""
    import yt_dlp

    captured_params: dict = {}

    def _fake_init(self, params=None):
        self.params = params or {}
        captured_params.update(self.params)

    def _fake_enter(self):
        return self

    def _fake_exit(self, *args):  # noqa: ARG001
        pass

    fake_info = {
        "id": "x",
        "webpage_url": "https://x",
        "title": "T",
        "channel": "C",
        "is_live": False,
        "thumbnail": None,
        "comments": [{"is_pinned": True, "text": "hi", "like_count": 1}],
    }

    monkeypatch.setattr(yt_dlp.YoutubeDL, "__init__", _fake_init)
    monkeypatch.setattr(
        yt_dlp.YoutubeDL,
        "extract_info",
        lambda self, url, download=False: fake_info,  # noqa: ARG005
    )
    monkeypatch.setattr(yt_dlp.YoutubeDL, "close", lambda self: None)
    monkeypatch.setattr(yt_dlp.YoutubeDL, "__enter__", _fake_enter)
    monkeypatch.setattr(yt_dlp.YoutubeDL, "__exit__", _fake_exit)

    info = await probe("https://x", fetch_comments=True)
    assert captured_params.get("getcomments") is True
    assert info.comments is not None
    assert len(info.comments) == 1
