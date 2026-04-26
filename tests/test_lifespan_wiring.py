import pytest
from fastapi.testclient import TestClient

from concertpvr.main import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CPVR_DATA_DIR", str(tmp_path))
    with TestClient(create_app()) as c:
        yield c


def test_pool_and_scheduler_present_on_app_state(client):
    app = client.app
    assert hasattr(app.state, "pool")
    assert hasattr(app.state, "scheduler")
    assert hasattr(app.state, "broadcaster")
    assert hasattr(app.state, "buffer")


def test_scheduler_is_running(client):
    assert client.app.state.scheduler.running is True
