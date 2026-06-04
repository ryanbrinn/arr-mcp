"""Service diagnostic and health-check tools for arr-mcp."""

from __future__ import annotations

import json
import logging
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from mcp.server.fastmcp import FastMCP
from mcp.types import TextContent

from arr_mcp.config import Settings
from arr_mcp.runtime.client import ContainerClient
from arr_mcp.tools.services import (
    KNOWN_SERVICES,
    DiagnosticReport,
    Issue,
    ScannedService,
    run_diagnostics,
)

log = logging.getLogger(__name__)

_BLOCKED_DB_SUFFIXES = {".db", ".db-shm", ".db-wal"}


def _check_diagnostic_path(path: str, settings: Settings) -> Path:
    """Validate a path for diagnostic read access within services_dir.

    Unlike _check_path in filesystem.py, this allows reading config.xml.
    Database files are still blocked. No write access is granted.
    """
    try:
        p = Path(path).resolve()
    except ValueError as exc:
        raise PermissionError(f"Invalid path: {exc}") from exc

    services_root = Path(settings.services_dir).resolve()
    if not str(p).startswith(str(services_root) + "/") and p != services_root:
        raise PermissionError(f"Path not in services_dir: {p}")

    if p.suffix in _BLOCKED_DB_SUFFIXES:
        raise PermissionError(f"Access to database files is blocked: {p.name}")

    return p


def _collect_running_names(containers: list[dict[str, Any]]) -> set[str]:
    names: set[str] = set()
    for c in containers:
        for raw_name in c.get("Names") or []:
            names.add(raw_name.lstrip("/").lower())
    return names


def _scan_services(services_dir: Path, running_names: set[str]) -> list[ScannedService]:
    """Return a ScannedService for each subdirectory of services_dir."""
    if not services_dir.exists() or not services_dir.is_dir():
        return []

    results: list[ScannedService] = []
    for entry in sorted(services_dir.iterdir()):
        if not entry.is_dir():
            continue
        name = entry.name.lower()
        info = KNOWN_SERVICES.get(name)
        has_config = bool(info and (entry / info.config_file).exists())
        # Substring match covers stack-prefixed names like "media-sonarr"
        container_running = any(name in rname for rname in running_names)
        results.append(
            ScannedService(
                name=name,
                service_dir=str(entry),
                known=info is not None,
                has_config=has_config,
                container_running=container_running,
            )
        )
    return results


def register_diagnostic_tools(server: FastMCP, settings: Settings, client: ContainerClient) -> None:
    """Register service diagnostic tools with the MCP server."""

    @server.tool()
    async def service_scan() -> list[TextContent]:
        """Scan the services directory to discover installed media apps.

        Returns a JSON list where each entry describes a discovered service:
        name, directory path, whether it is a known app type, whether a
        config file is present, and whether a matching container is running.
        """
        services_root = Path(settings.services_dir).resolve()

        running_names: set[str] = set()
        try:
            containers: list[dict[str, Any]] = await client.get("/v1.41/containers/json?all=true")
            running_names = _collect_running_names(containers)
        except Exception as exc:
            log.warning("Could not fetch container list during service_scan: %s", exc)

        results = _scan_services(services_root, running_names)
        return [TextContent(type="text", text=json.dumps([s.to_dict() for s in results]))]

    @server.tool()
    async def service_diagnose(service: str, service_dir: str) -> list[TextContent]:
        """Run expert diagnostics on a specific media service.

        Checks config file validity, API key presence, port bindings,
        integration links, and recent log errors. Returns structured JSON
        with a status field ("healthy" | "degraded" | "critical" | "unknown"),
        a list of issues with fix hints, and a list of passing checks.

        Args:
            service: App name, e.g. "sonarr", "radarr", "plex".
            service_dir: Absolute path to the service config directory.
        """
        p = _check_diagnostic_path(service_dir, settings)
        info = KNOWN_SERVICES.get(service.lower())

        if info is None:
            report = DiagnosticReport(
                service=service,
                service_dir=str(p),
                status="unknown",
                warnings=[
                    Issue(
                        severity="info",
                        category="config",
                        message=(
                            f"'{service}' is not in the known service registry — "
                            "no expert checks available."
                        ),
                        fix_hint="",
                    )
                ],
                ok=[f"Directory exists: {p}"] if p.exists() else [],
            )
        else:
            report = run_diagnostics(service.lower(), p, info)

        return [TextContent(type="text", text=json.dumps(report.to_dict()))]

    @server.tool()
    async def service_health_report() -> list[TextContent]:
        """Scan all services and return a unified health report.

        Discovers every known service in services_dir, runs expert diagnostics
        on each, and returns a JSON object containing per-service results and a
        summary with counts of healthy, degraded, critical, and unknown services.
        """
        services_root = Path(settings.services_dir).resolve()

        running_names: set[str] = set()
        try:
            containers: list[dict[str, Any]] = await client.get("/v1.41/containers/json?all=true")
            running_names = _collect_running_names(containers)
        except Exception as exc:
            log.warning("Could not fetch container list during service_health_report: %s", exc)

        scanned = _scan_services(services_root, running_names)

        reports: list[dict[str, object]] = []
        summary: dict[str, int] = {"healthy": 0, "degraded": 0, "critical": 0, "unknown": 0}

        for svc in scanned:
            if not svc.known:
                continue
            info = KNOWN_SERVICES[svc.name]
            report = run_diagnostics(svc.name, Path(svc.service_dir), info)
            reports.append(report.to_dict())
            summary[report.status] = summary.get(report.status, 0) + 1

        result: dict[str, object] = {
            "scanned_at": datetime.now(UTC).isoformat(),
            "services": reports,
            "summary": summary,
        }
        return [TextContent(type="text", text=json.dumps(result))]

    @server.tool()
    async def service_fix(
        service: str,
        service_dir: str,
        fix_type: str,
        params: dict[str, str],
        confirm: bool = False,
    ) -> list[TextContent]:
        """Apply a configuration fix to a service.

        Requires confirm=True to apply changes. Supported fix types:

        - "update_config_xml": Update a single element value in config.xml.
          Required params: {"key": "<XmlElementTag>", "value": "<new value>"}
          Note: container restart required; XML comments may be lost.

        - "update_env_var": Update an environment variable in the service's
          compose file. Requires compose_dir to be configured.
          Required params: {"stack": "<stack name>", "var": "<VAR_NAME>", "value": "<new value>"}
          Note: stack restart required.

        Returns JSON with changed, before, after, and a note.

        Args:
            service: App name, e.g. "sonarr".
            service_dir: Absolute path to the service config directory.
            fix_type: "update_config_xml" or "update_env_var".
            params: Fix-specific key/value parameters.
            confirm: Must be True to apply the change.
        """
        if not confirm:
            return [
                TextContent(
                    type="text",
                    text=(
                        f"Pass confirm=True to apply '{fix_type}' to {service}. "
                        "Review the params carefully before confirming."
                    ),
                )
            ]

        p = _check_diagnostic_path(service_dir, settings)

        if fix_type == "update_config_xml":
            return await _fix_config_xml(service, p, params)

        if fix_type == "update_env_var":
            return _fix_env_var(settings, params)

        raise ValueError(
            f"Unknown fix_type: '{fix_type}'. Supported values: update_config_xml, update_env_var"
        )


