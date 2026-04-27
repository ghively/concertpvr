"""VOD downloader — yt-dlp subprocess invocation, progress parsing."""

from __future__ import annotations

import pytest

from concertpvr.process import FakeProcessRunner
from concertpvr.vod_downloader import VodDownloadError, VodDownloader, VodProgress


@pytest.mark.asyncio
async def test_downloader_invokes_ytdlp_with_correct_args(tmp_path):
    runner = FakeProcessRunner()
    runner.queue("yt-dlp", stdout=[], exit_code=0)
    output_path = tmp_path / "out.mkv"
    dl = VodDownloader(runner=runner)

    await dl.download(
        url="https://www.youtube.com/watch?v=abc",
        output_path=output_path,
        quality_format="bestvideo*+bestaudio/best",
        cookies_path=None,
        on_progress=None,
    )

    args = runner.spawned[0]
    assert args[0] == "yt-dlp"
    assert "--continue" in args
    assert "-f" in args and "bestvideo*+bestaudio/best" in args
    assert "-o" in args
    assert str(output_path) in args[args.index("-o") + 1]
    assert args[-1] == "https://www.youtube.com/watch?v=abc"


@pytest.mark.asyncio
async def test_downloader_passes_cookies_when_set(tmp_path):
    cookies = tmp_path / "cookies.txt"
    cookies.write_text("# cookies")
    runner = FakeProcessRunner()
    runner.queue("yt-dlp", stdout=[], exit_code=0)
    dl = VodDownloader(runner=runner)

    await dl.download(
        url="https://x",
        output_path=tmp_path / "o.mkv",
        quality_format="best",
        cookies_path=cookies,
        on_progress=None,
    )

    args = runner.spawned[0]
    assert "--cookies" in args
    idx = args.index("--cookies")
    assert args[idx + 1] == str(cookies)


@pytest.mark.asyncio
async def test_downloader_parses_progress_lines(tmp_path):
    progress_events: list[VodProgress] = []

    async def collect(p: VodProgress) -> None:
        progress_events.append(p)

    # yt-dlp emits "[download]  10.5% of   1.20GiB at  2.50MiB/s ETA 03:24"
    runner = FakeProcessRunner()
    runner.queue(
        "yt-dlp",
        stdout=[
            "[download]   0.0% of  1.20GiB at Unknown ETA Unknown",
            "[download]  10.5% of  1.20GiB at  2.50MiB/s ETA 03:24",
            "[download]  50.0% of  1.20GiB at  3.00MiB/s ETA 01:10",
            "[download] 100.0% of  1.20GiB",
        ],
        exit_code=0,
    )

    dl = VodDownloader(runner=runner)
    await dl.download(
        url="https://x",
        output_path=tmp_path / "o.mkv",
        quality_format="best",
        cookies_path=None,
        on_progress=collect,
    )

    assert len(progress_events) >= 3
    assert progress_events[1].pct == pytest.approx(10.5, abs=0.1)
    assert progress_events[1].eta_s == 3 * 60 + 24


@pytest.mark.asyncio
async def test_downloader_raises_on_nonzero_exit(tmp_path):
    runner = FakeProcessRunner()
    runner.queue("yt-dlp", stdout=["ERROR: Video unavailable"], exit_code=1)
    dl = VodDownloader(runner=runner)

    with pytest.raises(VodDownloadError) as exc_info:
        await dl.download(
            url="https://x",
            output_path=tmp_path / "o.mkv",
            quality_format="best",
            cookies_path=None,
            on_progress=None,
        )
    assert "Video unavailable" in str(exc_info.value)
