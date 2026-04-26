"""FastAPI dependency callables."""

from fastapi import Request

from concertpvr.buffer import BufferManager
from concertpvr.db import Database
from concertpvr.pool import RecorderPool
from concertpvr.ws import Broadcaster


def get_db(request: Request) -> Database:
    """Access the per-app Database from app state."""
    return request.app.state.db  # type: ignore[no-any-return]


def get_pool(request: Request) -> RecorderPool:
    return request.app.state.pool  # type: ignore[no-any-return]


def get_buffer(request: Request) -> BufferManager:
    return request.app.state.buffer  # type: ignore[no-any-return]


def get_broadcaster(request: Request) -> Broadcaster:
    return request.app.state.broadcaster  # type: ignore[no-any-return]
