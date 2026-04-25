# concertpvr — Phase 1: Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish the project scaffolding, database, FastAPI shell, React shell, and Docker packaging so the app boots, shows an empty Dashboard with a working navbar, and has a functional Settings page. No recording yet — that's Phase 2.

**Architecture:** Python 3.12 FastAPI backend with SQLAlchemy + Alembic + SQLite. React 18 + Vite + TypeScript frontend served as static assets from the same FastAPI app. Single multi-stage Docker image. No authentication in Phase 1 (LAN-only during development; auth added in Phase 6).

**Tech Stack:** FastAPI, Uvicorn, Pydantic v2, SQLAlchemy 2.0, Alembic, APScheduler (installed but not yet used), React 18, TypeScript, Vite, Tailwind, shadcn/ui, TanStack Query, React Router v6.

**Spec reference:** `docs/superpowers/specs/2026-04-24-concertpvr-design.md` — sections 3 (Architecture), 4 (Tech Stack), 5 (Data Model — `settings` table only for Phase 1), 11 (Deployment).

---

## File structure created by this phase

```
concertpvr/
├── pyproject.toml
├── alembic.ini
├── alembic/
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
│       └── 0001_initial.py
├── src/
│   └── concertpvr/
│       ├── __init__.py
│       ├── __main__.py           # python -m concertpvr
│       ├── config.py             # env var loader (Pydantic Settings)
│       ├── db.py                 # SQLAlchemy engine + session
│       ├── models.py             # SQLAlchemy Base + Settings model
│       ├── schemas.py            # Pydantic request/response models
│       ├── main.py               # FastAPI app factory
│       ├── deps.py               # FastAPI dependencies (get_db etc.)
│       └── api/
│           ├── __init__.py
│           ├── health.py         # /api/healthz
│           └── settings.py       # /api/settings GET/PATCH
├── tests/
│   ├── __init__.py
│   ├── conftest.py               # shared pytest fixtures
│   ├── test_config.py
│   ├── test_db.py
│   ├── test_health.py
│   └── test_settings_api.py
├── frontend/
│   ├── package.json
│   ├── tsconfig.json
│   ├── tsconfig.node.json
│   ├── vite.config.ts
│   ├── tailwind.config.js
│   ├── postcss.config.js
│   ├── components.json           # shadcn config
│   ├── index.html
│   ├── src/
│   │   ├── main.tsx
│   │   ├── App.tsx
│   │   ├── lib/
│   │   │   ├── api.ts
│   │   │   ├── query.ts
│   │   │   └── utils.ts          # shadcn's cn() helper
│   │   ├── components/
│   │   │   ├── Layout.tsx
│   │   │   └── ui/               # shadcn primitives go here
│   │   ├── pages/
│   │   │   ├── Dashboard.tsx
│   │   │   ├── Streams.tsx
│   │   │   ├── Schedule.tsx
│   │   │   ├── Library.tsx
│   │   │   ├── Watchers.tsx
│   │   │   └── Settings.tsx
│   │   └── styles/
│   │       └── globals.css
│   └── public/
├── Dockerfile
├── docker-compose.yml
├── .dockerignore
└── README.md
```

---

## Task 1: Python project scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `src/concertpvr/__init__.py`
- Create: `tests/__init__.py`

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[project]
name = "concertpvr"
version = "0.1.0"
description = "YouTube concert and livestream PVR with Emby integration"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.32.0",
    "pydantic>=2.9.0",
    "pydantic-settings>=2.6.0",
    "sqlalchemy>=2.0.35",
    "alembic>=1.13.3",
    "apscheduler>=3.10.4",
    "argon2-cffi>=23.1.0",
    "yt-dlp>=2024.10.22",
    "httpx>=0.27.2",
    "python-multipart>=0.0.12",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.3.3",
    "pytest-asyncio>=0.24.0",
    "pytest-cov>=5.0.0",
    "ruff>=0.7.0",
    "mypy>=1.13.0",
    "httpx>=0.27.2",
]

[build-system]
requires = ["setuptools>=75"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
addopts = "-q --strict-markers"

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "W", "I", "B", "UP", "SIM"]
ignore = ["E501"]  # line length handled by formatter

[tool.mypy]
python_version = "3.12"
strict = true
packages = ["concertpvr"]
```

- [ ] **Step 2: Create empty package init files**

```python
# src/concertpvr/__init__.py
"""concertpvr — YouTube concert PVR."""
__version__ = "0.1.0"
```

```python
# tests/__init__.py
```

- [ ] **Step 3: Install dev dependencies**

Run (from project root):
```bash
python -m venv .venv
.venv/Scripts/activate   # Windows
pip install -e ".[dev]"
```

Expected: installs without errors. `pip list` shows fastapi, pytest, ruff, mypy, sqlalchemy, yt-dlp.

- [ ] **Step 4: Verify tooling works**

Run:
```bash
python -c "import concertpvr; print(concertpvr.__version__)"
pytest --version
ruff --version
mypy --version
```

Expected: `0.1.0`, then version numbers for pytest/ruff/mypy.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml src/concertpvr/__init__.py tests/__init__.py
git commit -m "feat: python project scaffolding with fastapi and dev tooling"
```

---

## Task 2: Config loader

**Files:**
- Create: `src/concertpvr/config.py`
- Create: `tests/test_config.py`

The config module loads runtime configuration from environment variables (prefix `CPVR_`) with sensible defaults. This is the *deployment-time* config (paths, bind address). Per-install config (Emby URL, retention days) lives in the `settings` DB table added in Task 5.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config.py
from pathlib import Path

from concertpvr.config import Config


def test_defaults_when_no_env(monkeypatch, tmp_path):
    for k in list(__import__("os").environ):
        if k.startswith("CPVR_"):
            monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("CPVR_DATA_DIR", str(tmp_path))
    cfg = Config()
    assert cfg.data_dir == tmp_path
    assert cfg.db_path == tmp_path / "metadata.db"
    assert cfg.host == "0.0.0.0"
    assert cfg.port == 8787


def test_overrides_from_env(monkeypatch, tmp_path):
    monkeypatch.setenv("CPVR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CPVR_PUBLISH_DIR", "/srv/concerts")
    monkeypatch.setenv("CPVR_PORT", "9000")
    cfg = Config()
    assert cfg.publish_dir == Path("/srv/concerts")
    assert cfg.port == 9000


