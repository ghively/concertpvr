"""End-to-end publish: cut clip → write metadata → move to Emby library → trigger scan."""

from __future__ import annotations

import datetime as _dt
from pathlib import Path

from concertpvr.db import Database
from concertpvr.emby import EmbyClient
from concertpvr.ffmpeg import Splitter
from concertpvr.metadata import MetadataBuilder, SegmentMeta
from concertpvr.models import ChannelWatcher, Recording, Segment, Stream
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
            seg_genres = seg.genres
            start_s = seg.start_s
            end_s = seg.end_s
            source_path = Path(rec.path)
            stream_kind = stream.kind if stream else "live"
            stream_title = stream.title if stream else ""
            stream_channel_name = stream.channel_name if stream else ""
            stream_original_upload_date = stream.original_upload_date if stream else None
            stream_description = stream.description if stream else None
            stream_watcher_id = stream.watcher_id if stream else None
            rec_started = rec.started_at
            rec_width = rec.width
            rec_height = rec.height

        try:
            # year: prefer original_upload_date for VODs, fallback to recording.started_at
            if year is None:
                if stream_original_upload_date:
                    year = stream_original_upload_date.year
                elif rec_started:
                    year = rec_started.year
                else:
                    year = _dt.datetime.now(_dt.UTC).year

            # date: same priority
            date_val: _dt.date | None = (
                stream_original_upload_date
                if stream_original_upload_date
                else rec_started.date() if rec_started else None
            )

            # festival default: per-kind dispatch
            if festival is None:
                if stream_kind == "video":
                    festival = stream_channel_name or None
                elif "—" in stream_title:
                    festival = stream_title.split("—")[0].strip()

            # venue: only for non-VOD streams with em-dash convention
            if venue is None and stream_kind != "video" and "—" in stream_title:
                venue = stream_title.split("—", 1)[1].strip()

            # channel token
            channel_val = stream_channel_name

            # Resolve genres: segment.genres > watcher.default_genres > []
            resolved_genres: list[str] = []
            if seg_genres:
                resolved_genres = [g.strip() for g in seg_genres.split(",") if g.strip()]
            elif stream_watcher_id is not None:
                with self._db.session() as s2:
                    watcher = s2.get(ChannelWatcher, stream_watcher_id)
                    if watcher and watcher.default_genres:
                        resolved_genres = [
                            g.strip()
                            for g in watcher.default_genres.split(",")
                            if g.strip()
                        ]

            # Plot: stream.description for VODs
            plot: str | None = None
            if stream_kind == "video" and stream_description:
                plot = stream_description

            try:
                folder_name = self._folder_pattern.format(
                    artist=artist,
                    festival=festival or "",
                    venue=venue or "",
                    year=year,
                    date=date_val.isoformat() if date_val else "",
                    title=title or artist,
                    channel=channel_val,
                ).strip()
            except (KeyError, IndexError) as e:
                raise ValueError(f"invalid folder_pattern token: {e}") from e
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
                date=date_val,
                duration_s=int(end_s - start_s),
                width=rec_width,
                height=rec_height,
                plot=plot,
                genres=resolved_genres,
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
