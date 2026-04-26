"""End-to-end publish: cut clip → write metadata → move to Emby library → trigger scan."""

from __future__ import annotations

import datetime as _dt
from pathlib import Path

from concertpvr.db import Database
from concertpvr.emby import EmbyClient
from concertpvr.ffmpeg import Splitter
from concertpvr.metadata import MetadataBuilder, SegmentMeta
from concertpvr.models import Recording, Segment, Stream
from concertpvr.process import ProcessRunner


class PublishWorker:
    def __init__(
        self,
        *,
        db: Database,
        runner: ProcessRunner,
        publish_root: Path,
        folder_pattern: str,
        emby_client: EmbyClient,
    ) -> None:
        self._db = db
        self._splitter = Splitter(runner)
        self._meta_builder = MetadataBuilder()
        self._publish_root = publish_root
        self._folder_pattern = folder_pattern
        self._emby = emby_client

    async def publish(
        self,
        segment_id: int,
        *,
        festival: str | None = None,
        venue: str | None = None,
        year: int | None = None,
    ) -> None:
        with self._db.session() as s:
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
            rec_started = rec.started_at
            rec_width = rec.width
            rec_height = rec.height

        try:
            if year is None:
                year = rec_started.year if rec_started else _dt.datetime.now().year
            if festival is None:
                festival = stream_title.split("—")[0].strip() if stream_title else None
            if venue is None and "—" in stream_title:
                venue = stream_title.split("—", 1)[1].strip()

            folder_name = self._folder_pattern.format(
                artist=artist,
                festival=festival or "",
                venue=venue or "",
                year=year,
                date=rec_started.date().isoformat() if rec_started else "",
                title=title or artist,
            ).strip()
            folder_name = " ".join(folder_name.split())

            target_dir = self._publish_root / folder_name
            target_dir.mkdir(parents=True, exist_ok=True)

            media_ext = source_path.suffix or ".mkv"
            media_out = target_dir / f"{folder_name}{media_ext}"

            await self._splitter.cut(
                source_path, media_out, start_s=float(start_s), end_s=float(end_s)
            )

            mid = float(start_s) + (float(end_s) - float(start_s)) / 2
            thumb = target_dir / "_thumb.jpg"
            await self._splitter.thumbnail(source_path, thumb, at_s=mid)

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
            nfo_path = self._meta_builder.build_nfo(meta, target_dir)
            poster_path = self._meta_builder.build_poster(meta, thumb, target_dir)
            self._meta_builder.build_fanart(thumb, target_dir)

            thumb.unlink(missing_ok=True)

            await self._emby.trigger_path_scan(str(target_dir))

            with self._db.session() as s:
                seg = s.get(Segment, segment_id)
                if seg is not None:
                    seg.status = "published"
                    seg.emby_path = str(target_dir)
                    seg.poster_path = str(poster_path)
                    seg.nfo_path = str(nfo_path)

        except Exception as e:
            with self._db.session() as s:
                seg = s.get(Segment, segment_id)
                if seg is not None:
                    seg.status = "publish_failed"
                    seg.error = f"{type(e).__name__}: {e}"
            raise