def test_data_dir_required(monkeypatch):
    monkeypatch.delenv("CPVR_DATA_DIR", raising=False)
    try:
        Config()
    except Exception as e:
        assert "data_dir" in str(e).lower() or "CPVR_DATA_DIR" in str(e)
    else:
        raise AssertionError("expected Config() to raise without CPVR_DATA_DIR")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_config.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'concertpvr.config'`.

- [ ] **Step 3: Implement config**

```python
# src/concertpvr/config.py
"""Deployment-time configuration loaded from environment variables."""
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    """Environment-driven runtime config. Prefix: CPVR_."""

    model_config = SettingsConfigDict(env_prefix="CPVR_", extra="ignore")

    data_dir: Path = Field(..., description="Host data directory (mounted into container)")
    publish_dir: Path = Field(
        default=Path("/media/concerts"),
        description="Where published segments land (Emby movies library)",
    )

    host: str = "0.0.0.0"
    port: int = 8787

    @property
    def db_path(self) -> Path:
        return self.data_dir / "metadata.db"

    @property
    def db_url(self) -> str:
        return f"sqlite:///{self.db_path}"

    @property
    def buffer_dir(self) -> Path:
        return self.data_dir / "buffer"

    @property
    def staging_dir(self) -> Path:
        return self.data_dir / "staging"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_config.py -v
```
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/concertpvr/config.py tests/test_config.py
git commit -m "feat(config): env-driven runtime config with Pydantic Settings"
```

---

## Task 3: Database engine + session

**Files:**
- Create: `src/concertpvr/db.py`
- Create: `tests/conftest.py`
- Create: `tests/test_db.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_db.py
from sqlalchemy import text

from concertpvr.db import Database


def test_database_connects_and_pings(tmp_path):
    db = Database(f"sqlite:///{tmp_path / 'test.db'}")
    with db.session() as s:
        result = s.execute(text("SELECT 1")).scalar_one()
        assert result == 1


def test_database_session_is_transactional(tmp_path):
    """Each session() context manager is its own transaction."""
    db = Database(f"sqlite:///{tmp_path / 'test.db'}")
    with db.session() as s:
        s.execute(text("CREATE TABLE t (x INTEGER)"))
        s.execute(text("INSERT INTO t VALUES (1)"))

    with db.session() as s:
        count = s.execute(text("SELECT COUNT(*) FROM t")).scalar_one()
        assert count == 1
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/test_db.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'concertpvr.db'`.

- [ ] **Step 3: Implement Database**

```python
# src/concertpvr/db.py
"""SQLAlchemy engine + session factory."""
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker


class Database:
    """Wraps a SQLAlchemy engine + session factory for an app install."""

    def __init__(self, url: str) -> None:
        self.engine: Engine = create_engine(
            url,
            # SQLite + multi-thread (FastAPI threadpool) needs this:
            connect_args={"check_same_thread": False} if url.startswith("sqlite") else {},
            future=True,
        )
        self._Session = sessionmaker(self.engine, expire_on_commit=False, future=True)

    @contextmanager
    def session(self) -> Iterator[Session]:
        """Open a session; commit on clean exit, rollback on exception."""
        s = self._Session()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()
```

- [ ] **Step 4: Add shared test fixtures**

```python
# tests/conftest.py
"""Shared pytest fixtures."""
from pathlib import Path

import pytest

from concertpvr.db import Database


@pytest.fixture
def tmp_db(tmp_path: Path) -> Database:
    """A throw-away SQLite database per test."""
    return Database(f"sqlite:///{tmp_path / 'test.db'}")
```

- [ ] **Step 5: Run tests**

```bash
pytest tests/test_db.py -v
```
Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
git add src/concertpvr/db.py tests/conftest.py tests/test_db.py
git commit -m "feat(db): sqlalchemy engine + session context manager"
```

---

## Task 4: `Settings` model

**Files:**
- Create: `src/concertpvr/models.py`
- Modify: `tests/test_db.py` (add model round-trip test)

Phase 1 defines only the `settings` singleton table. Phases 2–5 add `streams`, `recordings`, `segments`, etc.

- [ ] **Step 1: Add failing test for model round-trip**

Append to `tests/test_db.py`:

```python
from concertpvr.models import Base, Settings


def test_settings_model_round_trip(tmp_db):
    Base.metadata.create_all(tmp_db.engine)

    with tmp_db.session() as s:
        s.add(Settings(id=1, emby_url="http://emby:8096", folder_pattern="{artist}"))

    with tmp_db.session() as s:
        row = s.get(Settings, 1)
        assert row is not None
        assert row.emby_url == "http://emby:8096"
        assert row.folder_pattern == "{artist}"
        assert row.default_quality == "bestvideo*+bestaudio/best"  # default
        assert row.max_concurrent_recordings == 4  # default
```

- [ ] **Step 2: Run — should fail**

```bash
pytest tests/test_db.py::test_settings_model_round_trip -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'concertpvr.models'`.

- [ ] **Step 3: Implement models**

```python
# src/concertpvr/models.py
"""SQLAlchemy models.

Phase 1 defines only the `settings` singleton. Future phases append tables:
  - Phase 2: streams, watch_subscriptions, recordings
  - Phase 3: schedules
  - Phase 4: segments, setlists
  - Phase 5: channel_watchers
"""
from __future__ import annotations

from sqlalchemy import String, Integer, Boolean
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Settings(Base):
    """Singleton row — always id=1."""

    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)

    # Emby integration (nullable until configured)
    emby_url: Mapped[str | None] = mapped_column(String, nullable=True)
    emby_api_key: Mapped[str | None] = mapped_column(String, nullable=True)
    emby_library_path: Mapped[str | None] = mapped_column(String, nullable=True)

    # Publish naming
    folder_pattern: Mapped[str] = mapped_column(
        String, default="{artist} - {festival} ({year})", nullable=False
    )

    # Recording defaults
    default_quality: Mapped[str] = mapped_column(
        String, default="bestvideo*+bestaudio/best", nullable=False
    )
    default_retention_days: Mapped[int] = mapped_column(Integer, default=7, nullable=False)
    max_concurrent_recordings: Mapped[int] = mapped_column(Integer, default=4, nullable=False)
    auto_prune_when_full: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # yt-dlp cookies file (nullable)
    yt_dlp_cookies_path: Mapped[str | None] = mapped_column(String, nullable=True)
```

- [ ] **Step 4: Run**

```bash
pytest tests/test_db.py -v
```
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/concertpvr/models.py tests/test_db.py
git commit -m "feat(models): settings singleton table"
```

---

## Task 5: Alembic setup + initial migration

**Files:**
- Create: `alembic.ini`
- Create: `alembic/env.py`
- Create: `alembic/script.py.mako`
- Create: `alembic/versions/0001_initial.py`
- Create: `tests/test_migrations.py`

- [ ] **Step 1: Scaffold alembic**

Run:
```bash
alembic init -t generic alembic
```
This creates `alembic.ini` + `alembic/` directory. The default `env.py` is offline-only; we'll replace it.

- [ ] **Step 2: Edit `alembic.ini`**

Change these two lines in `alembic.ini`:

```ini
# leave sqlalchemy.url blank — env.py pulls it from concertpvr.config
sqlalchemy.url =
```

and

```ini
script_location = alembic
```

(Remove any `%(here)s/` prefix Alembic added.)

- [ ] **Step 3: Replace `alembic/env.py`**

