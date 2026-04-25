"""Shared pytest fixtures."""

from pathlib import Path

import pytest

from concertpvr.db import Database


@pytest.fixture
def tmp_db(tmp_path: Path) -> Database:
    """A throw-away SQLite database per test."""
    return Database(f"sqlite:///{tmp_path / 'test.db'}")
