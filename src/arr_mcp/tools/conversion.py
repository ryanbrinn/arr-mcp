"""Compose ↔ Quadlet conversion tools."""

from __future__ import annotations

import io
import logging
from pathlib import Path
from typing import Any

import yaml
from mcp.server.fastmcp import FastMCP
from mcp.types import TextContent

from arr_mcp.config import Settings
from arr_mcp.tools.utils import is_owned_by_current_user

log = logging.getLogger(__name__)

# Compose restart policy → Quadlet Restart= mapping
_RESTART_TO_QUADLET: dict[str, str] = {
    "unless-stopped": "always",
    "always": "always",
    "on-failure": "on-failure",
    "no": "no",
}

# Quadlet Restart= → Compose restart mapping (conservative)
_RESTART_TO_COMPOSE: dict[str, str] = {
    "always": "unless-stopped",
    "on-failure": "on-failure",
    "no": "no",
}

# Compose fields with no quadlet equivalent — warn but don't fail
_UNSUPPORTED_COMPOSE_FIELDS = {"build", "profiles", "deploy", "extends"}


# ---------------------------------------------------------------------------
# Pure conversion helpers (no I/O — easy to unit test)
# ---------------------------------------------------------------------------


def service_to_quadlet(name: str, service: dict[str, Any]) -> tuple[str, list[str]]:
    """Convert a single compose service dict to a .container file string.

    Returns (quadlet_content, warnings) where warnings lists unsupported fields.
    """
    warnings: list[str] = []
    lines_unit: list[str] = [
        "[Unit]",
        f"Description={name}",
        "After=network-online.target",
        "Wants=network-online.target",
    ]
    lines_container: list[str] = ["[Container]"]
    lines_service: list[str] = ["[Service]"]
    lines_install: list[str] = ["[Install]", "WantedBy=default.target"]

    # Check for unsupported fields
    for field in _UNSUPPORTED_COMPOSE_FIELDS:
        if field in service:
            warnings.append(f"  - '{field}' has no quadlet equivalent and was skipped")

    # Image
    image = service.get("image", "")
    if image:
        lines_container.append(f"Image={image}")

    # ContainerName
    container_name = service.get("container_name", name)
    lines_container.append(f"ContainerName={container_name}")

    # Environment — accepts both dict and list forms
    env = service.get("environment", {})
    if isinstance(env, dict):
        for k, v in env.items():
            lines_container.append(f"Environment={k}={v}")
    elif isinstance(env, list):
        for entry in env:
            lines_container.append(f"Environment={entry}")

    # Volumes
    for vol in service.get("volumes", []):
        lines_container.append(f"Volume={vol}")

    # Ports
    for port in service.get("ports", []):
        lines_container.append(f"PublishPort={port}")

    # Networks
    for net in service.get("networks", []):
        lines_container.append(f"Network={net}")

    # Healthcheck
    healthcheck = service.get("healthcheck", {})
    if healthcheck:
        test = healthcheck.get("test", "")
        if isinstance(test, list):
            # Strip CMD / CMD-SHELL prefix
            test = (
                " ".join(test[1:])
                if test and test[0] in ("CMD", "CMD-SHELL")
                else " ".join(test)
            )
        if test:
            lines_container.append(f"HealthCmd={test}")
        if "interval" in healthcheck:
            lines_container.append(f"HealthInterval={healthcheck['interval']}")
        if "timeout" in healthcheck:
            lines_container.append(f"HealthTimeout={healthcheck['timeout']}")
        if "retries" in healthcheck:
            lines_container.append(f"HealthRetries={healthcheck['retries']}")

    # Restart policy
    restart = service.get("restart", "")
    quadlet_restart = _RESTART_TO_QUADLET.get(restart, "")
    if quadlet_restart:
        lines_service.append(f"Restart={quadlet_restart}")

    # depends_on → After= in [Unit]
    depends_on = service.get("depends_on", [])
    if isinstance(depends_on, dict):
        depends_on = list(depends_on.keys())
    for dep in depends_on:
        lines_unit.append(f"After={dep}.service")

    sections = [
        "\n".join(lines_unit),
        "\n".join(lines_container),
        "\n".join(lines_service),
        "\n".join(lines_install),
    ]
    return "\n\n".join(sections) + "\n", warnings