```python
# alembic/env.py
"""Alembic migration env — pulls DB URL from concertpvr.config."""
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from concertpvr.config import Config
from concertpvr.models import Base

config = context.config

# Inject sqlalchemy.url from our app config at runtime.
config.set_main_option("sqlalchemy.url", Config().db_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

- [ ] **Step 4: Write the initial migration**

Delete any auto-generated file in `alembic/versions/` and create:

```python
# alembic/versions/0001_initial.py
"""initial schema: settings singleton

Revision ID: 0001_initial
Revises:
Create Date: 2026-04-24
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("emby_url", sa.String(), nullable=True),
        sa.Column("emby_api_key", sa.String(), nullable=True),
        sa.Column("emby_library_path", sa.String(), nullable=True),
        sa.Column("folder_pattern", sa.String(), nullable=False,
                  server_default="{artist} - {festival} ({year})"),
        sa.Column("default_quality", sa.String(), nullable=False,
                  server_default="bestvideo*+bestaudio/best"),
        sa.Column("default_retention_days", sa.Integer(), nullable=False, server_default="7"),
        sa.Column("max_concurrent_recordings", sa.Integer(), nullable=False, server_default="4"),
        sa.Column("auto_prune_when_full", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("yt_dlp_cookies_path", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("settings")
```

- [ ] **Step 5: Test upgrade/downgrade round-trip**

```python
# tests/test_migrations.py
import subprocess
from pathlib import Path


def test_migration_upgrade_then_downgrade(tmp_path, monkeypatch):
    monkeypatch.setenv("CPVR_DATA_DIR", str(tmp_path))

    # upgrade to head
    r = subprocess.run(["alembic", "upgrade", "head"], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr

    # settings table should exist
    db = tmp_path / "metadata.db"
    assert db.exists()

    # downgrade
    r = subprocess.run(["alembic", "downgrade", "base"], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
```

- [ ] **Step 6: Run**

```bash
pytest tests/test_migrations.py -v
```
Expected: 1 passed.

- [ ] **Step 7: Commit**

```bash
git add alembic.ini alembic/ tests/test_migrations.py
git commit -m "feat(db): alembic initial migration for settings table"
```

---

## Task 6: FastAPI app factory + /api/healthz

**Files:**
- Create: `src/concertpvr/main.py`
- Create: `src/concertpvr/deps.py`
- Create: `src/concertpvr/api/__init__.py`
- Create: `src/concertpvr/api/health.py`
- Create: `src/concertpvr/__main__.py`
- Create: `tests/test_health.py`

**Important:** `app` is NOT instantiated at module level in `main.py`. Doing so would run `Config()` at import time, which fails before pytest fixtures set `CPVR_DATA_DIR`. Instead, `uvicorn` and `__main__.py` use **factory mode** (`--factory` / `factory=True`) to call `create_app()` at startup. The `get_db` dependency lives in `deps.py` to avoid circular imports with router modules.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_health.py
import pytest
from fastapi.testclient import TestClient

from concertpvr.main import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CPVR_DATA_DIR", str(tmp_path))
    app = create_app()
    with TestClient(app) as c:
        yield c


def test_healthz_returns_ok(client):
    r = client.get("/api/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_healthz_db_reachable(client):
    """Health endpoint should also verify DB is reachable."""
    r = client.get("/api/healthz?deep=true")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["db"] == "reachable"
```

- [ ] **Step 2: Run — fails**

```bash
pytest tests/test_health.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'concertpvr.main'`.

- [ ] **Step 3: Implement `deps.py`**

```python
# src/concertpvr/deps.py
"""FastAPI dependency callables."""
from fastapi import Request

from concertpvr.db import Database


def get_db(request: Request) -> Database:
    """Access the per-app Database from app state."""
    return request.app.state.db
```

- [ ] **Step 4: Implement the api package and health router**

```python
# src/concertpvr/api/__init__.py
```

```python
# src/concertpvr/api/health.py
"""Liveness probe."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy import text

from concertpvr.db import Database
from concertpvr.deps import get_db

router = APIRouter()


@router.get("/healthz")
def healthz(deep: bool = Query(False), db: Database = Depends(get_db)) -> dict[str, str]:
    body = {"status": "ok"}
    if deep:
        with db.session() as s:
            s.execute(text("SELECT 1"))
        body["db"] = "reachable"
    return body
```

- [ ] **Step 5: Implement the app factory**

Note: no module-level `app = create_app()`. Uvicorn and `__main__.py` both use factory mode.

```python
# src/concertpvr/main.py
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

    return app
```

- [ ] **Step 6: Entry point for `python -m concertpvr`**

```python
# src/concertpvr/__main__.py
"""Entry point: `python -m concertpvr`."""
import uvicorn

from concertpvr.config import Config

if __name__ == "__main__":
    cfg = Config()
    uvicorn.run(
        "concertpvr.main:create_app",
        factory=True,
        host=cfg.host,
        port=cfg.port,
        reload=False,
    )
```

- [ ] **Step 7: Run tests**

```bash
pytest tests/test_health.py -v
```
Expected: 2 passed.

- [ ] **Step 8: Smoke-test the server**

In one shell:
```bash
export CPVR_DATA_DIR=/tmp/cpvr-dev
python -m concertpvr
```

In another shell:
```bash
curl http://localhost:8787/api/healthz
```
Expected: `{"status":"ok"}`. Kill the server with Ctrl-C.

- [ ] **Step 9: Commit**

```bash
git add src/concertpvr/main.py src/concertpvr/deps.py src/concertpvr/__main__.py src/concertpvr/api/ tests/test_health.py
git commit -m "feat(api): fastapi app factory with healthz endpoint"
```

---

## Task 7: Settings GET/PATCH API

**Files:**
- Create: `src/concertpvr/schemas.py`
- Create: `src/concertpvr/api/settings.py`
- Modify: `src/concertpvr/main.py` (register router)
- Create: `tests/test_settings_api.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_settings_api.py
import pytest
from fastapi.testclient import TestClient

from concertpvr.main import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CPVR_DATA_DIR", str(tmp_path))
    with TestClient(create_app()) as c:
        yield c


def test_get_settings_returns_defaults_on_fresh_install(client):
    r = client.get("/api/settings")
    assert r.status_code == 200
    body = r.json()
    assert body["folder_pattern"] == "{artist} - {festival} ({year})"
    assert body["default_quality"] == "bestvideo*+bestaudio/best"
    assert body["max_concurrent_recordings"] == 4
    assert body["emby_url"] is None


def test_patch_settings_updates_values(client):
    r = client.patch("/api/settings", json={
        "emby_url": "http://emby.local:8096",
        "max_concurrent_recordings": 2,
    })
    assert r.status_code == 200
    body = r.json()
    assert body["emby_url"] == "http://emby.local:8096"
    assert body["max_concurrent_recordings"] == 2
    # unchanged fields kept their defaults
    assert body["default_quality"] == "bestvideo*+bestaudio/best"


