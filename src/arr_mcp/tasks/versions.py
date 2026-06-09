"""VersionChecker — automated release tracking and upgrade recommendations."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import anyio
import httpx

if TYPE_CHECKING:
    from arr_mcp.config import Settings

log = logging.getLogger(__name__)

_VERSIONS_FILE = ".arr-mcp-versions.json"
_POLL_INTERVAL_SECONDS = 86_400  # 24 hours
_GITHUB_API = "https://api.github.com/repos/{owner}/{repo}/releases/latest"

# GitHub repo slugs per service
_GITHUB_REPOS: dict[str, str] = {
    "sonarr": "Sonarr/Sonarr",
    "radarr": "Radarr/Radarr",
    "lidarr": "lidarr/Lidarr",
    "prowlarr": "Prowlarr/Prowlarr",
    "readarr": "Readarr/Readarr",
    "sabnzbd": "sabnzbd/sabnzbd",
    "qbittorrent": "qbittorrent/qBittorrent",
}


@dataclass
class UpgradeRecommendation:
    """An available upgrade for a single service."""

    service: str
    current_version: str
    latest_version: str
    release_date: str
    changelog_summary: str
    risk: str  # "major" | "minor" | "patch" | "unknown"
    upgrade_command: str


def _semver_risk(current: str, latest: str) -> str:
    """Return risk level derived from the semver delta between two versions."""

    def _parse(v: str) -> tuple[int, int, int]:
        m = re.match(r"v?(\d+)\.(\d+)\.(\d+)", v)
        if m:
            return int(m.group(1)), int(m.group(2)), int(m.group(3))
        return 0, 0, 0

    cur = _parse(current)
    lat = _parse(latest)
    if cur == (0, 0, 0) or lat == (0, 0, 0):
        return "unknown"
    if lat[0] > cur[0]:
        return "major"
    if lat[1] > cur[1]:
        return "minor"
    if lat[2] > cur[2]:
        return "patch"
    return "unknown"


def _changelog_summary(body: str | None) -> str:
    """Return the first 500 chars of release notes."""
    if not body:
        return ""
    return body[:500].strip()


class VersionStore:
    """Caches version check results in a JSON file."""

    def __init__(self, services_dir: str) -> None:
        self._path = Path(services_dir) / _VERSIONS_FILE

    def load(self) -> dict[str, dict[str, str]]:
        if not self._path.exists():
            return {}
        try:
            loaded: dict[str, dict[str, str]] = json.loads(self._path.read_text())
            return loaded if isinstance(loaded, dict) else {}
        except Exception:
            return {}

    def save(self, data: dict[str, dict[str, str]]) -> None:
        try:
            self._path.write_text(json.dumps(data, indent=2))
        except Exception:
            log.error("Failed to write version cache at %s", self._path)

    def get_recommendations(self) -> list[UpgradeRecommendation]:
        """Return cached upgrade recommendations where latest != current."""
        data = self.load()
        result = []
        for svc, info in data.items():
            current = info.get("current_version", "")
            latest = info.get("latest_version", "")
            if current and latest and current != latest:
                result.append(
                    UpgradeRecommendation(
                        service=svc,
                        current_version=current,
                        latest_version=latest,
                        release_date=info.get("release_date", ""),
                        changelog_summary=info.get("changelog_summary", ""),
                        risk=info.get("risk", "unknown"),
                        upgrade_command=info.get("upgrade_command", ""),
                    )
                )
        return result


class VersionChecker:
    """Background task that polls GitHub releases daily and caches results.

    ``upgrades_available()`` reads from cache and never makes network calls,
    so it responds instantly regardless of when the last poll ran.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings
        self._store = VersionStore(settings.services_dir)
        self._http = http

    async def run(self) -> None:
        """Run the daily poll loop until cancelled."""
        log.info("VersionChecker started (interval=24h)")
        while True:
            try:
                await self._poll()
            except Exception:
                log.exception("VersionChecker poll error")
            await anyio.sleep(_POLL_INTERVAL_SECONDS)

    async def _poll(self) -> None:
        """Fetch running versions and latest releases, update the cache."""
        from arr_mcp.services.base import ServiceNotConfiguredError
        from arr_mcp.services.registry import ServiceRegistry

        registry = ServiceRegistry(self._settings.services_dir)
        cache = self._store.load()
        updated = False

        github_token = None
        try:
            import os

            github_token = os.environ.get("GITHUB_TOKEN")
        except Exception:
            pass

        for service_name in registry.available():
            repo = _GITHUB_REPOS.get(service_name)
            if repo is None:
                continue

            # Get running version from service API
            current_version = ""
            try:
                client = registry.get_client(service_name)
                status_result = await client.system_status()  # type: ignore[attr-defined]
                if status_result.ok and hasattr(status_result.data, "version"):
                    current_version = status_result.data.version  # type: ignore[union-attr]
            except ServiceNotConfiguredError:
                continue
            except Exception:
                log.debug("Could not fetch version for %s", service_name)

            # Fetch latest release from GitHub
            latest_version, release_date, changelog = await self._fetch_github_release(
                repo, token=github_token
            )
            if not latest_version:
                continue

            entry: dict[str, str] = {
                "current_version": current_version,
                "latest_version": latest_version,
                "release_date": release_date,
                "changelog_summary": changelog,
                "risk": _semver_risk(current_version, latest_version),
                "upgrade_command": (
                    f"docker pull linuxserver/{service_name}:latest && "
                    f"docker restart {service_name}"
                ),
                "checked_at": datetime.now(UTC).isoformat(),
            }
            cache[service_name] = entry
            updated = True

        if updated:
            self._store.save(cache)
            log.info("VersionChecker updated cache for %d service(s)", len(cache))

    async def _fetch_github_release(
        self, repo: str, *, token: str | None = None
    ) -> tuple[str, str, str]:
        """Return (version, release_date, changelog_summary) for the latest GitHub release."""
        owner, name = repo.split("/", 1)
        url = _GITHUB_API.format(owner=owner, repo=name)
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        if token:
            headers["Authorization"] = f"Bearer {token}"

        async def _get(client: httpx.AsyncClient) -> tuple[str, str, str]:
            try:
                resp = await client.get(url, headers=headers, timeout=15.0)
                if not resp.is_success:
                    log.debug("GitHub API %s for %s", resp.status_code, repo)
                    return "", "", ""
                data = resp.json()
                version = data.get("tag_name", "").lstrip("v")
                release_date = data.get("published_at", "")[:10]  # YYYY-MM-DD
                changelog = _changelog_summary(data.get("body"))
                return version, release_date, changelog
            except Exception as exc:
                log.debug("GitHub release fetch failed for %s: %s", repo, exc)
                return "", "", ""

        if self._http is not None:
            return await _get(self._http)
        async with httpx.AsyncClient() as client:
            return await _get(client)
