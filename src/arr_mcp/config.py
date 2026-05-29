"""Application settings loaded from environment / .env file."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ARR_MCP_",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    api_key: str = Field(default="changeme", description="Bearer token for HTTP auth")
    port: int = Field(default=8081, description="HTTP listen port")
    stacks_dir: str = Field(default="/opt/stacks", description="podman-compose stack root")
    media_dir: str = Field(default="/media-server", description="Media storage root")
    container_runtime: str = Field(default="auto", description="auto | docker | podman")
    log_level: str = Field(default="info", description="Logging level")