def test_patch_settings_rejects_unknown_fields(client):
    r = client.patch("/api/settings", json={"nonexistent_field": "x"})
    assert r.status_code == 422


def test_patch_settings_validates_types(client):
    r = client.patch("/api/settings", json={"max_concurrent_recordings": "not-a-number"})
    assert r.status_code == 422
```

- [ ] **Step 2: Run — fails**

```bash
pytest tests/test_settings_api.py -v
```
Expected: 4 failures (module not found / 404).

- [ ] **Step 3: Pydantic schemas**

```python
# src/concertpvr/schemas.py
"""Pydantic request/response models."""
from pydantic import BaseModel, ConfigDict


class SettingsRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    emby_url: str | None
    emby_api_key: str | None
    emby_library_path: str | None
    folder_pattern: str
    default_quality: str
    default_retention_days: int
    max_concurrent_recordings: int
    auto_prune_when_full: bool
    yt_dlp_cookies_path: str | None


class SettingsPatch(BaseModel):
    """All fields optional — PATCH semantics. Unknown fields rejected."""
    model_config = ConfigDict(extra="forbid")

    emby_url: str | None = None
    emby_api_key: str | None = None
    emby_library_path: str | None = None
    folder_pattern: str | None = None
    default_quality: str | None = None
    default_retention_days: int | None = None
    max_concurrent_recordings: int | None = None
    auto_prune_when_full: bool | None = None
    yt_dlp_cookies_path: str | None = None
```

- [ ] **Step 4: Implement settings router**

```python
# src/concertpvr/api/settings.py
"""Settings singleton CRUD."""
from fastapi import APIRouter, Depends

from concertpvr.db import Database
from concertpvr.deps import get_db
from concertpvr.models import Settings
from concertpvr.schemas import SettingsPatch, SettingsRead

router = APIRouter()


def _get_or_create(db: Database) -> Settings:
    with db.session() as s:
        row = s.get(Settings, 1)
        if row is None:
            row = Settings(id=1)
            s.add(row)
            s.flush()
        s.expunge(row)
    return row


@router.get("/settings", response_model=SettingsRead)
def read_settings(db: Database = Depends(get_db)) -> Settings:
    return _get_or_create(db)


@router.patch("/settings", response_model=SettingsRead)
def patch_settings(patch: SettingsPatch, db: Database = Depends(get_db)) -> Settings:
    updates = patch.model_dump(exclude_unset=True)
    with db.session() as s:
        row = s.get(Settings, 1)
        if row is None:
            row = Settings(id=1)
            s.add(row)
            s.flush()
        for k, v in updates.items():
            setattr(row, k, v)
        s.flush()
        s.refresh(row)
        s.expunge(row)
    return row
```

- [ ] **Step 5: Register the router**

In `src/concertpvr/main.py`, inside `create_app()`, after `app.include_router(health_router, prefix="/api")` add:

```python
    from concertpvr.api.settings import router as settings_router
    app.include_router(settings_router, prefix="/api")
```

- [ ] **Step 6: Run**

```bash
pytest tests/test_settings_api.py -v
```
Expected: 4 passed.

- [ ] **Step 7: Commit**

```bash
git add src/concertpvr/schemas.py src/concertpvr/api/settings.py src/concertpvr/main.py tests/test_settings_api.py
git commit -m "feat(api): settings singleton GET/PATCH endpoints"
```

---

## Task 8: Static file mount + SPA fallback

**Files:**
- Modify: `src/concertpvr/main.py`
- Create: `tests/test_static.py`

The frontend build output lands at `/app/static/` inside the container (Dockerfile in Task 18). For local dev, we'll point Vite at the FastAPI server in later tasks and just need the mount contract working.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_static.py
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from concertpvr.main import create_app


@pytest.fixture
def client_with_static(tmp_path, monkeypatch):
    monkeypatch.setenv("CPVR_DATA_DIR", str(tmp_path))

    static_dir = tmp_path / "static"
    static_dir.mkdir()
    (static_dir / "index.html").write_text("<html><body>concertpvr spa</body></html>")
    (static_dir / "assets").mkdir()
    (static_dir / "assets" / "app.js").write_text("// bundled spa")

    monkeypatch.setenv("CPVR_STATIC_DIR", str(static_dir))

    with TestClient(create_app()) as c:
        yield c


def test_static_asset_served(client_with_static):
    r = client_with_static.get("/assets/app.js")
    assert r.status_code == 200
    assert "bundled spa" in r.text


def test_spa_fallback_serves_index_for_unknown_route(client_with_static):
    """Client-side routing: /dashboard, /streams etc. should return index.html."""
    r = client_with_static.get("/dashboard")
    assert r.status_code == 200
    assert "concertpvr spa" in r.text


def test_api_routes_still_work(client_with_static):
    r = client_with_static.get("/api/healthz")
    assert r.status_code == 200


def test_missing_static_dir_does_not_crash(tmp_path, monkeypatch):
    """During dev or before frontend build, missing static dir is OK."""
    monkeypatch.setenv("CPVR_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("CPVR_STATIC_DIR", raising=False)
    with TestClient(create_app()) as c:
        r = c.get("/api/healthz")
        assert r.status_code == 200
```

- [ ] **Step 2: Add `static_dir` to Config**

In `src/concertpvr/config.py`, add to `Config`:

```python
    static_dir: Path | None = None  # path to built React SPA; None in dev
```

- [ ] **Step 3: Wire static mount in main.py**

Update `create_app()` in `src/concertpvr/main.py`:

```python
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


def _mount_spa(app: FastAPI, static_dir: "Path") -> None:
    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles

    assets_dir = static_dir / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    index = static_dir / "index.html"

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str):  # noqa: ARG001
        return FileResponse(index)
```

Add at top of file:
```python
from pathlib import Path
```

- [ ] **Step 4: Run**

