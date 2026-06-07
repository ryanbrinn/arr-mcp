"""Secure per-service API credential management."""

from __future__ import annotations

import base64
import json
import logging
import os
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from pathlib import Path

log = logging.getLogger(__name__)

# Env var names per service — highest priority credential source
_ENV_KEY_MAP: dict[str, str] = {
    "sonarr": "SONARR_API_KEY",
    "radarr": "RADARR_API_KEY",
    "lidarr": "LIDARR_API_KEY",
    "prowlarr": "PROWLARR_API_KEY",
    "readarr": "READARR_API_KEY",
    "plex": "PLEX_TOKEN",
    "sabnzbd": "SABNZBD_API_KEY",
    "nzbget": "NZBGET_API_KEY",
    "qbittorrent": "QBITTORRENT_PASSWORD",
    "overseerr": "OVERSEERR_API_KEY",
    "tautulli": "TAUTULLI_API_KEY",
    "bazarr": "BAZARR_API_KEY",
    "jellyfin": "JELLYFIN_API_KEY",
}

_CREDENTIAL_FILE = ".arr-mcp-credentials.json"


@dataclass
class ServiceCredential:
    """API credential for a single service."""

    api_key: str
    base_url: str | None = None


def _encrypt(data: str, secret: str) -> str:
    """XOR-encrypt data with secret and base64-encode the result."""
    key_bytes = secret.encode()
    data_bytes = data.encode()
    encrypted = bytes(b ^ key_bytes[i % len(key_bytes)] for i, b in enumerate(data_bytes))
    return base64.b64encode(encrypted).decode()


def _decrypt(data: str, secret: str) -> str:
    """Base64-decode and XOR-decrypt data with secret."""
    key_bytes = secret.encode()
    encrypted = base64.b64decode(data.encode())
    decrypted = bytes(b ^ key_bytes[i % len(key_bytes)] for i, b in enumerate(encrypted))
    return decrypted.decode()


def _load_file(path: Path, secret: str | None) -> dict[str, dict[str, str | None]]:
    if not path.exists():
        return {}
    raw = path.read_text()
    if not raw.strip():
        return {}
    if secret:
        try:
            raw = _decrypt(raw, secret)
        except Exception:
            log.warning("Failed to decrypt credential file — returning empty store")
            return {}
    try:
        loaded: dict[str, dict[str, str | None]] = json.loads(raw)
        return loaded
    except json.JSONDecodeError:
        log.warning("Credential file is not valid JSON — returning empty store")
        return {}


def _save_file(path: Path, data: dict[str, dict[str, str | None]], secret: str | None) -> None:
    raw = json.dumps(data)
    if secret:
        raw = _encrypt(raw, secret)
    path.write_text(raw)
    # Restrict to owner read/write only
    try:
        path.chmod(0o600)
    except OSError:
        pass


class CredentialStore:
    """Single source of truth for API credentials across all services.

    Resolution order (highest priority first):
    1. Environment variable (e.g. SONARR_API_KEY)
    2. Stored credential in the credential file
    3. Auto-discovered from the service's local XML config file
    """

    def __init__(self, services_dir: str) -> None:
        self._services_dir = Path(services_dir)
        self._cred_file = self._services_dir / _CREDENTIAL_FILE
        self._secret: str | None = os.environ.get("ARR_MCP_SECRET") or None
        if not self._secret:
            log.warning(
                "ARR_MCP_SECRET is not set — credentials stored in plaintext. "
                "Set this env var for encrypted storage."
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(self, service: str) -> ServiceCredential | None:
        """Return the credential for a service, or None if not configured."""
        service = service.lower()

        # 1. Environment variable
        env_key = _ENV_KEY_MAP.get(service)
        if env_key:
            api_key = os.environ.get(env_key)
            if api_key:
                return ServiceCredential(api_key=api_key)

        # 2. Stored credential file
        stored = self._read_file().get(service)
        if stored and stored.get("api_key"):
            return ServiceCredential(
                api_key=stored["api_key"],  # type: ignore[arg-type]
                base_url=stored.get("base_url"),
            )

        # 3. Auto-discover from XML config
        api_key = self._autodiscover_api_key(service)
        if api_key:
            return ServiceCredential(api_key=api_key)

        return None

    def set(self, service: str, cred: ServiceCredential) -> None:
        """Store or update a credential for the given service."""
        service = service.lower()
        data = self._read_file()
        data[service] = {k: v for k, v in asdict(cred).items() if v is not None}
        _save_file(self._cred_file, data, self._secret)

    def delete(self, service: str) -> None:
        """Remove a stored credential for the given service."""
        service = service.lower()
        data = self._read_file()
        data.pop(service, None)
        _save_file(self._cred_file, data, self._secret)

    def list_configured(self) -> list[str]:
        """Return service names that have credentials configured (any source).

        Never returns key values.
        """
        configured: set[str] = set()

        # Env vars
        for svc, env_var in _ENV_KEY_MAP.items():
            if os.environ.get(env_var):
                configured.add(svc)

        # Stored file
        configured.update(self._read_file().keys())

        # Auto-discoverable (XML config present with ApiKey)
        for svc in self._autodiscoverable_services():
            configured.add(svc)

        return sorted(configured)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _read_file(self) -> dict[str, dict[str, str | None]]:
        return _load_file(self._cred_file, self._secret)

    def _autodiscover_api_key(self, service: str) -> str | None:
        """Try to read ApiKey from a service's XML config file."""
        config_path = self._services_dir / service / "config.xml"
        if not config_path.exists():
            return None
        try:
            tree = ET.parse(config_path)
            root = tree.getroot()
            elem = root.find("ApiKey")
            if elem is not None and elem.text:
                return elem.text
        except Exception:
            pass
        return None

    def _autodiscoverable_services(self) -> list[str]:
        """Return services with a readable XML config containing ApiKey."""
        result: list[str] = []
        if not self._services_dir.exists():
            return result
        for entry in self._services_dir.iterdir():
            if entry.is_dir():
                key = self._autodiscover_api_key(entry.name)
                if key:
                    result.append(entry.name)
        return result
