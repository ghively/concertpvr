from pathlib import Path

import pytest
from pydantic import ValidationError

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
    with pytest.raises(ValidationError) as exc_info:
        Config()
    assert "data_dir" in str(exc_info.value).lower()


def test_configure_logging_creates_log_file(tmp_path):
    import logging
    from concertpvr.logging_config import configure_logging

    configure_logging(tmp_path / "logs")
    logging.getLogger("concertpvr.test").info("hello")

    log_file = tmp_path / "logs" / "concertpvr.log"
    assert log_file.exists()
    assert "hello" in log_file.read_text()

    # Cleanup the global logging state so other tests aren't affected
    logging.getLogger().handlers = []
