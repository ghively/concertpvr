import datetime as dt
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from concertpvr.db import Database
from concertpvr.models import Base, ChannelWatcher, Recording, Segment, Stream
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

    with pytest.raises(ValueError):
        await worker.publish(seg_id, year=2026)

    with db.session() as s:
        seg = s.get(Segment, seg_id)
        assert seg.status == "publish_failed"
        assert (
            "folder_pattern" in (seg.error or "").lower() or "invalid" in (seg.error or "").lower()
        )


def _seed_vod(
    db: Database,
    source_path: Path,
    *,
    kind: str = "video",
    channel_name: str = "NPR Music",
    original_upload_date: dt.date | None = dt.date(2020, 9, 2),
    description: str | None = None,
    artist: str = "Khruangbin",
    genres: str | None = None,
    watcher_id: int | None = None,
) -> int:
    with db.session() as s:
        stream = Stream(
            kind=kind,
            youtube_id="vod-x",
            url="https://youtube.com/watch?v=vod-x",
            title="Khruangbin Full Concert",
            channel_name=channel_name,
            original_upload_date=original_upload_date,
            description=description,
            watcher_id=watcher_id,
        )
        s.add(stream)
        s.flush()
        rec = Recording(
            stream_id=stream.id,
            started_at=dt.datetime(2026, 4, 26, 10, 0, tzinfo=dt.UTC),
            path=str(source_path),
            is_buffer=False,
            status="complete",
        )
        s.add(rec)
        s.flush()
        seg = Segment(
            recording_id=rec.id,
            artist=artist,
            title="Full Set",
            start_s=0,
            end_s=2,
            source="manual",
            status="draft",
            genres=genres,
        )
        s.add(seg)
        s.flush()
        return seg.id


@pytest.mark.asyncio
async def test_publish_uses_upload_date_year_for_vod(db, tmp_path, fixture_video):
    """A VOD with original_upload_date in 2020 should produce {year}=2020 even
    if the recording was downloaded in 2026."""
    seg_id = _seed_vod(db, fixture_video, original_upload_date=dt.date(2020, 9, 2))

    worker = PublishWorker(
        db=db,
        runner=AsyncSubprocessRunner(),
        publish_root=tmp_path / "media",
        folder_pattern="{artist} ({year})",
        emby_client=MagicMock(trigger_path_scan=AsyncMock()),
    )
    await worker.publish(seg_id)

    with db.session() as s:
        seg = s.get(Segment, seg_id)
        assert seg.emby_path is not None
        assert "(2020)" in seg.emby_path


@pytest.mark.asyncio
async def test_publish_channel_token(db, tmp_path, fixture_video):
    """folder_pattern with {channel} resolves to stream.channel_name."""
    seg_id = _seed_vod(db, fixture_video, channel_name="NPR Music", artist="Khruangbin")

    worker = PublishWorker(
        db=db,
        runner=AsyncSubprocessRunner(),
        publish_root=tmp_path / "media",
        folder_pattern="{channel}/{artist}",
        emby_client=MagicMock(trigger_path_scan=AsyncMock()),
    )
    await worker.publish(seg_id)

    with db.session() as s:
        seg = s.get(Segment, seg_id)
        assert seg.emby_path is not None
        assert "NPR Music" in seg.emby_path
        assert "Khruangbin" in seg.emby_path


@pytest.mark.asyncio
async def test_publish_festival_defaults_to_channel_name_for_vod(db, tmp_path, fixture_video):
    """For kind=video, {festival} should resolve to channel_name."""
    seg_id = _seed_vod(db, fixture_video, channel_name="NPR Music", kind="video")

    worker = PublishWorker(
        db=db,
        runner=AsyncSubprocessRunner(),
        publish_root=tmp_path / "media",
        folder_pattern="{festival}",
        emby_client=MagicMock(trigger_path_scan=AsyncMock()),
    )
    await worker.publish(seg_id)

    with db.session() as s:
        seg = s.get(Segment, seg_id)
        assert seg.emby_path is not None
        assert "NPR Music" in seg.emby_path


