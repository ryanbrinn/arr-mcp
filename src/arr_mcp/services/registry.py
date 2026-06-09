"""ServiceRegistry — builds typed service clients from KNOWN_SERVICES + CredentialStore."""  # noqa: E501

from __future__ import annotations

import logging
from pathlib import Path

import httpx

from arr_mcp.services.arr import ArrClient
from arr_mcp.services.base import BaseServiceClient, ServiceNotConfiguredError
from arr_mcp.services.credentials import CredentialStore
from arr_mcp.services.plex import PlexClient
from arr_mcp.services.radarr import RadarrClient
from arr_mcp.services.sonarr import SonarrClient
from arr_mcp.tools.services import KNOWN_SERVICES, parse_xml_config

log = logging.getLogger(__name__)

# Mapping from service name to its specific client class
_CLIENT_MAP: dict[str, type[BaseServiceClient]] = {
    "sonarr": SonarrClient,
    "radarr": RadarrClient,
    "lidarr": ArrClient,
    "prowlarr": ArrClient,
    "readarr": ArrClient,
    "plex": PlexClient,
}


def _resolve_base_url(service: str, services_dir: str, store: CredentialStore) -> str:
    """Derive the base URL for a service.

    Priority:
    1. Stored credential's base_url override
    2. Port read from local XML config
    3. Default port from KNOWN_SERVICES
    """
    cred = store.get(service)
    if cred and cred.base_url:
        return cred.base_url.rstrip("/")

    info = KNOWN_SERVICES.get(service)
    if info is None:
        raise ServiceNotConfiguredError(f"Unknown service: {service!r}")

    port: int | str | None = info.default_port

    # Try to read the actual configured port from XML config
    if info.config_format == "xml" and info.port_xml_key:
        config_path = Path(services_dir) / service / info.config_file
        if config_path.exists():
            try:
                cfg = parse_xml_config(config_path)
                raw_port = cfg.get(info.port_xml_key, "").strip()
                if raw_port.isdigit():
                    port = int(raw_port)
            except Exception:
                pass

    if port is None:
        raise ServiceNotConfiguredError(
            f"Cannot determine port for {service!r} — set base_url in credential_set."
        )

    return f"http://{service}:{port}"


class ServiceRegistry:
    """Factory for typed service clients.

    Each call to ``get_client`` returns a fresh client instance. Clients are
    not cached because credentials and ports can change at runtime.
    """

    def __init__(
        self,
        services_dir: str,
        *,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self._services_dir = services_dir
        self._store = CredentialStore(services_dir)
        self._http = http

    def get_client(self, name: str) -> BaseServiceClient:
        """Return a configured client for the named service.

        Raises:
            ServiceNotConfiguredError: if no credential can be resolved.
        """
        name = name.lower()
        cred = self._store.get(name)
        if cred is None:
            raise ServiceNotConfiguredError(
                f"No credential configured for {name!r}. "
                f"Use credential_set to add one, or set the "
                f"{name.upper()}_API_KEY environment variable."
            )

        base_url = _resolve_base_url(name, self._services_dir, self._store)
        client_cls = _CLIENT_MAP.get(name, BaseServiceClient)
        return client_cls(base_url, cred.api_key, http=self._http)

    def available(self) -> list[str]:
        """Return names of services that have credentials configured."""
        return self._store.list_configured()
