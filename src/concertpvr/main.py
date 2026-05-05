"""FastAPI app factory."""

import logging as _logging_vod
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from concertpvr.config import Config
from concertpvr.db import Database


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
    cfg = Config()
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    cfg.buffer_dir.mkdir(parents=True, exist_ok=True)
    cfg.staging_dir.mkdir(parents=True, exist_ok=True)
    app.state.config = cfg
    app.state.db = Database(cfg.db_url)

    from concertpvr.models import Base

    Base.metadata.create_all(app.state.db.engine)

    # Orphan recovery: any recording stuck in 'recording' from a prior crash
    # is real (the pool is empty at startup). Mark interrupted.
    from concertpvr.orphan_recovery import mark_interrupted_on_startup

    mark_interrupted_on_startup(app.state.db)

    # VOD recovery: any download stuck in 'vod_downloading' from a prior crash
    # is real (the queue is empty at startup). Requeue it.
    from concertpvr.vod_recovery import mark_vod_downloads_interrupted_on_startup

    mark_vod_downloads_interrupted_on_startup(app.state.db)

    # Eagerly ensure a session_secret exists so token-issuance is never a race.
    from concertpvr.models import Settings as _SettingsModel
    from concertpvr.session import generate_secret as _generate_secret

    with app.state.db.session() as _s:
        _row = _s.get(_SettingsModel, 1)
        if _row is None:
            _row = _SettingsModel(id=1)
            _s.add(_row)
            _s.flush()
        if _row.session_secret is None:
            _row.session_secret = _generate_secret()

    from concertpvr.models import Settings as SettingsModel

    with app.state.db.session() as s:
        row = s.get(SettingsModel, 1)
        max_concurrent = row.max_concurrent_recordings if row else 4

    from concertpvr.buffer import BufferManager

    app.state.buffer = BufferManager(cfg.buffer_dir)

    from concertpvr.ws import Broadcaster

    app.state.broadcaster = Broadcaster()

    from concertpvr.pool import RecorderPool

    app.state.pool = RecorderPool(max_concurrent=max_concurrent)

    from concertpvr.scheduler import build_scheduler

    app.state.scheduler = build_scheduler(app.state.db)
    app.state.scheduler.start()

    from concertpvr.process import AsyncSubprocessRunner
    from concertpvr.schedule_manager import ScheduleManager
    from concertpvr.scheduled_runner import register_app, unregister_app

    app.state.schedule_manager = ScheduleManager(app.state.scheduler)
    register_app(
        db=app.state.db,
        pool=app.state.pool,
        buf=app.state.buffer,
        bc=app.state.broadcaster,
        runner_factory=AsyncSubprocessRunner,
        staging_root=cfg.staging_dir,
    )

    # VOD queue setup with real download handler.
    import datetime as _dt_vod
    from pathlib import Path as _PathVod

    from concertpvr.ffmpeg import Splitter as _Splitter
    from concertpvr.models import Recording as _Recording
    from concertpvr.models import Settings as _SettingsModel
    from concertpvr.models import Stream as _Stream
    from concertpvr.process import AsyncSubprocessRunner as _AsyncSubprocessRunner
    from concertpvr.recording_starter import _resolve_cookies_path as _resolve_cookies
    from concertpvr.vod_downloader import VodCancelled as _VodCancelled
    from concertpvr.vod_downloader import VodDownloader as _VodDownloader
    from concertpvr.vod_downloader import VodDownloadError as _VodDownloadError
    from concertpvr.vod_downloader import VodProgress as _VodProgress
    from concertpvr.vod_queue import VodQueue

    with app.state.db.session() as _s:
        _row = _s.get(_SettingsModel, 1)
        _vod_cap = _row.max_concurrent_vod_downloads if _row else 2

    async def _vod_handler(rec_id: int) -> None:
        with app.state.db.session() as s:
            rec = s.get(_Recording, rec_id)
            if rec is None:
                return
            stream = s.get(_Stream, rec.stream_id)
            if stream is None:
                rec.status = "vod_failed"
                rec.error = "stream missing"
                return
            url = stream.url
            output_path = _PathVod(rec.path)
            settings_row = s.get(_SettingsModel, 1)
            quality = settings_row.default_quality if settings_row else "bestvideo*+bestaudio/best"
            rec.status = "vod_downloading"

        cookies_path = _resolve_cookies(app.state.db)

        async def on_progress(p: _VodProgress) -> None:
            await app.state.broadcaster.publish(
                f"recordings.{rec_id}.progress",
                {
                    "pct": p.pct,
                    "bytes_total": p.bytes_total,
                    "bitrate_bps": p.bitrate_bps,
                    "eta_s": p.eta_s,
                },
            )

        downloader = _VodDownloader(runner=_AsyncSubprocessRunner())

        def _on_spawn(proc: object) -> None:
            from concertpvr.process import ManagedProcess

            if isinstance(proc, ManagedProcess):
                app.state.vod_queue.register_running(rec_id, proc)

        # DVR pull discriminator: the API endpoint that creates DVR-pull rows
        # uses a "dvr-" prefix on the output filename so the handler knows to
        # pass --live-from-start without needing a new column or table.
        is_dvr_pull = _PathVod(output_path).name.startswith("dvr-")

        try:
            await downloader.download(
                url=url,
                output_path=output_path,
                quality_format=quality,
                cookies_path=cookies_path,
                on_progress=on_progress,
                on_spawn=_on_spawn,
                live_from_start=is_dvr_pull,
            )
        except _VodCancelled:
            # Re-raise so the queue worker marks vod_cancelled and skips the
            # post-download bookkeeping (probe / auto-publish).
            app.state.vod_queue.unregister_running(rec_id)
            raise
        except _VodDownloadError as e:
            app.state.vod_queue.unregister_running(rec_id)
            with app.state.db.session() as s:
                rec = s.get(_Recording, rec_id)
                if rec is not None:
                    rec.status = "vod_failed"
                    rec.error = str(e)[:500]
            return
        finally:
            app.state.vod_queue.unregister_running(rec_id)

        # Resolve the actual on-disk filename. The Recording.path stored at
        # queue-time is a yt-dlp template like "vod-<id>.%(ext)s" — yt-dlp picks
        # the container based on the available formats and we don't know it
        # until after the download completes. Glob for the resolved file.
        resolved_path = output_path
        if "%" in str(output_path):
            template_str = str(output_path)
            stem = template_str[: template_str.index("%")]  # ".../vod-<id>."
            stem_path = _PathVod(stem)
            parent = stem_path.parent
            prefix = stem_path.name  # "vod-<id>."
            matches = sorted(parent.glob(f"{prefix}*"))
            # Prefer non-fragment / non-part files
            usable = [p for p in matches if p.is_file() and p.suffix not in {".part", ".ytdl"}]
            if usable:
                resolved_path = usable[0]
                logger_main = _logging_vod.getLogger(__name__)
                logger_main.info("vod_handler: resolved %s -> %s", output_path, resolved_path)

        # Run ffprobe to populate width/height/duration_s/size_bytes
        media_info = None
        try:
            splitter = _Splitter(runner=_AsyncSubprocessRunner())
            media_info = await splitter.probe(resolved_path)
        except Exception:  # noqa: BLE001
            logger_main = _logging_vod.getLogger(__name__)
            logger_main.warning(
                "ffprobe failed for recording %d at %s — leaving dimensions null",
                rec_id,
                resolved_path,
                exc_info=True,
            )

        with app.state.db.session() as s:
            rec = s.get(_Recording, rec_id)
            if rec is None:
                return
            rec.status = "complete"
            rec.ended_at = _dt_vod.datetime.now(_dt_vod.UTC)
            # Update path to resolved filename so downstream code (publisher,
            # source-delete) can find the file.
            rec.path = str(resolved_path)
            if resolved_path.exists():
                rec.size_bytes = resolved_path.stat().st_size
            if media_info is not None:
                rec.width = media_info.width
                rec.height = media_info.height
                rec.fps = int(media_info.fps)
                rec.duration_s = int(media_info.duration_s)

            auto_publish = rec.auto_publish_after_download

            from sqlalchemy import select

            from concertpvr.models import Segment

            segs = list(s.scalars(select(Segment).where(Segment.recording_id == rec_id)))
            publishable = [seg for seg in segs if seg.artist]

        if not auto_publish:
            return

        if not publishable:
            logger_main = _logging_vod.getLogger(__name__)
            logger_main.info(
                "auto_publish skipped for rec %d — no segments with non-null artist",
                rec_id,
            )
            return

        publisher = app.state.publisher_factory()
        for seg in publishable:
            try:
                await publisher.publish(seg.id)
            except Exception:  # noqa: BLE001
                logger_main = _logging_vod.getLogger(__name__)
                logger_main.exception("auto-publish failed for segment %d", seg.id)

    app.state.vod_queue = VodQueue(
        db=app.state.db,
        handler=_vod_handler,
        max_concurrent=_vod_cap,
    )
    await app.state.vod_queue.start_workers()
    await app.state.vod_queue.rehydrate_from_db()

    app.state.schedule_manager.rehydrate_from_db(app.state.db)

    from concertpvr.auto_segment import register as _register_auto_segment

    _register_auto_segment()

    from concertpvr.emby import EmbyClient
    from concertpvr.models import Settings as SettingsModel
    from concertpvr.publisher import PublishWorker

    with app.state.db.session() as s:
        settings_row = s.get(SettingsModel, 1)
        emby_url = settings_row.emby_url if settings_row else None
        emby_key = settings_row.emby_api_key if settings_row else None
        emby_local_prefix = settings_row.emby_path_local_prefix if settings_row else None
        emby_emby_prefix = settings_row.emby_path_emby_prefix if settings_row else None
        folder_pattern = (
            settings_row.folder_pattern if settings_row else "{artist} - {festival} ({year})"
        )

    app.state.emby_client = EmbyClient(
        emby_url,
        emby_key,
        local_prefix=emby_local_prefix,
        emby_prefix=emby_emby_prefix,
    )

    def _publisher_factory() -> PublishWorker:
        return PublishWorker(
            db=app.state.db,
            runner=AsyncSubprocessRunner(),
            publish_root=cfg.publish_dir,
            folder_pattern=folder_pattern,
            emby_client=app.state.emby_client,
        )

    app.state.publisher_factory = _publisher_factory

    from concertpvr.retention import build_prune_job

    app.state.scheduler.add_job(
        build_prune_job(app.state.db, app.state.buffer),
        "interval",
        minutes=5,
        id="buffer_retention_prune",
        replace_existing=True,
        jobstore="memory",
    )

    from concertpvr.channel_poller import poll_all_channel_watchers
    from concertpvr.models import Settings as _SettingsModel

    async def _channel_poll_job() -> None:
        with app.state.db.session() as s:
            settings_row = s.get(_SettingsModel, 1)
            quality = settings_row.default_quality if settings_row else "bestvideo*+bestaudio/best"
        await poll_all_channel_watchers(
            db=app.state.db,
            pool=app.state.pool,
            buf=app.state.buffer,
            bc=app.state.broadcaster,
            default_quality=quality,
            vod_queue=app.state.vod_queue,
            staging_root=cfg.staging_dir,
        )

    app.state.scheduler.add_job(
        _channel_poll_job,
        "interval",
        seconds=60,
        id="channel_poller",
        replace_existing=True,
        jobstore="memory",
    )

    yield

    unregister_app()
    if hasattr(app.state, "vod_queue"):
        await app.state.vod_queue.stop()
    app.state.scheduler.shutdown(wait=False)
    import asyncio as _asyncio

    if hasattr(app.state.pool, "wait_all") and _asyncio.iscoroutinefunction(
        app.state.pool.wait_all
    ):
        await app.state.pool.wait_all()
    app.state.db.engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(title="concertpvr", version="0.4.1", lifespan=lifespan)

    from concertpvr.api.auth import AuthMiddleware

    app.add_middleware(AuthMiddleware)

    from concertpvr.api.health import router as health_router
    from concertpvr.api.settings import router as settings_router
    from concertpvr.api.streams import router as streams_router

    app.include_router(health_router, prefix="/api")
    app.include_router(settings_router, prefix="/api")
    app.include_router(streams_router, prefix="/api")

    from concertpvr.api.recordings import router as recordings_router

    app.include_router(recordings_router, prefix="/api")

    from concertpvr.api.schedules import router as schedules_router

    app.include_router(schedules_router, prefix="/api")

    from concertpvr.api.segments import router as segments_router

    app.include_router(segments_router, prefix="/api")

    from concertpvr.api.setlists import router as setlists_router

    app.include_router(setlists_router, prefix="/api")

    from concertpvr.api.ws_progress import router as ws_router

    app.include_router(ws_router)  # no /api prefix — /ws/... is its own namespace

    from concertpvr.api.channel_watchers import router as channel_watchers_router

    app.include_router(channel_watchers_router, prefix="/api")

    from concertpvr.api.auth import router as auth_router

    app.include_router(auth_router, prefix="/api")

    from concertpvr.api import playlists as _playlists_api

    app.include_router(_playlists_api.router, prefix="/api")

    cfg = Config()
    if cfg.static_dir is not None and cfg.static_dir.is_dir():
        _mount_spa(app, cfg.static_dir)

    return app


def _mount_spa(app: FastAPI, static_dir: Path) -> None:
    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles

    assets_dir = static_dir / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    index = static_dir / "index.html"

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str) -> FileResponse:  # noqa: ARG001
        return FileResponse(index)