@pytest.mark.asyncio
async def test_publish_genres_resolution_per_segment_overrides_watcher(db, tmp_path, fixture_video):
    """Segment.genres set → use that; watcher.default_genres is ignored."""
    with db.session() as s:
        watcher = ChannelWatcher(
            channel_url="https://youtube.com/@npmmusic",
            channel_name="NPR Music",
            default_genres="Indie,Folk",
        )
        s.add(watcher)
        s.flush()
        watcher_id = watcher.id

    seg_id = _seed_vod(db, fixture_video, genres="Rock", watcher_id=watcher_id)

    worker = PublishWorker(
        db=db,
        runner=AsyncSubprocessRunner(),
        publish_root=tmp_path / "media",
        folder_pattern="{artist} ({year})",
        emby_client=MagicMock(trigger_path_scan=AsyncMock()),
    )
    await worker.publish(seg_id)

    with db.session() as s:
        seg = s.get(Segment, seg_id)
        assert seg.nfo_path is not None
        nfo_text = Path(seg.nfo_path).read_text(encoding="utf-8")
        assert "<genre>Rock</genre>" in nfo_text
        assert "<genre>Indie</genre>" not in nfo_text
        assert "<genre>Folk</genre>" not in nfo_text


@pytest.mark.asyncio
async def test_publish_genres_falls_back_to_watcher_default_when_segment_null(
    db, tmp_path, fixture_video
):
    """Segment.genres=None → inherit watcher.default_genres."""
    with db.session() as s:
        watcher = ChannelWatcher(
            channel_url="https://youtube.com/@npmmusic2",
            channel_name="NPR Music",
            default_genres="Indie,Folk",
        )
        s.add(watcher)
        s.flush()
        watcher_id = watcher.id

    seg_id = _seed_vod(db, fixture_video, genres=None, watcher_id=watcher_id)

    worker = PublishWorker(
        db=db,
        runner=AsyncSubprocessRunner(),
        publish_root=tmp_path / "media",
        folder_pattern="{artist} ({year})",
        emby_client=MagicMock(trigger_path_scan=AsyncMock()),
    )
    await worker.publish(seg_id)

    with db.session() as s:
        seg = s.get(Segment, seg_id)
        assert seg.nfo_path is not None
        nfo_text = Path(seg.nfo_path).read_text(encoding="utf-8")
        assert "<genre>Indie</genre>" in nfo_text
        assert "<genre>Folk</genre>" in nfo_text


@pytest.mark.asyncio
async def test_publish_plot_set_from_description_for_vods(db, tmp_path, fixture_video):
    """stream.kind=video with description → NFO has <plot> element."""
    description = "Khruangbin performing live at NPR's Tiny Desk."
    seg_id = _seed_vod(db, fixture_video, description=description, kind="video")

    worker = PublishWorker(
        db=db,
        runner=AsyncSubprocessRunner(),
        publish_root=tmp_path / "media",
        folder_pattern="{artist} ({year})",
        emby_client=MagicMock(trigger_path_scan=AsyncMock()),
    )
    await worker.publish(seg_id)

    with db.session() as s:
        seg = s.get(Segment, seg_id)
        assert seg.nfo_path is not None
        nfo_text = Path(seg.nfo_path).read_text(encoding="utf-8")
        assert "<plot>" in nfo_text
        assert "Tiny Desk" in nfo_text


# ---------------------------------------------------------------------------
# Auto-delete source tests
# ---------------------------------------------------------------------------


def _seed_with_settings(db: Database, source_path: Path, *, auto_delete: bool) -> int:
    """Seed a single-segment recording with global auto_delete_source_after_publish setting."""
    from concertpvr.models import Settings

    with db.session() as s:
        settings = s.get(Settings, 1)
        if settings is None:
            settings = Settings(id=1)
            s.add(settings)
        settings.auto_delete_source_after_publish = auto_delete
        s.flush()

    return _seed(db, source_path)


