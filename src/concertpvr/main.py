"""FastAPI app factory."""
from contextlib import asynccontextmanager

from fastapi import FastAPI

from concertpvr.config import Config
from concertpvr.db import Database


@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = Config()
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    app.state.config = cfg
    app.state.db = Database(cfg.db_url)

    # Ensure schema exists (on first boot — prod migrates via alembic at deploy)
    from concertpvr.models import Base
    Base.metadata.create_all(app.state.db.engine)

    yield

    app.state.db.engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(title="concertpvr", version="0.1.0", lifespan=lifespan)

    from concertpvr.api.health import router as health_router
    app.include_router(health_router, prefix="/api")

    from concertpvr.api.settings import router as settings_router
    app.include_router(settings_router, prefix="/api")

    return app
