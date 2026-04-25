"""Entry point: `python -m concertpvr`."""
import uvicorn

from concertpvr.config import Config

if __name__ == "__main__":
    cfg = Config()
    uvicorn.run(
        "concertpvr.main:create_app",
        factory=True,
        host=cfg.host,
        port=cfg.port,
        reload=False,
    )