```bash
pytest tests/test_static.py -v
```
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/concertpvr/main.py src/concertpvr/config.py tests/test_static.py
git commit -m "feat(api): static SPA mount with client-side routing fallback"
```

---

## Task 9: Frontend scaffolding (Vite + TS + Tailwind)

**Files:**
- Create: `frontend/package.json`, `tsconfig.json`, `tsconfig.node.json`, `vite.config.ts`
- Create: `frontend/tailwind.config.js`, `postcss.config.js`
- Create: `frontend/index.html`
- Create: `frontend/src/main.tsx`, `App.tsx`
- Create: `frontend/src/styles/globals.css`

- [ ] **Step 1: Create `frontend/package.json`**

```json
{
  "name": "concertpvr-frontend",
  "version": "0.1.0",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "preview": "vite preview",
    "lint": "eslint src --ext .ts,.tsx",
    "typecheck": "tsc -b --noEmit",
    "test": "vitest"
  },
  "dependencies": {
    "react": "^18.3.1",
    "react-dom": "^18.3.1",
    "react-router-dom": "^6.27.0",
    "@tanstack/react-query": "^5.59.0",
    "clsx": "^2.1.1",
    "tailwind-merge": "^2.5.4",
    "lucide-react": "^0.453.0"
  },
  "devDependencies": {
    "@types/node": "^22.7.5",
    "@types/react": "^18.3.11",
    "@types/react-dom": "^18.3.0",
    "@vitejs/plugin-react": "^4.3.2",
    "autoprefixer": "^10.4.20",
    "postcss": "^8.4.47",
    "tailwindcss": "^3.4.14",
    "typescript": "^5.6.3",
    "vite": "^5.4.9",
    "vitest": "^2.1.3",
    "@testing-library/react": "^16.0.1",
    "@testing-library/jest-dom": "^6.6.1",
    "jsdom": "^25.0.1",
    "eslint": "^9.12.0"
  }
}
```

- [ ] **Step 2: TS configs**

```json
// frontend/tsconfig.json
{
  "compilerOptions": {
    "target": "ES2022",
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": false,
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true,
    "jsx": "react-jsx",
    "esModuleInterop": true,
    "skipLibCheck": true,
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "baseUrl": ".",
    "paths": { "@/*": ["./src/*"] }
  },
  "include": ["src"],
  "references": [{ "path": "./tsconfig.node.json" }]
}
```

```json
// frontend/tsconfig.node.json
{
  "compilerOptions": {
    "composite": true,
    "skipLibCheck": true,
    "module": "ESNext",
    "moduleResolution": "bundler",
    "allowSyntheticDefaultImports": true,
    "strict": true
  },
  "include": ["vite.config.ts"]
}
```

- [ ] **Step 3: Vite config**

```typescript
// frontend/vite.config.ts
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "./src") },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": "http://localhost:8787",
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
});
```

- [ ] **Step 4: Tailwind + PostCSS**

```javascript
// frontend/tailwind.config.js
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Editorial accent palette on a Studio Dark shell.
        terracotta: { DEFAULT: "#d4664a", dim: "#a84e37" },
        sage: { DEFAULT: "#7ab078", dim: "#55805a" },
        amber: { DEFAULT: "#d4a35a", dim: "#9f7a3e" },
        mauve: { DEFAULT: "#9b7dd4", dim: "#6d56a0" },
        surface: {
          0: "#0c0e12",
          1: "#14171c",
          2: "#1a1d24",
          3: "#232730",
        },
        border: {
          DEFAULT: "#2a2e36",
          strong: "#353a46",
        },
        ink: {
          DEFAULT: "#e8eaee",
          dim: "#9aa0ab",
          faint: "#6b7280",
        },
      },
      fontFamily: {
        mono: ["JetBrains Mono", "ui-monospace", "Menlo", "monospace"],
      },
    },
  },
  plugins: [],
};
```

```javascript
// frontend/postcss.config.js
export default {
  plugins: { tailwindcss: {}, autoprefixer: {} },
};
```

- [ ] **Step 5: Global CSS**

```css
/* frontend/src/styles/globals.css */
@tailwind base;
@tailwind components;
@tailwind utilities;

html, body, #root {
  height: 100%;
  background: theme("colors.surface.0");
  color: theme("colors.ink.DEFAULT");
  font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
  font-size: 13px;
  line-height: 1.5;
}

* {
  border-color: theme("colors.border.DEFAULT");
}
```

- [ ] **Step 6: Entry point**

```html
<!-- frontend/index.html -->
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>concertpvr</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

```typescript
// frontend/src/main.tsx
import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import App from "./App";
import "./styles/globals.css";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { refetchOnWindowFocus: false, retry: 1 },
  },
});

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <QueryClientProvider client={queryClient}>
        <App />
      </QueryClientProvider>
    </BrowserRouter>
  </React.StrictMode>,
);
```

```typescript
// frontend/src/App.tsx
export default function App() {
  return (
    <div className="p-8">
      <h1 className="text-xl text-terracotta">◉ concertpvr</h1>
      <p className="text-ink-dim mt-2">Phase 1 — foundation booting.</p>
    </div>
  );
}
```

- [ ] **Step 7: Install frontend deps and smoke test**

```bash
cd frontend
npm install
npm run dev
```
Expected: Vite dev server starts on http://localhost:5173. Opening the URL shows "◉ concertpvr" in terracotta with the subtitle. Kill with Ctrl-C.

```bash
npm run typecheck
npm run build
```
Expected: TypeScript clean, `frontend/dist/` created with `index.html` + `assets/`.

- [ ] **Step 8: Commit**

```bash
git add frontend/package.json frontend/package-lock.json frontend/tsconfig.json frontend/tsconfig.node.json frontend/vite.config.ts frontend/tailwind.config.js frontend/postcss.config.js frontend/index.html frontend/src/
git commit -m "feat(frontend): vite+react+tailwind scaffolding with editorial palette"
```

---

## Task 10: shadcn/ui init + utility helpers

**Files:**
- Create: `frontend/src/lib/utils.ts`
- Create: `frontend/components.json`
- Create: `frontend/src/components/ui/button.tsx`
- Create: `frontend/src/components/ui/card.tsx`
- Create: `frontend/src/components/ui/input.tsx`

shadcn/ui is a "copy components into your project" library — not an npm package. We set up the prerequisites, then paste three primitives we'll need in Phase 1 (Button, Card, Input). Later phases add more.

- [ ] **Step 1: utils.ts**

```typescript
// frontend/src/lib/utils.ts
import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
```

- [ ] **Step 2: components.json (tells shadcn CLI where things go, for future use)**

```json
{
  "$schema": "https://ui.shadcn.com/schema.json",
  "style": "default",
  "rsc": false,
  "tsx": true,
  "tailwind": {
    "config": "tailwind.config.js",
    "css": "src/styles/globals.css",
    "baseColor": "neutral",
    "cssVariables": false
  },
  "aliases": {
    "components": "@/components",
    "utils": "@/lib/utils",
    "ui": "@/components/ui"
  }
}
```

