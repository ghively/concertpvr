import pytest
from fastapi.testclient import TestClient

from concertpvr.main import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CPVR_DATA_DIR", str(tmp_path))
    with TestClient(create_app()) as c:
        yield c


def test_get_settings_returns_defaults_on_fresh_install(client):
    r = client.get("/api/settings")
    assert r.status_code == 200
    body = r.json()
    assert body["folder_pattern"] == "{artist} - {festival} ({year})"
    assert body["default_quality"] == "bestvideo*+bestaudio/best"
    assert body["max_concurrent_recordings"] == 4
    assert body["emby_url"] is None


def test_patch_settings_updates_values(client):
    r = client.patch(
        "/api/settings",
        json={
            "emby_url": "http://emby.local:8096",
            "max_concurrent_recordings": 2,
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["emby_url"] == "http://emby.local:8096"
    assert body["max_concurrent_recordings"] == 2
    # unchanged fields kept their defaults
    assert body["default_quality"] == "bestvideo*+bestaudio/best"


def test_patch_settings_rejects_unknown_fields(client):
    r = client.patch("/api/settings", json={"nonexistent_field": "x"})
    assert r.status_code == 422


def test_patch_settings_validates_types(client):
    r = client.patch("/api/settings", json={"max_concurrent_recordings": "not-a-number"})
    assert r.status_code == 422


def test_patching_emby_config_rebuilds_client(client):
    assert client.app.state.emby_client.configured is False

    client.patch(
        "/api/settings",
        json={
            "emby_url": "http://emby:8096",
            "emby_api_key": "secret123",
        },
    )

    assert client.app.state.emby_client.configured is True


def test_patch_settings_rejects_invalid_folder_pattern(client):
    r = client.patch("/api/settings", json={"folder_pattern": "{bogus_token}"})
    assert r.status_code == 422
    body = r.json()
    assert "folder_pattern" in str(body).lower()


def test_patch_settings_accepts_valid_folder_pattern(client):
    r = client.patch("/api/settings", json={"folder_pattern": "{artist} ({year})"})
    assert r.status_code == 200
    assert r.json()["folder_pattern"] == "{artist} ({year})"
