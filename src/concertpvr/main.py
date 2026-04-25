"""FastAPI app factory."""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from concertpvr.config import Config
from concertpvr.db import Database


@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = Config()
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    app.state.config = cfg
    app.state.db = Database(cfg.db_url)

    from concertpvr.models import Base
    Base.metadata.create_all(app.state.db.engine)

    yield

    app.state.db.engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(title="concertpvr", version="0.1.0", lifespan=lifespan)

    from concertpvr.api.health import router as health_router
    from concertpvr.api.settings import router as settings_router
    app.include_router(health_router, prefix="/api")
    app.include_router(settings_router, prefix="/api")

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
    async def spa_fallback(full_path: str):  # noqa: ARG001
        return FileResponse(index)
