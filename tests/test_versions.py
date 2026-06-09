"""Tests for VersionChecker and VersionStore."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from arr_mcp.tasks.versions import (
    UpgradeRecommendation,
    VersionChecker,
    VersionStore,
    _semver_risk,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def store(tmp_path):
    return VersionStore(services_dir=str(tmp_path))


@pytest.fixture
def settings(tmp_path):
    from arr_mcp.config import Settings

    return Settings(services_dir=str(tmp_path))


def _github_response(tag: str, body: str = "Release notes") -> dict:
    return {"tag_name": tag, "published_at": "2026-06-01T12:00:00Z", "body": body}


def _mock_http(responses: dict[str, tuple[int, object]]) -> httpx.AsyncClient:
    """Return an AsyncClient whose transport maps URL substrings to responses."""

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        for pattern, (status, body) in responses.items():
            if pattern in url:
                return httpx.Response(status, json=body)
        return httpx.Response(404, json={})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


# ---------------------------------------------------------------------------
# _semver_risk
# ---------------------------------------------------------------------------


def test_risk_major() -> None:
    assert _semver_risk("3.0.0", "4.0.0") == "major"


def test_risk_minor() -> None:
    assert _semver_risk("3.1.0", "3.2.0") == "minor"


def test_risk_patch() -> None:
    assert _semver_risk("3.1.0", "3.1.1") == "patch"


def test_risk_same() -> None:
    assert _semver_risk("3.1.0", "3.1.0") == "unknown"


def test_risk_unparseable() -> None:
    assert _semver_risk("", "v4.0.0") == "unknown"


def test_risk_strips_v_prefix() -> None:
    assert _semver_risk("v3.1.0", "v3.2.0") == "minor"


# ---------------------------------------------------------------------------
# VersionStore
# ---------------------------------------------------------------------------


def test_store_empty_when_no_file(store: VersionStore) -> None:
    assert store.load() == {}
    assert store.get_recommendations() == []


def test_store_save_and_load_round_trip(store: VersionStore) -> None:
    data = {
        "sonarr": {
            "current_version": "4.0.0",
            "latest_version": "4.1.0",
            "release_date": "2026-06-01",
            "changelog_summary": "Bug fixes",
            "risk": "minor",
            "upgrade_command": "docker pull ...",
        }
    }
    store.save(data)
    loaded = store.load()
    assert loaded["sonarr"]["current_version"] == "4.0.0"


def test_get_recommendations_returns_upgrades(store: VersionStore) -> None:
    data = {
        "sonarr": {
            "current_version": "4.0.0",
            "latest_version": "4.1.0",
            "release_date": "2026-06-01",
            "changelog_summary": "Notes",
            "risk": "minor",
            "upgrade_command": "docker pull ...",
        }
    }
    store.save(data)
    recs = store.get_recommendations()
    assert len(recs) == 1
    assert isinstance(recs[0], UpgradeRecommendation)
    assert recs[0].service == "sonarr"
    assert recs[0].risk == "minor"


def test_get_recommendations_excludes_current(store: VersionStore) -> None:
    data = {
        "sonarr": {
            "current_version": "4.1.0",
            "latest_version": "4.1.0",
            "release_date": "2026-06-01",
            "changelog_summary": "",
            "risk": "unknown",
            "upgrade_command": "",
        }
    }
    store.save(data)
    assert store.get_recommendations() == []


def test_get_recommendations_excludes_empty_versions(store: VersionStore) -> None:
    data = {
        "sonarr": {
            "current_version": "",
            "latest_version": "4.1.0",
            "release_date": "2026-06-01",
            "changelog_summary": "",
            "risk": "unknown",
            "upgrade_command": "",
        }
    }
    store.save(data)
    assert store.get_recommendations() == []


# ---------------------------------------------------------------------------
# VersionChecker._fetch_github_release
# ---------------------------------------------------------------------------


async def test_fetch_github_release_success(settings) -> None:
    http = _mock_http({"Sonarr/Sonarr": (200, _github_response("v4.1.0", "- Fix broken thing"))})
    checker = VersionChecker(settings, http=http)
    version, release_date, changelog = await checker._fetch_github_release("Sonarr/Sonarr")
    assert version == "4.1.0"
    assert release_date == "2026-06-01"
    assert "Fix broken thing" in changelog


async def test_fetch_github_release_not_found(settings) -> None:
    http = _mock_http({"Sonarr/Sonarr": (404, {})})
    checker = VersionChecker(settings, http=http)
    version, _, _ = await checker._fetch_github_release("Sonarr/Sonarr")
    assert version == ""


async def test_fetch_github_release_changelog_truncated(settings) -> None:
    long_notes = "X" * 1000
    http = _mock_http({"Sonarr/Sonarr": (200, _github_response("v4.0.0", long_notes))})
    checker = VersionChecker(settings, http=http)
    _, _, changelog = await checker._fetch_github_release("Sonarr/Sonarr")
    assert len(changelog) <= 500


# ---------------------------------------------------------------------------
# VersionChecker._poll
# ---------------------------------------------------------------------------


async def test_poll_updates_cache_for_configured_services(settings) -> None:
    from arr_mcp.services.arr import SystemStatus
    from arr_mcp.services.base import ApiResult

    http = _mock_http({"Sonarr/Sonarr": (200, _github_response("v4.1.0"))})
    checker = VersionChecker(settings, http=http)

    mock_client = AsyncMock()
    mock_client.system_status = AsyncMock(
        return_value=ApiResult(
            ok=True,
            data=SystemStatus(app_name="Sonarr", version="4.0.0", raw={}),
        )
    )

    with (
        patch("arr_mcp.services.registry.ServiceRegistry.get_client", return_value=mock_client),
        patch("arr_mcp.services.registry.ServiceRegistry.available", return_value=["sonarr"]),
    ):
        await checker._poll()

    store = VersionStore(services_dir=settings.services_dir)
    cache = store.load()
    assert "sonarr" in cache
    assert cache["sonarr"]["current_version"] == "4.0.0"
    assert cache["sonarr"]["latest_version"] == "4.1.0"
    assert cache["sonarr"]["risk"] == "minor"


async def test_poll_skips_service_without_github_repo(settings) -> None:
    mock_client = AsyncMock()
    with (
        patch("arr_mcp.services.registry.ServiceRegistry.get_client", return_value=mock_client),
        patch("arr_mcp.services.registry.ServiceRegistry.available", return_value=["plex"]),
    ):
        checker = VersionChecker(settings)
        await checker._poll()

    # plex has no github repo entry, nothing written
    assert VersionStore(services_dir=settings.services_dir).load() == {}


# ---------------------------------------------------------------------------
# MCP tool integration
# ---------------------------------------------------------------------------


async def test_upgrades_available_tool_no_data(tmp_path) -> None:
    from mcp.server.fastmcp import FastMCP

    from arr_mcp.config import Settings
    from arr_mcp.tools.versions import register_version_tools

    mcp = FastMCP("test")
    settings = Settings(services_dir=str(tmp_path))
    register_version_tools(mcp, settings)

    result = await mcp.call_tool("upgrades_available", {})
    assert "up to date" in result[0][0].text


async def test_upgrades_available_tool_with_data(tmp_path) -> None:
    from mcp.server.fastmcp import FastMCP

    from arr_mcp.config import Settings
    from arr_mcp.tools.versions import register_version_tools

    store = VersionStore(services_dir=str(tmp_path))
    store.save(
        {
            "sonarr": {
                "current_version": "4.0.0",
                "latest_version": "4.1.0",
                "release_date": "2026-06-01",
                "changelog_summary": "Minor improvements",
                "risk": "minor",
                "upgrade_command": "docker pull linuxserver/sonarr:latest",
            }
        }
    )

    mcp = FastMCP("test")
    settings = Settings(services_dir=str(tmp_path))
    register_version_tools(mcp, settings)

    result = await mcp.call_tool("upgrades_available", {})
    payload = json.loads(result[0][0].text)
    assert payload["upgrade_count"] == 1
    assert payload["upgrades"][0]["service"] == "sonarr"
    assert payload["upgrades"][0]["risk"] == "minor"
