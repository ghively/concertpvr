"""Logging configuration — rotating file in CPVR_DATA_DIR/logs/ + console."""

from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path


def configure_logging(logs_dir: Path, level: str = "INFO") -> None:
    """Configure root logger.

    - INFO+ to stdout (so it shows up in `docker logs`).
    - INFO+ to a rotating file in `logs_dir/concertpvr.log` (5 MiB × 5 backups).
    """
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / "concertpvr.log"

    fmt = logging.Formatter(
        "%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)

    root.setLevel(level)

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    root.addHandler(console)

    file_handler = logging.handlers.RotatingFileHandler(
        log_path,
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)

    logging.getLogger("apscheduler.executors").setLevel("WARNING")
    logging.getLogger("apscheduler.scheduler").setLevel("WARNING")
