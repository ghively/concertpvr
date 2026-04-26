import datetime as dt
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from concertpvr.db import Database
from concertpvr.models import Base, Recording, Segment, Stream
from concertpvr.process import AsyncSubprocessRunner
from concertpvr.publisher import PublishWorker


@pytest.fixture
def db(tmp_path):
    d = Database(f"sqlite:///{tmp_path / 'pub.db'}")
    Base.metadata.create_all(d.engine)
    return d


def _seed(db: Database, source_path: Path) -> int:
    with db.session() as s:
        stream = Stream(
            kind="live",
            youtube_id="x",
            url="u",
            title="Coachella W1 — Mojave Stage",
            channel_name="Coachella",
        )
        s.add(stream)
        s.flush()
        rec = Recording(
            stream_id=stream.id,
            started_at=dt.datetime(2026, 4, 12, 14, 0, tzinfo=dt.UTC),
            path=str(source_path),
            is_buffer=False,
            status="complete",
        )
        s.add(rec)
        s.flush()
        seg = Segment(
            recording_id=rec.id,
            artist="Phoebe Bridgers",
            title="Mojave Set",
            start_s=0,
            end_s=2,
            source="manual",
            status="draft",
        )
        s.add(seg)
        s.flush()
        return seg.id


@pytest.fixture
def fixture_video():
    return Path(__file__).parent / "fixtures" / "tiny.mp4"


@pytest.mark.asyncio
async def test_publish_writes_emby_dir_with_clip_nfo_poster_fanart(db, tmp_path, fixture_video):
    seg_id = _seed(db, fixture_video)

    publish_root = tmp_path / "media" / "concerts"
    emby_client = MagicMock()
    emby_client.trigger_path_scan = AsyncMock()

    worker = PublishWorker(
        db=db,
        runner=AsyncSubprocessRunner(),
        publish_root=publish_root,
        folder_pattern="{artist} - {festival} ({year})",
        emby_client=emby_client,
    )

    await worker.publish(seg_id, festival="Coachella W1", venue="Mojave", year=2026)

    with db.session() as s:
        seg = s.get(Segment, seg_id)
        assert seg.status == "published"
        assert seg.error is None
        assert seg.emby_path is not None

        emby_dir = Path(seg.emby_path)
        assert emby_dir.is_dir()
        assert emby_dir.name == "Phoebe Bridgers - Coachella W1 (2026)"
        movies = list(emby_dir.glob("Phoebe Bridgers - Coachella W1 (2026).*"))
        media = [m for m in movies if m.suffix in (".mp4", ".mkv")]
        assert len(media) == 1
        assert (emby_dir / "movie.nfo").exists()
        assert (emby_dir / "poster.jpg").exists()
        assert (emby_dir / "fanart.jpg").exists()

    emby_client.trigger_path_scan.assert_awaited()


@pytest.mark.asyncio
async def test_publish_marks_failed_on_ffmpeg_error(db, tmp_path):
    seg_id = _seed(db, tmp_path / "nonexistent.mp4")

    worker = PublishWorker(
        db=db,
        runner=AsyncSubprocessRunner(),
        publish_root=tmp_path / "media",
        folder_pattern="{artist} ({year})",
        emby_client=MagicMock(trigger_path_scan=AsyncMock()),
    )

    with pytest.raises(RuntimeError):
        await worker.publish(seg_id, year=2026)

    with db.session() as s:
        seg = s.get(Segment, seg_id)
        assert seg.status == "publish_failed"
        assert seg.error is not None


@pytest.mark.asyncio
async def test_publish_404s_when_segment_missing(db, tmp_path):
    worker = PublishWorker(
        db=db,
        runner=AsyncSubprocessRunner(),
        publish_root=tmp_path,
        folder_pattern="{artist} ({year})",
        emby_client=MagicMock(trigger_path_scan=AsyncMock()),
    )
    with pytest.raises(LookupError):
        await worker.publish(9999, year=2026)
