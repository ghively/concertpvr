from pathlib import Path

from concertpvr.config import Config


def test_defaults_when_no_env(monkeypatch, tmp_path):
    for k in list(__import__("os").environ):
        if k.startswith("CPVR_"):
            monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("CPVR_DATA_DIR", str(tmp_path))
    cfg = Config()
    assert cfg.data_dir == tmp_path
    assert cfg.db_path == tmp_path / "metadata.db"
    assert cfg.host == "0.0.0.0"
    assert cfg.port == 8787


def test_overrides_from_env(monkeypatch, tmp_path):
    monkeypatch.setenv("CPVR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CPVR_PUBLISH_DIR", "/srv/concerts")
    monkeypatch.setenv("CPVR_PORT", "9000")
    cfg = Config()
    assert cfg.publish_dir == Path("/srv/concerts")
    assert cfg.port == 9000


def test_data_dir_required(monkeypatch):
    monkeypatch.delenv("CPVR_DATA_DIR", raising=False)
    try:
        Config()
    except Exception as e:
        assert "data_dir" in str(e).lower() or "CPVR_DATA_DIR" in str(e)
    else:
        raise AssertionError("expected Config() to raise without CPVR_DATA_DIR")
