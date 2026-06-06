"""Service registry and pure diagnostic logic for media stack apps."""

from __future__ import annotations

import collections
import configparser
import json
import logging
import sqlite3
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

_DEFAULT_ERROR_PATTERNS = ["[error]", "[fatal]", "exception", "traceback", "unhandled"]


@dataclass(frozen=True)
class ServiceInfo:
    """Static knowledge about a known media service."""

    config_file: str
    config_format: str  # "xml" | "ini" | "json" | "yaml"
    log_dir: str
    port_xml_key: str | None
    default_port: int | None
    integration_keys: list[str]
    api_health_path: str | None = None  # lightweight health-check path
    db_file: str | None = None  # SQLite DB filename, e.g. "sonarr.db"


KNOWN_SERVICES: dict[str, ServiceInfo] = {
    "sonarr": ServiceInfo(
        config_file="config.xml",
        config_format="xml",
        log_dir="logs",
        port_xml_key="Port",
        default_port=8989,
        integration_keys=["NzbgetUrl", "SabnzbdUrl"],
        api_health_path="/api/v3/system/status",
        db_file="sonarr.db",
    ),
    "radarr": ServiceInfo(
        config_file="config.xml",
        config_format="xml",
        log_dir="logs",
        port_xml_key="Port",
        default_port=7878,
        integration_keys=["NzbgetUrl", "SabnzbdUrl"],
        api_health_path="/api/v3/system/status",
        db_file="radarr.db",
    ),
    "lidarr": ServiceInfo(
        config_file="config.xml",
        config_format="xml",
        log_dir="logs",
        port_xml_key="Port",
        default_port=8686,
        integration_keys=[],
        api_health_path="/api/v1/system/status",
        db_file="lidarr.db",
    ),
    "prowlarr": ServiceInfo(
        config_file="config.xml",
        config_format="xml",
        log_dir="logs",
        port_xml_key="Port",
        default_port=9696,
        integration_keys=[],
        api_health_path="/api/v1/system/status",
        db_file="prowlarr.db",
    ),
    "readarr": ServiceInfo(
        config_file="config.xml",
        config_format="xml",
        log_dir="logs",
        port_xml_key="Port",
        default_port=8787,
        integration_keys=[],
        api_health_path="/api/v1/system/status",
        db_file="readarr.db",
    ),
    "bazarr": ServiceInfo(
        config_file="config.yaml",
        config_format="yaml",
        log_dir="log",
        port_xml_key=None,
        default_port=6767,
        integration_keys=[],
        api_health_path="/api/system/status",
    ),
    "sabnzbd": ServiceInfo(
        config_file="sabnzbd.ini",
        config_format="ini",
        log_dir="logs",
        port_xml_key=None,
        default_port=8080,
        integration_keys=[],
        api_health_path="/api?mode=version",
    ),
    "plex": ServiceInfo(
        config_file="Preferences.xml",
        config_format="xml",
        log_dir="Logs",
        port_xml_key=None,
        default_port=32400,
        integration_keys=[],
        api_health_path="/identity",
    ),
    "jellyfin": ServiceInfo(
        config_file="system.xml",
        config_format="xml",
        log_dir="log",
        port_xml_key=None,
        default_port=8096,
        integration_keys=[],
        api_health_path="/health",
    ),
    "overseerr": ServiceInfo(
        config_file="settings.json",
        config_format="json",
        log_dir="logs",
        port_xml_key=None,
        default_port=5055,
        integration_keys=[],
        api_health_path="/api/v1/status",
    ),
    "tautulli": ServiceInfo(
        config_file="config.ini",
        config_format="ini",
        log_dir="logs",
        port_xml_key=None,
        default_port=8181,
        integration_keys=[],
        api_health_path="/api/v2?cmd=get_server_info",
    ),
    "qbittorrent": ServiceInfo(
        config_file="qBittorrent.conf",
        config_format="ini",
        log_dir="logs",
        port_xml_key=None,
        default_port=8080,
        integration_keys=[],
        api_health_path="/api/v2/app/version",
    ),
    "nzbget": ServiceInfo(
        config_file="nzbget.conf",
        config_format="ini",
        log_dir="logs",
        port_xml_key=None,
        default_port=6789,
        integration_keys=[],
    ),
}


@dataclass
class ApiReachabilityResult:
    """Result of a lightweight HTTP reachability check against a service API."""

    reachable: bool
    status_code: int | None  # HTTP status if a response was received
    error: str | None  # connection error message if no response received

    def to_dict(self) -> dict[str, object]:
        """Serialise to a JSON-safe dict."""
        return {
            "reachable": self.reachable,
            "status_code": self.status_code,
            "error": self.error,
        }


