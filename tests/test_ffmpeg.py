from pathlib import Path

import pytest

from concertpvr.ffmpeg import ProbeInfo, Splitter
from concertpvr.process import AsyncSubprocessRunner

FIXTURE = Path(__file__).parent / "fixtures" / "tiny.mp4"


@pytest.mark.asyncio
async def test_probe_returns_dimensions_and_duration():
    splitter = Splitter(AsyncSubprocessRunner())
    info = await splitter.probe(FIXTURE)
    assert isinstance(info, ProbeInfo)
    assert info.width == 320
    assert info.height == 180
    assert 2.5 <= info.duration_s <= 3.5
    assert 25 <= info.fps <= 31


@pytest.mark.asyncio
async def test_cut_writes_a_shorter_file(tmp_path: Path):
    splitter = Splitter(AsyncSubprocessRunner())
    out = tmp_path / "cut.mp4"
    await splitter.cut(FIXTURE, out, start_s=0.5, end_s=1.5)
    assert out.exists() and out.stat().st_size > 0

    info = await splitter.probe(out)
    assert 0.8 <= info.duration_s <= 1.5


@pytest.mark.asyncio
async def test_thumbnail_writes_jpeg(tmp_path: Path):
    splitter = Splitter(AsyncSubprocessRunner())
    out = tmp_path / "thumb.jpg"
    await splitter.thumbnail(FIXTURE, out, at_s=1.0)
    assert out.exists() and out.stat().st_size > 0

    header = out.read_bytes()[:3]
    assert header == b"\xff\xd8\xff"


@pytest.mark.asyncio
async def test_cut_raises_on_ffmpeg_failure(tmp_path: Path):
    splitter = Splitter(AsyncSubprocessRunner())
    nonexistent = tmp_path / "nonexistent.mp4"
    out = tmp_path / "cut.mp4"
    with pytest.raises(RuntimeError):
        await splitter.cut(nonexistent, out, 0.0, 1.0)
