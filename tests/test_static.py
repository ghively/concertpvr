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