def extract_service_port(service_dir: Path, info: ServiceInfo) -> int | None:
    """Return the port a service is listening on, from config file or default."""
    if info.port_xml_key and info.config_format == "xml":
        config_path = service_dir / info.config_file
        try:
            cfg = parse_xml_config(config_path)
            raw = cfg.get(info.port_xml_key, "").strip()
            if raw.isdigit():
                return int(raw)
        except (ValueError, OSError):
            pass
    return info.default_port


def extract_xml_api_key(service_dir: Path, info: ServiceInfo) -> str:
    """Return the ApiKey from an XML config file, or empty string."""
    if info.config_format != "xml":
        return ""
    config_path = service_dir / info.config_file
    try:
        cfg = parse_xml_config(config_path)
        return cfg.get("ApiKey", "").strip()
    except (ValueError, OSError):
        return ""


def extract_ini_api_key(service_dir: Path, info: ServiceInfo, section: str, key: str) -> str:
    """Return an API key from a specific INI section/key, or empty string."""
    if info.config_format != "ini":
        return ""
    config_path = service_dir / info.config_file
    try:
        cfg = parse_ini_config(config_path)
        return cfg.get(section, {}).get(key, "").strip()
    except (configparser.Error, OSError):
        return ""


@dataclass
class DownloadClientRecord:
    """A download client row from the arr service database."""

    id: int
    name: str
    implementation: str
    settings: dict[str, object]
    enable: bool

    def to_dict(self) -> dict[str, object]:
        """Serialise to a JSON-safe dict."""
        return {
            "id": self.id,
            "name": self.name,
            "implementation": self.implementation,
            "settings": self.settings,
            "enable": self.enable,
        }


@dataclass
class IndexerRecord:
    """An indexer row from the arr service database."""

    id: int
    name: str
    implementation: str
    enable: bool

    def to_dict(self) -> dict[str, object]:
        """Serialise to a JSON-safe dict."""
        return {
            "id": self.id,
            "name": self.name,
            "implementation": self.implementation,
            "enable": self.enable,
        }


def _open_db_readonly(db_path: Path) -> sqlite3.Connection:
    """Open a SQLite database in read-only mode using URI syntax."""
    uri = f"file:{db_path.as_posix()}?mode=ro"
    return sqlite3.connect(uri, uri=True, check_same_thread=False)


def read_download_clients(db_path: Path) -> list[DownloadClientRecord]:
    """Read the DownloadClients table from an arr service database.

    Returns an empty list if the table does not exist or the DB is unavailable.
    """
    if not db_path.exists():
        return []
    try:
        with _open_db_readonly(db_path) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.execute(
                "SELECT Id, Name, Implementation, Settings, Enable FROM DownloadClients"
            )
            rows = cur.fetchall()
    except sqlite3.OperationalError:
        return []

    result: list[DownloadClientRecord] = []
    for row in rows:
        try:
            settings: dict[str, object] = json.loads(row["Settings"] or "{}")
        except (json.JSONDecodeError, TypeError):
            settings = {}
        result.append(
            DownloadClientRecord(
                id=row["Id"],
                name=row["Name"],
                implementation=row["Implementation"],
                settings=settings,
                enable=bool(row["Enable"]),
            )
        )
    return result


def read_indexers(db_path: Path) -> list[IndexerRecord]:
    """Read the Indexers table from an arr service database.

    Returns an empty list if the table does not exist or the DB is unavailable.
    """
    if not db_path.exists():
        return []
    try:
        with _open_db_readonly(db_path) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.execute("SELECT Id, Name, Implementation, Enable FROM Indexers")
            rows = cur.fetchall()
    except sqlite3.OperationalError:
        return []

    return [
        IndexerRecord(
            id=row["Id"],
            name=row["Name"],
            implementation=row["Implementation"],
            enable=bool(row["Enable"]),
        )
        for row in rows
    ]


@dataclass
class Issue:
    """A single diagnostic finding."""

    severity: str  # "error" | "warning" | "info"
    category: str  # "config" | "port" | "integration" | "logs" | "missing"
    message: str
    fix_hint: str  # actionable instruction; empty string if no automated fix available

    def to_dict(self) -> dict[str, str]:
        """Serialise to a JSON-safe dict."""
        return {
            "severity": self.severity,
            "category": self.category,
            "message": self.message,
            "fix_hint": self.fix_hint,
        }


@dataclass
class DiagnosticReport:
    """Full diagnostic result for a single service."""

    service: str
    service_dir: str
    status: str  # "healthy" | "degraded" | "critical" | "unknown"
    issues: list[Issue] = field(default_factory=list)
    warnings: list[Issue] = field(default_factory=list)
    ok: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        """Serialise to a JSON-safe dict."""
        return {
            "service": self.service,
            "service_dir": self.service_dir,
            "status": self.status,
            "issues": [i.to_dict() for i in self.issues],
            "warnings": [w.to_dict() for w in self.warnings],
            "ok": self.ok,
        }


