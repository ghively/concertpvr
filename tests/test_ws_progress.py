import asyncio
import threading
import time

import pytest
from fastapi.testclient import TestClient

from concertpvr.main import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CPVR_DATA_DIR", str(tmp_path))
    with TestClient(create_app()) as c:
        yield c


def test_ws_progress_receives_published_events(client):
    bc = client.app.state.broadcaster
    loop = asyncio.new_event_loop()

    def runner():
        loop.run_forever()

    threading.Thread(target=runner, daemon=True).start()

    try:
        with client.websocket_connect("/ws/streams/42/progress") as ws:
            time.sleep(0.1)  # let subscribe register
            future = asyncio.run_coroutine_threadsafe(
                bc.publish("streams.42.progress", {"bytes_total": 1024}), loop
            )
            future.result(timeout=1)
            msg = ws.receive_json()
            assert msg == {"bytes_total": 1024}
    finally:
        loop.call_soon_threadsafe(loop.stop)