- [ ] **Step 3: Button primitive (custom tailwind'd — matches Studio Dark / editorial palette)**

```typescript
// frontend/src/components/ui/button.tsx
import * as React from "react";
import { cn } from "@/lib/utils";

type Variant = "default" | "primary" | "ghost";

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
}

const base =
  "inline-flex items-center gap-1.5 rounded px-3 py-1.5 text-xs font-medium transition-colors " +
  "border disabled:opacity-50 disabled:cursor-not-allowed";

const variants: Record<Variant, string> = {
  default: "bg-surface-3 border-border-strong text-ink hover:border-ink-faint",
  primary: "bg-terracotta hover:bg-terracotta-dim border-terracotta-dim text-white",
  ghost: "bg-transparent border-transparent text-ink-dim hover:text-ink",
};

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ variant = "default", className, ...rest }, ref) => (
    <button ref={ref} className={cn(base, variants[variant], className)} {...rest} />
  ),
);
Button.displayName = "Button";
```

- [ ] **Step 4: Card primitive**

```typescript
// frontend/src/components/ui/card.tsx
import * as React from "react";
import { cn } from "@/lib/utils";

export const Card = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...rest }, ref) => (
    <div
      ref={ref}
      className={cn("rounded-md border border-border bg-surface-1 p-4", className)}
      {...rest}
    />
  ),
);
Card.displayName = "Card";

export const CardLabel = ({ children, className }: { children: React.ReactNode; className?: string }) => (
  <div className={cn("text-[10px] uppercase tracking-wider text-ink-faint", className)}>
    {children}
  </div>
);
```

- [ ] **Step 5: Input primitive**

```typescript
// frontend/src/components/ui/input.tsx
import * as React from "react";
import { cn } from "@/lib/utils";

export const Input = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(
  ({ className, ...rest }, ref) => (
    <input
      ref={ref}
      className={cn(
        "w-full rounded border border-border-strong bg-surface-0 px-2.5 py-1.5",
        "text-xs text-ink placeholder:text-ink-faint",
        "focus:outline-none focus:border-terracotta",
        className,
      )}
      {...rest}
    />
  ),
);
Input.displayName = "Input";
```

- [ ] **Step 6: Smoke test — render a button in App.tsx**

Update `frontend/src/App.tsx` to verify primitives work:

```typescript
// frontend/src/App.tsx
import { Button } from "@/components/ui/button";
import { Card, CardLabel } from "@/components/ui/card";

export default function App() {
  return (
    <div className="p-8 space-y-4">
      <h1 className="text-xl font-semibold text-terracotta">◉ concertpvr</h1>
      <p className="text-ink-dim">Phase 1 — foundation booting.</p>
      <div className="flex gap-2">
        <Button variant="primary">Primary</Button>
        <Button>Default</Button>
        <Button variant="ghost">Ghost</Button>
      </div>
      <Card>
        <CardLabel>Sample Card</CardLabel>
        <div className="text-sm mt-1">If this renders in editorial colors, shadcn setup works.</div>
      </Card>
    </div>
  );
}
```

- [ ] **Step 7: Typecheck and build**

```bash
cd frontend
npm run typecheck
npm run build
```
Expected: clean + `dist/` regenerated.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/lib/utils.ts frontend/components.json frontend/src/components/ui/ frontend/src/App.tsx
git commit -m "feat(frontend): shadcn-style button/card/input primitives with editorial theme"
```

---

## Task 11: API client + React Query wiring

**Files:**
- Create: `frontend/src/lib/api.ts`
- Create: `frontend/src/lib/query.ts`

- [ ] **Step 1: api.ts — typed fetch wrapper**

```typescript
// frontend/src/lib/api.ts
export class ApiError extends Error {
  constructor(public status: number, public body: unknown, message?: string) {
    super(message ?? `API error: ${status}`);
    this.name = "ApiError";
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method,
    headers: body ? { "content-type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
    credentials: "include",
  });
  const text = await res.text();
  const json = text ? (() => { try { return JSON.parse(text); } catch { return text; } })() : null;
  if (!res.ok) throw new ApiError(res.status, json);
  return json as T;
}

export const api = {
  get: <T>(p: string) => request<T>("GET", p),
  post: <T>(p: string, b?: unknown) => request<T>("POST", p, b),
  patch: <T>(p: string, b?: unknown) => request<T>("PATCH", p, b),
  delete: <T>(p: string) => request<T>("DELETE", p),
};

// ───────── typed resource hooks live here (one file per group added later) ─────────

export type Settings = {
  emby_url: string | null;
  emby_api_key: string | null;
  emby_library_path: string | null;
  folder_pattern: string;
  default_quality: string;
  default_retention_days: number;
  max_concurrent_recordings: number;
  auto_prune_when_full: boolean;
  yt_dlp_cookies_path: string | null;
};

export type SettingsPatch = Partial<Settings>;

export const settingsApi = {
  get: () => api.get<Settings>("/api/settings"),
  patch: (p: SettingsPatch) => api.patch<Settings>("/api/settings", p),
};
```

- [ ] **Step 2: query.ts — typed React Query hooks**

```typescript
// frontend/src/lib/query.ts
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { settingsApi, type Settings, type SettingsPatch } from "./api";

export const keys = {
  settings: ["settings"] as const,
};

export function useSettings() {
  return useQuery<Settings>({
    queryKey: keys.settings,
    queryFn: () => settingsApi.get(),
  });
}

export function useUpdateSettings() {
  const qc = useQueryClient();
  return useMutation<Settings, Error, SettingsPatch>({
    mutationFn: (patch) => settingsApi.patch(patch),
    onSuccess: (data) => qc.setQueryData(keys.settings, data),
  });
}
```

- [ ] **Step 3: Typecheck**

```bash
cd frontend
npm run typecheck
```
Expected: clean.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/api.ts frontend/src/lib/query.ts
git commit -m "feat(frontend): api client + react-query hooks for settings"
```

---

## Task 12: Layout + navigation

**Files:**
- Create: `frontend/src/components/Layout.tsx`

- [ ] **Step 1: Layout component**

```typescript
// frontend/src/components/Layout.tsx
import { NavLink, Outlet } from "react-router-dom";
import { cn } from "@/lib/utils";

const navItems = [
  { to: "/", label: "Dashboard", end: true },
  { to: "/streams", label: "Streams" },
  { to: "/schedule", label: "Schedule" },
  { to: "/library", label: "Library" },
  { to: "/watchers", label: "Watchers" },
];

export default function Layout() {
  return (
    <div className="min-h-screen flex flex-col bg-surface-0">
      <header className="flex items-center gap-4 px-4 py-2.5 bg-surface-1 border-b border-border">
        <span className="font-bold tracking-wide">
          <span className="text-terracotta">◉</span> concertpvr
        </span>
        <nav className="flex gap-1">
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                cn(
                  "px-2.5 py-1 rounded text-xs text-ink-dim hover:text-ink",
                  isActive && "bg-terracotta/10 text-terracotta",
                )
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="flex-1" />
        <NavLink
          to="/settings"
          className={({ isActive }) =>
            cn("text-xs text-ink-dim hover:text-ink", isActive && "text-terracotta")
          }
        >
          ⚙ Settings
        </NavLink>
      </header>
      <main className="flex-1 p-4">
        <Outlet />
      </main>
    </div>
  );
}
```

- [ ] **Step 2: Typecheck**

```bash
cd frontend && npm run typecheck
```
Expected: clean.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/Layout.tsx
git commit -m "feat(frontend): top-nav layout with editorial palette"
```

---

## Task 13: Page stubs + routing

**Files:**
- Create: `frontend/src/pages/Dashboard.tsx`
- Create: `frontend/src/pages/Streams.tsx`
- Create: `frontend/src/pages/Schedule.tsx`
- Create: `frontend/src/pages/Library.tsx`
- Create: `frontend/src/pages/Watchers.tsx`
- Create: `frontend/src/pages/Settings.tsx` (functional — consumes the Settings API)
- Modify: `frontend/src/App.tsx` (router)

- [ ] **Step 1: Reusable "coming in phase N" placeholder**

```typescript
// frontend/src/pages/Dashboard.tsx
export default function Dashboard() {
  return (
    <div>
      <h2 className="text-lg font-semibold">Dashboard</h2>
      <p className="text-ink-dim text-xs mt-1">
        Live recordings + today's schedule — lands in Phase 2.
      </p>
    </div>
  );
}
```

```typescript
// frontend/src/pages/Streams.tsx
export default function Streams() {
  return (
    <div>
      <h2 className="text-lg font-semibold">Streams</h2>
      <p className="text-ink-dim text-xs mt-1">Tracked YouTube sources — Phase 2.</p>
    </div>
  );
}
```

```typescript
// frontend/src/pages/Schedule.tsx
export default function Schedule() {
  return (
    <div>
      <h2 className="text-lg font-semibold">Schedule</h2>
      <p className="text-ink-dim text-xs mt-1">Weekly calendar — Phase 3.</p>
    </div>
  );
}
```

```typescript
// frontend/src/pages/Library.tsx
export default function Library() {
  return (
    <div>
      <h2 className="text-lg font-semibold">Library</h2>
      <p className="text-ink-dim text-xs mt-1">Published concerts — Phase 4.</p>
    </div>
  );
}
```

```typescript
// frontend/src/pages/Watchers.tsx
export default function Watchers() {
  return (
    <div>
      <h2 className="text-lg font-semibold">Channel Watchers</h2>
      <p className="text-ink-dim text-xs mt-1">Auto-record subscriptions — Phase 5.</p>
    </div>
  );
}
```

- [ ] **Step 2: Settings page — the one real Phase 1 screen**

```typescript
// frontend/src/pages/Settings.tsx
import { useState, useEffect } from "react";
import { useSettings, useUpdateSettings } from "@/lib/query";
import { Button } from "@/components/ui/button";
import { Card, CardLabel } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import type { SettingsPatch } from "@/lib/api";

export default function SettingsPage() {
  const { data, isLoading, error } = useSettings();
  const update = useUpdateSettings();

  const [form, setForm] = useState<SettingsPatch>({});
  useEffect(() => {
    if (data) setForm({});
  }, [data]);

  if (isLoading) return <div className="text-ink-dim text-xs">Loading…</div>;
  if (error || !data) return <div className="text-terracotta text-xs">Failed to load settings.</div>;

  const field = <K extends keyof SettingsPatch>(k: K) => (v: SettingsPatch[K]) =>
    setForm((f) => ({ ...f, [k]: v }));

  const merged = { ...data, ...form };

  const save = () => {
    const dirty: SettingsPatch = {};
    for (const k of Object.keys(form) as (keyof SettingsPatch)[]) {
      if (form[k] !== data[k]) (dirty as Record<string, unknown>)[k as string] = form[k];
    }
    if (Object.keys(dirty).length > 0) update.mutate(dirty);
  };

  return (
    <div className="max-w-2xl">
      <h2 className="text-lg font-semibold mb-4">Settings</h2>

      <Card className="mb-4 space-y-3">
        <CardLabel>Emby Integration</CardLabel>
        <Labeled label="Emby server URL" help="Used to trigger library refresh after publish">
          <Input
            className="font-mono"
            value={merged.emby_url ?? ""}
            onChange={(e) => field("emby_url")(e.target.value || null)}
            placeholder="http://192.168.1.10:8096"
          />
        </Labeled>
        <Labeled label="API key">
          <Input
            type="password"
            className="font-mono"
            value={merged.emby_api_key ?? ""}
            onChange={(e) => field("emby_api_key")(e.target.value || null)}
          />
        </Labeled>
        <Labeled label="Movies library path (Emby's view)">
          <Input
            className="font-mono"
            value={merged.emby_library_path ?? ""}
            onChange={(e) => field("emby_library_path")(e.target.value || null)}
            placeholder="/media/concerts"
          />
        </Labeled>
      </Card>

      <Card className="mb-4 space-y-3">
        <CardLabel>Naming</CardLabel>
        <Labeled
          label="Folder pattern"
          help="Tokens: {artist} {festival} {venue} {year} {date} {title}"
        >
          <Input
            className="font-mono"
            value={merged.folder_pattern}
            onChange={(e) => field("folder_pattern")(e.target.value)}
          />
        </Labeled>
      </Card>

      <Card className="mb-4 space-y-3">
        <CardLabel>Recording defaults</CardLabel>
        <Labeled label="Default quality (yt-dlp format selector)">
          <Input
            className="font-mono"
            value={merged.default_quality}
            onChange={(e) => field("default_quality")(e.target.value)}
          />
        </Labeled>
        <Labeled label="Default retention (days)">
          <Input
            type="number"
            className="font-mono"
            value={merged.default_retention_days}
            onChange={(e) => field("default_retention_days")(Number(e.target.value))}
          />
        </Labeled>
        <Labeled label="Max concurrent recordings">
          <Input
            type="number"
            className="font-mono"
            value={merged.max_concurrent_recordings}
            onChange={(e) => field("max_concurrent_recordings")(Number(e.target.value))}
          />
        </Labeled>
      </Card>

      <div className="flex gap-2">
        <Button variant="primary" onClick={save} disabled={update.isPending}>
          {update.isPending ? "Saving…" : "Save"}
        </Button>
        {update.isSuccess && <span className="text-sage text-xs self-center">Saved ✓</span>}
        {update.isError && (
          <span className="text-terracotta text-xs self-center">Error: {update.error.message}</span>
        )}
      </div>
    </div>
  );
}

function Labeled({
  label,
  help,
  children,
}: {
  label: string;
  help?: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <label className="block text-[11px] text-ink-dim mb-1">{label}</label>
      {children}
      {help && <div className="text-[10px] text-ink-faint mt-1">{help}</div>}
    </div>
  );
}
```

- [ ] **Step 3: Router**

```typescript
// frontend/src/App.tsx
import { Routes, Route } from "react-router-dom";
import Layout from "@/components/Layout";
import Dashboard from "@/pages/Dashboard";
import Streams from "@/pages/Streams";
import Schedule from "@/pages/Schedule";
import Library from "@/pages/Library";
import Watchers from "@/pages/Watchers";
import Settings from "@/pages/Settings";

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Layout />}>
        <Route index element={<Dashboard />} />
        <Route path="streams" element={<Streams />} />
        <Route path="schedule" element={<Schedule />} />
        <Route path="library" element={<Library />} />
        <Route path="watchers" element={<Watchers />} />
        <Route path="settings" element={<Settings />} />
      </Route>
    </Routes>
  );
}
```

- [ ] **Step 4: End-to-end smoke test**

Run the backend:
```bash
CPVR_DATA_DIR=/tmp/cpvr-dev python -m concertpvr
```

Run the frontend:
```bash
cd frontend && npm run dev
```

Open `http://localhost:5173`. You should see:
- Top nav with Dashboard / Streams / Schedule / Library / Watchers + Settings link on the right
- Clicking each nav item changes the page content
- Settings page loads values from `/api/settings` (visible via Network tab)
- Editing a field and clicking Save sends a PATCH; "Saved ✓" appears