@dataclass
class ScannedService:
    """Discovered service entry from a services_dir scan."""

    name: str
    service_dir: str
    known: bool
    has_config: bool
    container_running: bool

    def to_dict(self) -> dict[str, object]:
        """Serialise to a JSON-safe dict."""
        return {
            "name": self.name,
            "service_dir": self.service_dir,
            "known": self.known,
            "has_config": self.has_config,
            "container_running": self.container_running,
        }


def parse_xml_config(path: Path) -> dict[str, str]:
    """Parse an XML config file and return a flat dict of element tag → text."""
    try:
        tree = ET.parse(str(path))
    except ET.ParseError as exc:
        raise ValueError(f"Malformed XML in {path.name}: {exc}") from exc
    root = tree.getroot()
    return {child.tag: (child.text or "").strip() for child in root}


def parse_ini_config(path: Path) -> dict[str, dict[str, str]]:
    """Parse an INI config file and return a nested dict of section → key → value."""
    parser = configparser.ConfigParser()
    parser.read(str(path))
    return {section: dict(parser[section]) for section in parser.sections()}


def parse_json_config(path: Path) -> dict[str, object]:
    """Parse a JSON config file and return a dict."""
    try:
        return json.loads(path.read_text(errors="replace"))  # type: ignore[no-any-return]
    except json.JSONDecodeError as exc:
        raise ValueError(f"Malformed JSON in {path.name}: {exc}") from exc


def check_api_key_present(config: dict[str, str]) -> bool:
    """Return True if ApiKey is present and non-empty in an XML config dict."""
    return bool(config.get("ApiKey", "").strip())


def check_port_binding(config: dict[str, str], port_key: str) -> tuple[str, bool]:
    """Return (port_value, is_localhost_only).

    is_localhost_only is True when BindAddress is a loopback address, which
    breaks inter-container communication in Docker/Podman networks.
    """
    port = config.get(port_key, "").strip()
    bind = config.get("BindAddress", "").strip().lower()
    return port, bind in {"localhost", "127.0.0.1", "::1"}


def scan_log_errors(
    log_dir: Path,
    patterns: list[str] | None = None,
    max_lines: int = 500,
) -> list[str]:
    """Scan the most recent log file in log_dir for lines matching any pattern."""
    effective_patterns = patterns if patterns is not None else _DEFAULT_ERROR_PATTERNS

    if not log_dir.exists() or not log_dir.is_dir():
        return []

    log_files = sorted(log_dir.glob("*.txt"), key=lambda f: f.stat().st_mtime, reverse=True)
    if not log_files:
        log_files = sorted(log_dir.glob("*.log"), key=lambda f: f.stat().st_mtime, reverse=True)
    if not log_files:
        return []

    tail: collections.deque[str] = collections.deque(maxlen=max_lines)
    try:
        with log_files[0].open(errors="replace") as f:
            for line in f:
                tail.append(line)
    except OSError:
        return []

    lower_patterns = [p.lower() for p in effective_patterns]
    return [line for line in tail if any(p in line.lower() for p in lower_patterns)]


def _check_db_download_clients(
    service: str,
    db_path: Path,
    issues: list[Issue],
    warnings: list[Issue],
    ok: list[str],
) -> None:
    """Append download client findings to issues/warnings/ok lists."""
    if not db_path.exists():
        return

    clients = read_download_clients(db_path)
    if not clients:
        warnings.append(
            Issue(
                severity="warning",
                category="integration",
                message="No download clients configured in the database",
                fix_hint=(f"Add a download client in {service} Settings → Download Clients."),
            )
        )
        return

    enabled = [c for c in clients if c.enable]
    disabled = [c for c in clients if not c.enable]

    for client in enabled:
        ok.append(f"Download client enabled: {client.name} ({client.implementation})")
    for client in disabled:
        warnings.append(
            Issue(
                severity="warning",
                category="integration",
                message=f"Download client is disabled: {client.name} ({client.implementation})",
                fix_hint=(f"Enable the download client in {service} Settings → Download Clients."),
            )
        )


def _check_db_indexers(
    service: str,
    db_path: Path,
    warnings: list[Issue],
    ok: list[str],
) -> None:
    """Append indexer findings to warnings/ok lists."""
    if not db_path.exists():
        return

    indexers = read_indexers(db_path)
    if not indexers:
        warnings.append(
            Issue(
                severity="warning",
                category="integration",
                message="No indexers configured in the database",
                fix_hint=(f"Add an indexer in {service} Settings → Indexers."),
            )
        )
        return

    enabled = [i for i in indexers if i.enable]
    for idx in enabled:
        ok.append(f"Indexer enabled: {idx.name} ({idx.implementation})")
    if not enabled:
        warnings.append(
            Issue(
                severity="warning",
                category="integration",
                message="All configured indexers are disabled",
                fix_hint=f"Enable at least one indexer in {service} Settings → Indexers.",
            )
        )


