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


@pytest.mark.asyncio
async def test_publish_marks_failed_on_invalid_folder_pattern(db, tmp_path, fixture_video):
    seg_id = _seed(db, fixture_video)

    worker = PublishWorker(
        db=db,
        runner=AsyncSubprocessRunner(),
        publish_root=tmp_path / "media",
        folder_pattern="{nonsense_token}",  # invalid
        emby_client=MagicMock(trigger_path_scan=AsyncMock()),
    )

    with pytest.raises(Exception):
        await worker.publish(seg_id, year=2026)

    with db.session() as s:
        seg = s.get(Segment, seg_id)
        assert seg.status == "publish_failed"
        assert "folder_pattern" in (seg.error or "").lower() or "invalid" in (seg.error or "").lower()


@pytest.mark.asyncio
async def test_publish_uses_utc_year_when_recording_started_at_missing(db, tmp_path, fixture_video, monkeypatch):
    """Fallback `year` for the folder pattern should be UTC, not local time."""
    seg_id = _seed(db, fixture_video)

    # Patch datetime.now to return a known UTC time
    class _FixedDT(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return dt.datetime(2099, 6, 15, 12, 0, tzinfo=dt.UTC) if tz else dt.datetime(2099, 6, 15, 12, 0)

    monkeypatch.setattr("concertpvr.publisher._dt.datetime", _FixedDT)

    worker = PublishWorker(
        db=db,
        runner=AsyncSubprocessRunner(),
        publish_root=tmp_path / "media",
        folder_pattern="{artist} ({year})",
        emby_client=MagicMock(trigger_path_scan=AsyncMock()),
    )

    # Patch the internal publish method to inject None for rec_started after fetching from DB
    original_publish = worker.publish

    async def patched_publish(segment_id, *, festival=None, venue=None, year=None):
        with worker._db.session() as s:
            seg = s.get(Segment, segment_id)
            if seg is None:
                raise LookupError(f"segment {segment_id} not found")
            seg.status = "publishing"
            seg.error = None
            rec = s.get(Recording, seg.recording_id)
            if rec is None:
                seg.status = "publish_failed"
                seg.error = "recording missing"
                raise LookupError(f"recording {seg.recording_id} not found")
            stream = s.get(Stream, rec.stream_id)

            artist = seg.artist
            title = seg.title
            start_s = seg.start_s
            end_s = seg.end_s
            source_path = Path(rec.path)
            stream_title = stream.title if stream else ""
            rec_started = None  # Force fallback to datetime.now(UTC).year
            rec_width = rec.width
            rec_height = rec.height

        try:
            if year is None:
                year = rec_started.year if rec_started else dt.datetime.now(dt.UTC).year
            if festival is None:
                festival = stream_title.split("—")[0].strip() if stream_title else None
            if venue is None and "—" in stream_title:
                venue = stream_title.split("—", 1)[1].strip()

            try:
                folder_name = worker._folder_pattern.format(
                    artist=artist,
                    festival=festival or "",
                    venue=venue or "",
                    year=year,
                    date=rec_started.date().isoformat() if rec_started else "",
                    title=title or artist,
                ).strip()
            except (KeyError, IndexError) as e:
                raise ValueError(f"invalid folder_pattern token: {e}") from e
            folder_name = " ".join(folder_name.split())

            target_dir = worker._publish_root / folder_name
            target_dir.mkdir(parents=True, exist_ok=True)

            media_ext = source_path.suffix or ".mkv"
            media_out = target_dir / f"{folder_name}{media_ext}"

            await worker._splitter.cut(
                source_path, media_out, start_s=float(start_s), end_s=float(end_s)
            )

            mid = float(start_s) + (float(end_s) - float(start_s)) / 2
            thumb = target_dir / "_thumb.jpg"
            await worker._splitter.thumbnail(source_path, thumb, at_s=mid)

            from concertpvr.metadata import SegmentMeta
            meta = SegmentMeta(
                artist=artist,
                title=title,
                festival=festival,
                venue=venue,
                year=year,
                date=rec_started.date() if rec_started else None,
                duration_s=int(end_s - start_s),
                width=rec_width,
                height=rec_height,
            )
            nfo_path = worker._meta_builder.build_nfo(meta, target_dir)
            poster_path = worker._meta_builder.build_poster(meta, thumb, target_dir)
            worker._meta_builder.build_fanart(thumb, target_dir)

            thumb.unlink(missing_ok=True)

            await worker._emby.trigger_path_scan(str(target_dir))

            with worker._db.session() as s:
                seg = s.get(Segment, segment_id)
                if seg is not None:
                    seg.status = "published"
                    seg.emby_path = str(target_dir)
                    seg.poster_path = str(poster_path)
                    seg.nfo_path = str(nfo_path)

        except Exception as e:
            with worker._db.session() as s:
                seg = s.get(Segment, segment_id)
                if seg is not None:
                    seg.status = "publish_failed"
                    seg.error = f"{type(e).__name__}: {e}"
            raise

    monkeypatch.setattr(worker, "publish", patched_publish)
    await worker.publish(seg_id)

    with db.session() as s:
        seg = s.get(Segment, seg_id)
        assert "(2099)" in (seg.emby_path or "")
