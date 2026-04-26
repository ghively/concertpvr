import pytest
from fastapi.testclient import TestClient

from concertpvr.auth import hash_password
from concertpvr.main import create_app
from concertpvr.models import Settings
from concertpvr.session import generate_secret


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CPVR_DATA_DIR", str(tmp_path))
    with TestClient(create_app()) as c:
        yield c


def _set_password(client, password: str) -> None:
    db = client.app.state.db
    with db.session() as s:
        row = s.get(Settings, 1)
        if row is None:
            row = Settings(id=1)
            s.add(row)
        row.password_hash = hash_password(password)
        if row.session_secret is None:
            row.session_secret = generate_secret()


def test_me_reports_unconfigured_first(client):
    r = client.get("/api/auth/me")
    assert r.status_code == 200
    body = r.json()
    assert body["password_set"] is False
    assert body["authenticated"] is True


def test_open_when_password_unset(client):
    r = client.get("/api/streams")
    assert r.status_code == 200


def test_login_succeeds_with_correct_password(client):
    _set_password(client, "hunter2")
    r = client.post("/api/auth/login", json={"password": "hunter2"})
    assert r.status_code == 204
    assert "cpvr_session" in r.cookies


def test_login_fails_with_wrong_password(client):
    _set_password(client, "hunter2")
    r = client.post("/api/auth/login", json={"password": "wrong"})
    assert r.status_code == 401


def test_protected_endpoint_requires_login_when_password_set(client):
    _set_password(client, "hunter2")
    r = client.get("/api/streams")
    assert r.status_code == 401


def test_protected_endpoint_works_after_login(client):
    _set_password(client, "hunter2")
    client.post("/api/auth/login", json={"password": "hunter2"})
    r = client.get("/api/streams")
    assert r.status_code == 200


def test_logout_clears_cookie(client):
    _set_password(client, "hunter2")
    client.post("/api/auth/login", json={"password": "hunter2"})
    r = client.post("/api/auth/logout")
    assert r.status_code == 204
    r2 = client.get("/api/streams")
    assert r2.status_code == 401


def test_healthz_always_open(client):
    _set_password(client, "hunter2")
    r = client.get("/api/healthz")
    assert r.status_code == 200


def test_me_after_login_reports_authenticated(client):
    _set_password(client, "hunter2")
    client.post("/api/auth/login", json={"password": "hunter2"})
    r = client.get("/api/auth/me")
    body = r.json()
    assert body["authenticated"] is True
    assert body["password_set"] is True


def test_set_password_first_time(client):
    r = client.post("/api/auth/set-password", json={"new_password": "hunter2"})
    assert r.status_code == 204
    r2 = client.get("/api/streams")
    assert r2.status_code == 200


def test_set_password_change_requires_current(client):
    client.post("/api/auth/set-password", json={"new_password": "old"})
    r = client.post("/api/auth/set-password", json={"new_password": "new"})
    assert r.status_code == 401
    r = client.post(
        "/api/auth/set-password", json={"new_password": "new", "current_password": "wrong"}
    )
    assert r.status_code == 401
    r = client.post(
        "/api/auth/set-password", json={"new_password": "new", "current_password": "old"}
    )
    assert r.status_code == 204


def test_session_secret_exists_at_boot(client):
    """Lifespan ensures Settings row + session_secret on startup."""
    db = client.app.state.db
    with db.session() as s:
        row = s.get(Settings, 1)
        assert row is not None
        assert row.session_secret is not None
        assert len(row.session_secret) > 16