def _compute_status(issues: list[Issue], warnings: list[Issue]) -> str:
    if any(i.severity == "error" for i in issues):
        return "critical"
    if warnings:
        return "degraded"
    return "healthy"


def run_diagnostics(service: str, service_dir: Path, info: ServiceInfo) -> DiagnosticReport:
    """Run expert diagnostics on a known service.

    Pure function — only performs filesystem reads, no MCP or network I/O.
    Suitable for direct testing with tmp_path fixtures.
    """
    issues: list[Issue] = []
    warnings: list[Issue] = []
    ok: list[str] = []

    config_path = service_dir / info.config_file

    if not config_path.exists():
        issues.append(
            Issue(
                severity="error",
                category="missing",
                message=f"Config file not found: {info.config_file}",
                fix_hint=(
                    f"Ensure {service} has started at least once and that "
                    "services_dir is mounted to the correct path."
                ),
            )
        )
        return DiagnosticReport(
            service=service,
            service_dir=str(service_dir),
            status="critical",
            issues=issues,
            warnings=warnings,
            ok=ok,
        )

    if info.config_format == "xml":
        try:
            config_xml = parse_xml_config(config_path)
        except ValueError as exc:
            issues.append(
                Issue(
                    severity="error",
                    category="config",
                    message=str(exc),
                    fix_hint=(
                        "Restore config.xml from a backup or remove it so the app regenerates it."
                    ),
                )
            )
            return DiagnosticReport(
                service=service,
                service_dir=str(service_dir),
                status="unknown",
                issues=issues,
                warnings=warnings,
                ok=ok,
            )

        ok.append(f"Config file parsed successfully: {info.config_file}")

        # API key check applies to *arr apps that have an ApiKey element
        if "ApiKey" in config_xml or info.port_xml_key:
            if not check_api_key_present(config_xml):
                issues.append(
                    Issue(
                        severity="error",
                        category="config",
                        message="ApiKey is missing or empty in config.xml",
                        fix_hint=(
                            f"Restart {service} to trigger key generation, "
                            "or set ApiKey manually and restart."
                        ),
                    )
                )
            else:
                ok.append("ApiKey is set")

        if info.port_xml_key:
            port, is_localhost = check_port_binding(config_xml, info.port_xml_key)
            if is_localhost:
                warnings.append(
                    Issue(
                        severity="warning",
                        category="port",
                        message=(
                            f"BindAddress is set to a loopback address — {service} will only "
                            "accept connections from localhost, breaking inter-container links."
                        ),
                        fix_hint=(
                            'Set BindAddress to "" (blank) or "0.0.0.0" in config.xml '
                            "and restart the container."
                        ),
                    )
                )
            elif port:
                ok.append(f"Port {port} is accessible on all interfaces")

        for key in info.integration_keys:
            val = config_xml.get(key, "").strip()
            if val:
                ok.append(f"Integration configured: {key}={val}")

    elif info.config_format == "ini":
        try:
            parse_ini_config(config_path)
            ok.append(f"Config file parsed successfully: {info.config_file}")
        except (configparser.Error, OSError) as exc:
            warnings.append(
                Issue(
                    severity="warning",
                    category="config",
                    message=f"Could not fully parse INI config: {exc}",
                    fix_hint="Check the config file for syntax errors.",
                )
            )

    elif info.config_format == "json":
        try:
            parse_json_config(config_path)
            ok.append(f"Config file parsed successfully: {info.config_file}")
        except ValueError as exc:
            warnings.append(
                Issue(
                    severity="warning",
                    category="config",
                    message=str(exc),
                    fix_hint="Check the config file for JSON syntax errors.",
                )
            )

    else:
        ok.append(f"Config file present: {info.config_file}")

    if info.db_file:
        db_path = service_dir / info.db_file
        _check_db_download_clients(service, db_path, issues, warnings, ok)
        _check_db_indexers(service, db_path, warnings, ok)

    log_dir = service_dir / info.log_dir
    error_lines = scan_log_errors(log_dir)
    if error_lines:
        warnings.append(
            Issue(
                severity="warning",
                category="logs",
                message=f"Found {len(error_lines)} error/exception line(s) in recent logs",
                fix_hint=f"Use log_read to inspect {service}/{info.log_dir} for more detail.",
            )
        )
    else:
        ok.append("No recent log errors detected")

    return DiagnosticReport(
        service=service,
        service_dir=str(service_dir),
        status=_compute_status(issues, warnings),
        issues=issues,
        warnings=warnings,
        ok=ok,
    )
