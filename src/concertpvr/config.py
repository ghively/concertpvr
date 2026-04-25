"""Deployment-time configuration loaded from environment variables."""
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    """Environment-driven runtime config. Prefix: CPVR_."""

    model_config = SettingsConfigDict(env_prefix="CPVR_", extra="ignore")

    data_dir: Path = Field(..., description="Host data directory (mounted into container)")
    publish_dir: Path = Field(
        default=Path("/media/concerts"),
        description="Where published segments land (Emby movies library)",
    )

    host: str = "0.0.0.0"
    port: int = 8787

    @property
    def db_path(self) -> Path:
        return self.data_dir / "metadata.db"

    @property
    def db_url(self) -> str:
        return f"sqlite:///{self.db_path}"

    @property
    def buffer_dir(self) -> Path:
        return self.data_dir / "buffer"

    @property
    def staging_dir(self) -> Path:
        return self.data_dir / "staging"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"
