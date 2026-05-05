"""WebSocket auth gate (v0.4): /ws/streams + /ws/recordings refuse
unauthenticated connections when a password is set."""

import asyncio
import threading
import time

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from concertpvr.main import create_app
from concertpvr.models import Settings


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CPVR_DATA_DIR", str(tmp_path))
    with TestClient(create_app()) as c:
        yield c


def _set_password(client, password: str) -> None:
    """Direct DB write to set a password without going through the API."""
    from concertpvr.auth import hash_password
    from concertpvr.session import generate_secret

    db = client.app.state.db
    with db.session() as s:
        row = s.get(Settings, 1)
        assert row is not None
        row.password_hash = hash_password(password)
        if row.session_secret is None:
            row.session_secret = generate_secret()


def test_ws_progress_open_when_no_password_set(client):
    """Default state: no password → WS connects without auth."""
    bc = client.app.state.broadcaster
    loop = asyncio.new_event_loop()

    def runner():
        loop.run_forever()

    threading.Thread(target=runner, daemon=True).start()
    try:
        with client.websocket_connect("/ws/streams/42/progress") as ws:
            time.sleep(0.05)
            future = asyncio.run_coroutine_threadsafe(
                bc.publish("streams.42.progress", {"ok": True}), loop
            )
            future.result(timeout=1)
            assert ws.receive_json() == {"ok": True}
    finally:
        loop.call_soon_threadsafe(loop.stop)


def test_ws_streams_progress_rejects_when_password_set_no_cookie(client):
    _set_password(client, "secret")
    with (
        pytest.raises(WebSocketDisconnect) as excinfo,
        client.websocket_connect("/ws/streams/42/progress"),
    ):
        pass
    assert excinfo.value.code == 1008


def test_ws_recordings_progress_rejects_when_password_set_no_cookie(client):
    _set_password(client, "secret")
    with (
        pytest.raises(WebSocketDisconnect) as excinfo,
        client.websocket_connect("/ws/recordings/42/progress"),
    ):
        pass
    assert excinfo.value.code == 1008


def test_ws_progress_accepts_when_password_set_with_valid_cookie(client):
    _set_password(client, "letmein")
    # Login through the API to get a session cookie on the client.
    r = client.post("/api/auth/login", json={"password": "letmein"})
    assert r.status_code == 204

    bc = client.app.state.broadcaster
    loop = asyncio.new_event_loop()

    def runner():
        loop.run_forever()

    threading.Thread(target=runner, daemon=True).start()
    try:
        with client.websocket_connect("/ws/streams/42/progress") as ws:
            time.sleep(0.05)
            future = asyncio.run_coroutine_threadsafe(
                bc.publish("streams.42.progress", {"ok": True}), loop
            )
            future.result(timeout=1)
            assert ws.receive_json() == {"ok": True}
    finally:
        loop.call_soon_threadsafe(loop.stop)
