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