def parse_quadlet(path: Path) -> dict[str, Any]:
    """Parse a .container file and return a normalised dict.

    Repeated keys (e.g. multiple Environment= lines) are joined with newlines
    so _collect_multi can split them back into a list.

    We parse manually rather than using configparser to correctly handle
    duplicate keys, which configparser silently overwrites.
    """
    result: dict[str, Any] = {}
    current_section: str | None = None

    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith(";"):
            continue
        if line.startswith("[") and line.endswith("]"):
            current_section = line[1:-1].lower()
            result.setdefault(current_section, {})
            continue
        if current_section is not None and "=" in line:
            key, _, value = line.partition("=")
            key = key.strip().lower()
            value = value.strip()
            section = result[current_section]
            if key in section:
                section[key] = f"{section[key]}\n{value}"
            else:
                section[key] = value

    return result


def _collect_multi(section: dict[str, Any], key: str) -> list[str]:
    """Collect all values for a key that may appear multiple times.

    configparser stores repeated keys as newline-joined values.
    """
    raw = section.get(key.lower(), "")
    if not raw:
        return []
    return [line.strip() for line in raw.splitlines() if line.strip()]


def quadlet_to_service(quadlet: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Convert a parsed quadlet dict to a (name, compose service dict) pair."""
    container = quadlet.get("container", {})
    unit = quadlet.get("unit", {})
    service_section = quadlet.get("service", {})

    name = container.get("containername", "")
    image = container.get("image", "")

    svc: dict[str, Any] = {}
    if image:
        svc["image"] = image
    if name:
        svc["container_name"] = name

    env_entries = _collect_multi(container, "Environment")
    if env_entries:
        svc["environment"] = env_entries

    volumes = _collect_multi(container, "Volume")
    if volumes:
        svc["volumes"] = volumes

    ports = _collect_multi(container, "PublishPort")
    if ports:
        svc["ports"] = ports

    networks = _collect_multi(container, "Network")
    if networks:
        svc["networks"] = networks

    restart_raw = service_section.get("restart", "")
    compose_restart = _RESTART_TO_COMPOSE.get(restart_raw, "")
    if compose_restart:
        svc["restart"] = compose_restart

    # After= → depends_on (strip .service/.container suffix)
    after_values = _collect_multi(unit, "After")
    deps = []
    for val in after_values:
        if val.endswith(".service") or val.endswith(".container"):
            deps.append(val.rsplit(".", 1)[0])
    if deps:
        svc["depends_on"] = deps

    # Health
    health_cmd = container.get("healthcmd", "")
    if health_cmd:
        healthcheck: dict[str, Any] = {"test": ["CMD-SHELL", health_cmd]}
        if "healthinterval" in container:
            healthcheck["interval"] = container["healthinterval"]
        if "healthtimeout" in container:
            healthcheck["timeout"] = container["healthtimeout"]
        if "healthretries" in container:
            healthcheck["retries"] = int(container["healthretries"])
        svc["healthcheck"] = healthcheck

    return name or "unknown", svc


# ---------------------------------------------------------------------------
# MCP tool registration
# ---------------------------------------------------------------------------


def register_conversion_tools(server: FastMCP, settings: Settings) -> None:
    """Register compose ↔ quadlet conversion tools with the MCP server."""
    stacks_root = Path(settings.compose_dir)

    def _stack_path(name: str) -> Path:
        p = stacks_root / name
        if not p.is_dir() or not is_owned_by_current_user(p):
            raise ValueError(f"Stack not found: {name}")
        return p

    @server.tool()
    async def compose_to_quadlets(stack: str) -> list[TextContent]:
        """Convert a stack's compose.yaml to quadlet .container files.

        Reads /opt/stacks/<stack>/compose.yaml and writes one .container
        file per service to /opt/stacks/<stack>/quadlets/ for review.
        """
        try:
            stack_dir = _stack_path(stack)
        except ValueError as exc:
            return [TextContent(type="text", text=str(exc))]

        # Find compose file
        compose_path: Path | None = None
        for fname in (
            "compose.yaml",
            "compose.yml",
            "docker-compose.yaml",
            "docker-compose.yml",
        ):
            candidate = stack_dir / fname
            if candidate.exists():
                compose_path = candidate
                break

        if compose_path is None:
            return [
                TextContent(type="text", text=f"No compose file found in {stack_dir}")
            ]

        try:
            data = yaml.safe_load(compose_path.read_text())
        except yaml.YAMLError as exc:
            return [
                TextContent(type="text", text=f"Could not parse compose.yaml: {exc}")
            ]

        if not isinstance(data, dict) or "services" not in data:
            return [
                TextContent(type="text", text="compose.yaml has no services defined")
            ]

        services: dict[str, Any] = data["services"] or {}
        if not services:
            return [
                TextContent(type="text", text="compose.yaml has no services defined")
            ]

        staging_dir = stack_dir / "quadlets"
        staging_dir.mkdir(exist_ok=True)

        written: list[str] = []
        all_warnings: list[str] = []

        for svc_name, svc_data in services.items():
            content, warnings = service_to_quadlet(svc_name, svc_data or {})
            out_path = staging_dir / f"{svc_name}.container"
            out_path.write_text(content)
            written.append(f"  {out_path.name}")
            if warnings:
                all_warnings.append(f"{svc_name}:")
                all_warnings.extend(warnings)

        lines = [f"Generated {len(written)} quadlet file(s) in {staging_dir}:", ""]
        lines.extend(written)

        if all_warnings:
            lines += ["", "Warnings (unsupported fields skipped):"]
            lines.extend(all_warnings)

        lines += [
            "",
            "To install, copy files to ~/.config/containers/systemd/ and run:",
            "  systemctl --user daemon-reload",
        ]

        return [TextContent(type="text", text="\n".join(lines))]

    @server.tool()
    async def quadlets_to_compose(stack: str) -> list[TextContent]:
        """Convert quadlet .container files back to a compose.yaml.

        Reads .container files from /opt/stacks/<stack>/quadlets/ and
        writes the result to /opt/stacks/<stack>/compose.from-quadlets.yaml.
        """
        try:
            stack_dir = _stack_path(stack)
        except ValueError as exc:
            return [TextContent(type="text", text=str(exc))]

        staging_dir = stack_dir / "quadlets"
        if not staging_dir.exists():
            return [
                TextContent(
                    type="text",
                    text=f"No quadlets directory found at {staging_dir}",
                )
            ]

        quadlet_files = sorted(staging_dir.glob("*.container"))
        if not quadlet_files:
            return [
                TextContent(
                    type="text",
                    text=f"No .container files found in {staging_dir}",
                )
            ]

        services: dict[str, Any] = {}
        skipped: list[str] = []

        for qfile in quadlet_files:
            try:
                quadlet = parse_quadlet(qfile)
                svc_name, svc_data = quadlet_to_service(quadlet)
                # Use stem as key if ContainerName was missing
                key = svc_name if svc_name != "unknown" else qfile.stem
                services[key] = svc_data
            except Exception as exc:
                log.warning("Skipping malformed quadlet %s: %s", qfile.name, exc)
                skipped.append(f"  {qfile.name}: {exc}")

        if not services:
            return [
                TextContent(type="text", text="No valid quadlet files could be parsed")
            ]

        compose_data: dict[str, Any] = {"services": services}

        # Render YAML with clean formatting
        stream = io.StringIO()
        yaml.dump(
            compose_data,
            stream,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
        )
        compose_yaml = stream.getvalue()

        out_path = stack_dir / "compose.from-quadlets.yaml"
        out_path.write_text(compose_yaml)

        lines = [f"Written: {out_path}", "", compose_yaml]
        if skipped:
            lines += ["Skipped (malformed):"]
            lines.extend(skipped)

        return [TextContent(type="text", text="\n".join(lines))]
