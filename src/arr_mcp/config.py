"""Application settings loaded from environment / .env file."""

from __future__ import annotations

from pydantic import Field, field_validator
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
        """True when running Docker Compose — enables stack tools and dashboard view."""
        return self.container_runtime == "docker-compose"

    socket_path: str = Field(
        default="",
        description=(
            "Explicit socket path (e.g. unix:///run/user/1000/podman/podman.sock). "
            "When set, skips auto-detection. Required inside a container."
        ),
    )
    helper_socket: str = Field(
        default="/run/arr-agent/arr-agent.sock",
        description=(
            "Path to the arr-agent Unix socket. "
            "Override with ARR_MCP_HELPER_SOCKET if mounted elsewhere."
        ),
    )
    admin_users: list[str] = Field(
        default_factory=list,
        description=(
            "Comma-separated usernames that receive admin role on the dashboard. "
            "Set ARR_MCP_ADMIN_USERS=alice,bob"
        ),
    )
    session_secret: str = Field(
        default="",
        description=(
            "Secret key for signing dashboard session cookies. "
            'Generate with: python -c "import secrets; print(secrets.token_hex(32))". '
            "Sessions survive restarts only when this is set."
        ),
    )
    allowed_stacks: list[str] = Field(
        default_factory=list,
        description=(
            "Comma-separated stack names the MCP server may operate on. "
            "When empty all stacks under compose_dir are allowed. "
            "Set ARR_MCP_ALLOWED_STACKS=media,downloads to restrict."
        ),
    )
    log_level: str = Field(default="info", description="Logging level")

    # ------------------------------------------------------------------
    # AI provider
    # ------------------------------------------------------------------

    ai_provider: str = Field(
        default="ollama",
        description="AI backend: ollama | anthropic | none",
    )
    ollama_url: str = Field(
        default="http://localhost:11434",
        description="Base URL for the local Ollama instance",
    )
    ollama_model: str = Field(
        default="llama3.2:3b",
        description="Ollama model name to use for completions",
    )
    anthropic_api_key: str = Field(
        default="",
        description="Anthropic API key — required when ARR_MCP_AI_PROVIDER=anthropic",
    )
    anthropic_model: str = Field(
        default="claude-haiku-4-5-20251001",
        description="Anthropic model ID to use for completions",
    )

    # ------------------------------------------------------------------
    # Alert watcher
    # ------------------------------------------------------------------

    alert_interval_seconds: int = Field(
        default=300,
        description=("How often AlertWatcher polls for threshold violations (seconds)"),
    )

    @field_validator("allowed_stacks", "admin_users", mode="before")
    @classmethod
    def _parse_allowed_stacks(cls, v: object) -> list[str]:
        """Accept a comma-separated string or a list."""
        if isinstance(v, str):
            return [s.strip() for s in v.split(",") if s.strip()]
        return v  # type: ignore[return-value]
