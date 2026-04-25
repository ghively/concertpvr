"""Entry point: `python -m concertpvr`."""

from pathlib import Path

import uvicorn

from concertpvr.config import Config

if __name__ == "__main__":
    cfg = Config(data_dir=Path("/tmp/concertpvr-data"))
    uvicorn.run(
        "concertpvr.main:create_app",
        factory=True,
        host=cfg.host,
        port=cfg.port,
        reload=False,
    )
