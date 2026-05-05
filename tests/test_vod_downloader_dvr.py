"""VodDownloader.live_from_start option (v0.4.1)."""

import pytest

from concertpvr.process import FakeProcessRunner
from concertpvr.vod_downloader import VodDownloader


@pytest.mark.asyncio
async def test_live_from_start_adds_flag_to_argv(tmp_path):
    runner = FakeProcessRunner()
    runner.queue("yt-dlp", stdout=[], stderr=[], exit_code=0)
    d = VodDownloader(runner=runner)

    out = tmp_path / "dvr-abc.%(ext)s"
    await d.download(
        url="https://www.youtube.com/watch?v=abc",
        output_path=out,
        quality_format="best",
        cookies_path=None,
        on_progress=None,
        live_from_start=True,
    )

    assert len(runner.spawned) == 1
    argv = runner.spawned[0]
    assert "--live-from-start" in argv


@pytest.mark.asyncio
async def test_default_does_not_add_live_from_start_flag(tmp_path):
    runner = FakeProcessRunner()
    runner.queue("yt-dlp", stdout=[], stderr=[], exit_code=0)
    d = VodDownloader(runner=runner)

    out = tmp_path / "vod-abc.%(ext)s"
    await d.download(
        url="https://www.youtube.com/watch?v=abc",
        output_path=out,
        quality_format="best",
        cookies_path=None,
        on_progress=None,
    )

    argv = runner.spawned[0]
    assert "--live-from-start" not in argv