@pytest.mark.asyncio
async def test_publish_auto_deletes_source_when_settings_say_so(db, tmp_path, fixture_video):
    """When settings.auto_delete=True and only segment is published, source file is removed."""
    # Use a copy of the fixture so we can delete it without affecting other tests
    source = tmp_path / "source.mp4"
    import shutil

    shutil.copy(str(fixture_video), str(source))

    seg_id = _seed_with_settings(db, source, auto_delete=True)

    worker = PublishWorker(
        db=db,
        runner=AsyncSubprocessRunner(),
        publish_root=tmp_path / "media",
        folder_pattern="{artist} ({year})",
        emby_client=MagicMock(trigger_path_scan=AsyncMock()),
    )
    await worker.publish(seg_id, year=2026)

    assert not source.exists(), "source file should have been auto-deleted"

    with db.session() as s:
        seg = s.get(Segment, seg_id)
        assert seg is not None
        rec = s.get(Recording, seg.recording_id)
        assert rec is not None
        assert rec.source_deleted is True


@pytest.mark.asyncio
async def test_publish_does_not_delete_source_when_some_segments_unpublished(
    db, tmp_path, fixture_video
):
    """With 2 segments and only 1 published, source should be preserved."""
    source = tmp_path / "source2.mp4"
    import shutil

    shutil.copy(str(fixture_video), str(source))

    from concertpvr.models import Settings

    with db.session() as s:
        settings = s.get(Settings, 1)
        if settings is None:
            settings = Settings(id=1)
            s.add(settings)
        settings.auto_delete_source_after_publish = True
        s.flush()

    # Seed with 2 segments
    with db.session() as s:
        stream = Stream(
            kind="live",
            youtube_id="two-segs",
            url="u",
            title="T — Stage",
            channel_name="T",
        )
        s.add(stream)
        s.flush()
        rec = Recording(
            stream_id=stream.id,
            started_at=dt.datetime(2026, 4, 12, 14, 0, tzinfo=dt.UTC),
            path=str(source),
            is_buffer=False,
            status="complete",
        )
        s.add(rec)
        s.flush()
        seg1 = Segment(
            recording_id=rec.id,
            artist="Artist A",
            title="Song A",
            start_s=0,
            end_s=1,
            source="manual",
            status="draft",
        )
        seg2 = Segment(
            recording_id=rec.id,
            artist="Artist B",
            title="Song B",
            start_s=1,
            end_s=2,
            source="manual",
            status="draft",
        )
        s.add(seg1)
        s.add(seg2)
        s.flush()
        seg1_id = seg1.id

    worker = PublishWorker(
        db=db,
        runner=AsyncSubprocessRunner(),
        publish_root=tmp_path / "media",
        folder_pattern="{artist} ({year})",
        emby_client=MagicMock(trigger_path_scan=AsyncMock()),
    )
    # Only publish seg1; seg2 remains draft
    await worker.publish(seg1_id, year=2026)

    assert source.exists(), "source should NOT be deleted while seg2 is still draft"

    with db.session() as s:
        seg = s.get(Segment, seg1_id)
        assert seg is not None
        rec = s.get(Recording, seg.recording_id)
        assert rec is not None
        assert rec.source_deleted is False


@pytest.mark.asyncio
async def test_publish_watcher_pref_overrides_settings(db, tmp_path, fixture_video):
    """watcher.auto_delete=False wins even when settings.auto_delete=True."""
    source = tmp_path / "source3.mp4"
    import shutil

    shutil.copy(str(fixture_video), str(source))

    from concertpvr.models import Settings

    with db.session() as s:
        settings = s.get(Settings, 1)
        if settings is None:
            settings = Settings(id=1)
            s.add(settings)
        settings.auto_delete_source_after_publish = True
        s.flush()

        watcher = ChannelWatcher(
            channel_url="https://youtube.com/@override",
            channel_name="Override Channel",
            auto_delete_source_after_publish=False,
        )
        s.add(watcher)
        s.flush()
        watcher_id = watcher.id

    seg_id = _seed_vod(db, source, watcher_id=watcher_id)

    worker = PublishWorker(
        db=db,
        runner=AsyncSubprocessRunner(),
        publish_root=tmp_path / "media",
        folder_pattern="{artist} ({year})",
        emby_client=MagicMock(trigger_path_scan=AsyncMock()),
    )
    await worker.publish(seg_id)

    assert source.exists(), (
        "source should NOT be deleted because watcher pref=False overrides settings"
    )

    with db.session() as s:
        seg = s.get(Segment, seg_id)
        assert seg is not None
        rec = s.get(Recording, seg.recording_id)
        assert rec is not None
        assert rec.source_deleted is False
