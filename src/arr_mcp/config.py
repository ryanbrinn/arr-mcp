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
    compose_dir: str = Field(
        default="",
        description=(
            "Root directory for Docker Compose projects. "
            "Only used when ARR_MCP_CONTAINER_RUNTIME=docker-compose."
        ),
    )
    quadlets_dir: str = Field(
        default="~/.config/containers/systemd",
        description=(
            "Directory where Podman quadlet unit files live. "
            "Only used when ARR_MCP_CONTAINER_RUNTIME=podman."
        ),
    )
    services_dir: str = Field(
        default="/media-server",
        description=(
            "Root directory where your arr services live (configs, logs, data). "
            "Set ARR_MCP_SERVICES_DIR to match your mount point. "
            "Access is read-only; config.xml and database files are blocked."
        ),
    )
    media_dir: str = Field(
        default="/media-server/library",
        description=(
            "Root directory of your media library. "
            "Set ARR_MCP_MEDIA_DIR if your media is at a different path "
            "(e.g. a separate mount at /mnt/nas/media)."
        ),
    )
    container_runtime: str = Field(
        default="docker-compose",
        description="docker-compose | docker | podman | auto",
    )

    @property
    def is_compose(self) -> bool:
        """True when running Docker Compose — enables stack tools and dashboard stacks view."""
        return self.container_runtime == "docker-compose"

    socket_path: str = Field(
        default="",
        description="Explicit socket path (e.g. unix:///run/user/1000/podman/podman.sock). "
        "When set, skips runtime auto-detection. Required when running inside a container.",
    )
    helper_socket: str = Field(
        default="/run/arr-agent/arr-agent.sock",
        description="Path to the arr-agent Unix socket. "
        "Override with ARR_MCP_HELPER_SOCKET env var if the socket is mounted elsewhere.",
    )
    dashboard_public: bool = Field(
        default=False,
        description="Serve dashboard without auth (safe for LAN-only deployments)",
    )
    log_level: str = Field(default="info", description="Logging level")
