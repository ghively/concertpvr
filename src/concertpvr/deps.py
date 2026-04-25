"""FastAPI dependency callables."""

from fastapi import Request

from concertpvr.db import Database


def get_db(request: Request) -> Database:
    """Access the per-app Database from app state."""
    return request.app.state.db  # type: ignore[no-any-return]
