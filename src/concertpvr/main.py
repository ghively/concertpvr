"""FastAPI app factory."""

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
        folder_pattern = (
            settings_row.folder_pattern if settings_row else "{artist} - {festival} ({year})"
        )

    app.state.emby_client = EmbyClient(emby_url, emby_key)

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
    app.state.scheduler.shutdown(wait=False)
    import asyncio as _asyncio

    if hasattr(app.state.pool, "wait_all") and _asyncio.iscoroutinefunction(
        app.state.pool.wait_all
    ):
        await app.state.pool.wait_all()
    app.state.db.engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(title="concertpvr", version="0.1.0", lifespan=lifespan)

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
