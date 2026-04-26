"""Entry point: `python -m concertpvr`."""

import uvicorn

from concertpvr.config import Config
from concertpvr.logging_config import configure_logging

if __name__ == "__main__":
    cfg = Config()
    configure_logging(cfg.logs_dir)
    uvicorn.run(
        "concertpvr.main:create_app",
        factory=True,
        host=cfg.host,
        port=cfg.port,
        reload=False,
    )