Kill both servers.

- [ ] **Step 5: Typecheck**

```bash
cd frontend && npm run typecheck
```
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/App.tsx frontend/src/pages/
git commit -m "feat(frontend): router + page stubs + functional settings page"
```

---

## Task 14: Multi-stage Dockerfile

**Files:**
- Create: `Dockerfile`
- Create: `.dockerignore`

- [ ] **Step 1: Dockerfile**

```dockerfile
# syntax=docker/dockerfile:1.7

# ─── stage 1: build the react bundle ───
FROM node:20-alpine AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ─── stage 2: python runtime ───
FROM python:3.12-slim AS runtime

RUN apt-get update && apt-get install -y --no-install-recommends \
      ffmpeg \
      ca-certificates \
      curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml ./
RUN pip install --no-cache-dir .

COPY src/ ./src/
COPY alembic.ini ./
COPY alembic/ ./alembic/

COPY --from=frontend /app/frontend/dist /app/static

ENV CPVR_DATA_DIR=/data
ENV CPVR_PUBLISH_DIR=/media/concerts
ENV CPVR_STATIC_DIR=/app/static
ENV CPVR_HOST=0.0.0.0
ENV CPVR_PORT=8787

VOLUME ["/data", "/media/concerts"]
EXPOSE 8787

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD curl -f http://localhost:8787/api/healthz || exit 1

