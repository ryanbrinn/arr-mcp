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
    stacks_dir: str = Field(default="/opt/stacks", description="Stack root directory")
    media_dir: str = Field(default="/media-server", description="Media storage root")
    container_runtime: str = Field(default="auto", description="auto | docker | podman")

    socket_path: str = Field(
        default="",
        description="Explicit socket path (e.g. unix:///run/user/1000/podman/podman.sock). "
        "When set, skips runtime auto-detection. Required when running inside a container.",
    )
    dashboard_public: bool = Field(
        default=False,
        description="Serve dashboard without auth (safe for LAN-only deployments)",
    )
    public_url: str = Field(
        default="",
        description="Public URL used in the 'Open in Claude' button",
    )
    log_level: str = Field(default="info", description="Logging level")
