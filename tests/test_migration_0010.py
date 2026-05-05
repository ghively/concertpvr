"""Migration 0010: emby path translation columns + setlistfm api key + per-watcher toggle."""

import subprocess
import sys

import sqlalchemy as sa


def _run(args, env=None):
    r = subprocess.run(args, capture_output=True, text=True, env=env)
    return r


def test_migration_0010_adds_columns(tmp_path, monkeypatch):
    monkeypatch.setenv("CPVR_DATA_DIR", str(tmp_path))

    r = _run([sys.executable, "-m", "alembic", "upgrade", "head"])
    assert r.returncode == 0, r.stderr

    db = tmp_path / "metadata.db"
    eng = sa.create_engine(f"sqlite:///{db}")
    insp = sa.inspect(eng)

    settings_cols = {c["name"] for c in insp.get_columns("settings")}
    assert "emby_path_local_prefix" in settings_cols
    assert "emby_path_emby_prefix" in settings_cols
    assert "setlistfm_api_key" in settings_cols

    watcher_cols = {c["name"] for c in insp.get_columns("channel_watchers")}
    assert "extract_setlist_from_setlistfm" in watcher_cols


def test_migration_0010_downgrade_drops_columns(tmp_path, monkeypatch):
    monkeypatch.setenv("CPVR_DATA_DIR", str(tmp_path))

    r = _run([sys.executable, "-m", "alembic", "upgrade", "head"])
    assert r.returncode == 0, r.stderr

    r = _run([sys.executable, "-m", "alembic", "downgrade", "0009_channel_backlog_cache"])
    assert r.returncode == 0, r.stderr

    db = tmp_path / "metadata.db"
    eng = sa.create_engine(f"sqlite:///{db}")
    insp = sa.inspect(eng)

    settings_cols = {c["name"] for c in insp.get_columns("settings")}
    assert "emby_path_local_prefix" not in settings_cols
    assert "emby_path_emby_prefix" not in settings_cols
    assert "setlistfm_api_key" not in settings_cols

    watcher_cols = {c["name"] for c in insp.get_columns("channel_watchers")}
    assert "extract_setlist_from_setlistfm" not in watcher_cols