CMD ["sh", "-c", "alembic upgrade head && python -m concertpvr"]
```

- [ ] **Step 2: .dockerignore**

```
.git/
.venv/
venv/
__pycache__/
*.pyc
.pytest_cache/
.mypy_cache/
.ruff_cache/
node_modules/
frontend/dist/
frontend/node_modules/
.superpowers/
docs/
*.md
.env*
.idea/
.vscode/
```

- [ ] **Step 3: Build and smoke-test**

```bash
docker build -t concertpvr:phase1 .
mkdir -p /tmp/cpvr-docker-data
docker run --rm -p 8787:8787 -v /tmp/cpvr-docker-data:/data concertpvr:phase1 &
sleep 5
curl http://localhost:8787/api/healthz
# → {"status":"ok"}
curl http://localhost:8787/api/settings
# → {"emby_url":null, ...}
curl http://localhost:8787/
# → <html> with "concertpvr" (SPA index)
docker stop $(docker ps -q --filter ancestor=concertpvr:phase1)
```

- [ ] **Step 4: Commit**

```bash
git add Dockerfile .dockerignore
git commit -m "feat(docker): multi-stage image with ffmpeg + built react bundle"
```

---

## Task 15: docker-compose.yml + README

**Files:**
- Create: `docker-compose.yml`
- Create: `README.md`

- [ ] **Step 1: docker-compose.yml**

```yaml
services:
  concertpvr:
    build: .
    image: concertpvr:latest
    container_name: concertpvr
    ports:
      - "8787:8787"
    volumes:
      - /volume1/concertpvr:/data
      - /volume1/media/concerts:/media/concerts
    environment:
      CPVR_DATA_DIR: /data
      CPVR_PUBLISH_DIR: /media/concerts
      CPVR_STATIC_DIR: /app/static
    restart: unless-stopped
```

- [ ] **Step 2: README**

```markdown
# concertpvr

YouTube concert & livestream PVR with Emby integration. Runs on Synology NAS via Docker.

## Status

**Phase 1 (Foundation) complete.** App boots, nav works, Settings page saves. No recording yet.

See the full roadmap and spec:
- Design: `docs/superpowers/specs/2026-04-24-concertpvr-design.md`
- Phase plans: `docs/superpowers/plans/`

## Local development

### Backend (one shell)

```bash
python -m venv .venv
source .venv/bin/activate   # or .venv/Scripts/activate on Windows
pip install -e ".[dev]"

export CPVR_DATA_DIR=/tmp/cpvr-dev   # Linux/Mac
# or: set CPVR_DATA_DIR=C:\tmp\cpvr-dev   (Windows cmd)

alembic upgrade head
python -m concertpvr
```

Backend now at http://localhost:8787.

### Frontend (another shell)

```bash
cd frontend
npm install
npm run dev
```

Frontend at http://localhost:5173, proxying `/api/*` to the backend.

## Tests

```bash
pytest                     # backend
cd frontend && npm test    # frontend (Vitest)
```

## Production (Docker)

```bash
docker compose up -d --build
```

The compose file expects:
- `/volume1/concertpvr` — runtime data (DB, buffer, staging, logs)
- `/volume1/media/concerts` — Emby movies library target

Adjust paths as needed for your Synology.

## License

TBD.
```

- [ ] **Step 3: Commit**

```bash
git add docker-compose.yml README.md
git commit -m "docs: compose example + dev setup readme"
```

---

## Task 16: Phase 1 wrap-up — lint, type, test sweep

- [ ] **Step 1: Backend lint + type + test clean run**

```bash
ruff check src/ tests/
ruff format --check src/ tests/
mypy src/
pytest -q
```
Expected: all clean. Fix anything that fails.

- [ ] **Step 2: Frontend typecheck + build**

```bash
cd frontend
npm run typecheck
npm run build
```
Expected: clean, `dist/` regenerated.

- [ ] **Step 3: Full end-to-end smoke test**

Rebuild Docker image and verify all behaviors:

```bash
docker compose build
docker compose up -d
sleep 5
curl -s http://localhost:8787/api/healthz | grep -q ok && echo "✓ healthz"
curl -s http://localhost:8787/api/settings | grep -q folder_pattern && echo "✓ settings"
curl -s http://localhost:8787/ | grep -q concertpvr && echo "✓ spa"
docker compose down
```

Expected: three `✓` lines.

- [ ] **Step 4: Final commit — tag phase 1 done**

If anything needed fixing, commit it with message `chore: phase 1 wrap-up — lint/type/test sweep`.

Then:

```bash
git tag -a phase-1-foundation -m "Phase 1 complete: foundation booted"
git log --oneline | head
```

Expected: tag applied, log shows all Phase 1 commits.

---

## Done — what's next

At tag `phase-1-foundation`:
- App boots in Docker
- `/api/healthz` and `/api/settings` work
- React SPA served with a working nav and functional Settings page
- All tests pass, lint clean, types clean

**Next up: Phase 2 — Record & Buffer.** Before starting, run the `writing-plans` skill again against the same spec to produce `docs/superpowers/plans/YYYY-MM-DD-phase-2-record-and-buffer.md`. That plan will add `streams` / `recordings` tables, the `recorder` + `buffer` modules, the Streams screen, and the Dashboard live-recording panel — building on the Phase 1 foundation.