async def _fix_config_xml(
    service: str, service_dir: Path, params: dict[str, str]
) -> list[TextContent]:
    key = params.get("key", "").strip()
    value = params.get("value", "").strip()
    if not key:
        return [TextContent(type="text", text="'key' is required in params.")]

    info = KNOWN_SERVICES.get(service.lower())
    config_filename = info.config_file if info else "config.xml"
    config_path = service_dir / config_filename

    if not config_path.exists():
        return [TextContent(type="text", text=f"Config file not found: {config_path}")]

    try:
        tree = ET.parse(str(config_path))
    except ET.ParseError as exc:
        return [TextContent(type="text", text=f"Cannot parse XML config: {exc}")]

    root = tree.getroot()
    element = root.find(key)
    if element is None:
        return [
            TextContent(
                type="text",
                text=json.dumps(
                    {
                        "changed": False,
                        "key": key,
                        "before": None,
                        "after": None,
                        "note": f"Key '{key}' not found in {config_filename}. No changes made.",
                    }
                ),
            )
        ]

    before = element.text or ""
    element.text = value
    ET.indent(tree, space="  ")
    tree.write(str(config_path), encoding="unicode", xml_declaration=False)

    result = {
        "changed": True,
        "key": key,
        "before": before,
        "after": value,
        "note": (
            "Container restart required for changes to take effect. "
            "XML comments may have been removed during write."
        ),
    }
    return [TextContent(type="text", text=json.dumps(result))]


def _fix_env_var(settings: Settings, params: dict[str, str]) -> list[TextContent]:
    stack = params.get("stack", "").strip()
    var = params.get("var", "").strip()
    value = params.get("value", "").strip()
    if not stack or not var:
        return [
            TextContent(
                type="text",
                text="'stack' and 'var' are required in params for update_env_var.",
            )
        ]

    if not settings.compose_dir:
        return [
            TextContent(
                type="text",
                text="compose_dir is not configured — update_env_var requires it.",
            )
        ]

    compose_root = Path(settings.compose_dir)
    compose_path = compose_root / stack / "compose.yaml"
    if not compose_path.exists():
        compose_path = compose_root / stack / "docker-compose.yml"
    if not compose_path.exists():
        return [TextContent(type="text", text=f"Compose file not found for stack: {stack}")]

    raw = compose_path.read_text()
    data: dict[str, Any] = yaml.safe_load(raw) or {}

    before: str | None = None
    changed = False
    services_block: dict[str, Any] = data.get("services", {})

    for svc_def in services_block.values():
        env = svc_def.get("environment")
        if isinstance(env, dict) and var in env:
            before = str(env[var])
            env[var] = value
            changed = True
            break
        if isinstance(env, list):
            for i, entry in enumerate(env):
                if isinstance(entry, str) and entry.startswith(f"{var}="):
                    before = entry.split("=", 1)[1]
                    env[i] = f"{var}={value}"
                    changed = True
                    break
            if changed:
                break

    if changed:
        compose_path.write_text(yaml.dump(data, default_flow_style=False))

    result = {
        "changed": changed,
        "var": var,
        "before": before,
        "after": value if changed else None,
        "note": (
            "Stack restart required for the new env var to take effect."
            if changed
            else f"Variable '{var}' not found in the compose file for stack '{stack}'."
        ),
    }
    return [TextContent(type="text", text=json.dumps(result))]
