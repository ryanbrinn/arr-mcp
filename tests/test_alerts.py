"""Tests for AlertWatcher and AlertStore."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from arr_mcp.tasks.alerts import (
    RULE_DISK_USAGE,
    RULE_LOG_ERRORS,
    RULE_SERVICE_DOWN,
    RULE_STUCK_DOWNLOAD,
    AlertEntry,
    AlertRule,
    AlertStore,
    AlertWatcher,
    _now_iso,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def store(tmp_path):
    return AlertStore(services_dir=str(tmp_path))


@pytest.fixture
def settings(tmp_path):
    from arr_mcp.config import Settings

    return Settings(
        services_dir=str(tmp_path),
        media_dir=str(tmp_path),
        alert_interval_seconds=1,
    )


# ---------------------------------------------------------------------------
# AlertStore — rules
# ---------------------------------------------------------------------------


def test_get_rules_returns_all_defaults(store: AlertStore) -> None:
    rules = store.get_rules()
    assert RULE_STUCK_DOWNLOAD in rules
    assert RULE_DISK_USAGE in rules
    assert RULE_SERVICE_DOWN in rules
    assert RULE_LOG_ERRORS in rules


def test_get_rules_defaults_enabled(store: AlertStore) -> None:
    rules = store.get_rules()
    assert all(r.enabled for r in rules.values())


def test_set_rule_updates_enabled(store: AlertStore) -> None:
    store.set_rule(RULE_DISK_USAGE, enabled=False)
    rules = store.get_rules()
    assert rules[RULE_DISK_USAGE].enabled is False


def test_set_rule_updates_threshold(store: AlertStore) -> None:
    store.set_rule(RULE_DISK_USAGE, threshold=95.0)
    rules = store.get_rules()
    assert rules[RULE_DISK_USAGE].threshold == 95.0


def test_set_rule_updates_cooldown(store: AlertStore) -> None:
    store.set_rule(RULE_STUCK_DOWNLOAD, cooldown_minutes=120)
    rules = store.get_rules()
    assert rules[RULE_STUCK_DOWNLOAD].cooldown_minutes == 120


def test_set_rule_unknown_raises(store: AlertStore) -> None:
    with pytest.raises(ValueError, match="Unknown rule"):
        store.set_rule("nonexistent_rule")


def test_set_rule_persists_across_instances(tmp_path) -> None:
    store1 = AlertStore(services_dir=str(tmp_path))
    store1.set_rule(RULE_DISK_USAGE, threshold=85.0)
    store2 = AlertStore(services_dir=str(tmp_path))
    assert store2.get_rules()[RULE_DISK_USAGE].threshold == 85.0


# ---------------------------------------------------------------------------
# AlertStore — cooldown
# ---------------------------------------------------------------------------


def test_not_on_cooldown_when_never_fired(store: AlertStore) -> None:
    rule = AlertRule(name=RULE_DISK_USAGE, cooldown_minutes=60, last_fired_at=None)
    assert store.is_on_cooldown(rule) is False


def test_on_cooldown_when_recently_fired(store: AlertStore) -> None:
    recent = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
    rule = AlertRule(name=RULE_DISK_USAGE, cooldown_minutes=60, last_fired_at=recent)
    assert store.is_on_cooldown(rule) is True


def test_not_on_cooldown_when_expired(store: AlertStore) -> None:
    old = (datetime.now(UTC) - timedelta(minutes=90)).isoformat()
    rule = AlertRule(name=RULE_DISK_USAGE, cooldown_minutes=60, last_fired_at=old)
    assert store.is_on_cooldown(rule) is False


def test_update_last_fired_records_time(store: AlertStore) -> None:
    store.update_last_fired(RULE_DISK_USAGE)
    rules = store.get_rules()
    assert rules[RULE_DISK_USAGE].last_fired_at is not None


# ---------------------------------------------------------------------------
# AlertStore — alert log
# ---------------------------------------------------------------------------


def test_append_and_retrieve_alert(store: AlertStore) -> None:
    entry = AlertEntry(
        rule=RULE_DISK_USAGE,
        service="/media",
        severity="warning",
        message="Disk at 92%",
        fired_at=_now_iso(),
    )
    store.append_alert(entry)
    alerts = store.recent_alerts(limit=10)
    assert len(alerts) == 1
    assert alerts[0].rule == RULE_DISK_USAGE
    assert alerts[0].message == "Disk at 92%"


def test_recent_alerts_returns_newest_first(store: AlertStore) -> None:
    for i in range(3):
        store.append_alert(
            AlertEntry(
                rule=RULE_DISK_USAGE,
                service="/media",
                severity="warning",
                message=f"Alert {i}",
                fired_at=_now_iso(),
            )
        )
    alerts = store.recent_alerts(limit=10)
    messages = [a.message for a in alerts]
    assert messages == list(reversed(messages)) or messages == [
        "Alert 2",
        "Alert 1",
        "Alert 0",
    ]


def test_recent_alerts_respects_limit(store: AlertStore) -> None:
    for i in range(5):
        store.append_alert(
            AlertEntry(
                rule=RULE_DISK_USAGE,
                service="/media",
                severity="warning",
                message=f"Alert {i}",
                fired_at=_now_iso(),
            )
        )
    assert len(store.recent_alerts(limit=3)) == 3


def test_recent_alerts_empty_when_no_log(store: AlertStore) -> None:
    assert store.recent_alerts() == []


def test_old_alerts_excluded(store: AlertStore) -> None:
    old_time = (datetime.now(UTC) - timedelta(days=31)).isoformat()
    line = json.dumps(
        {
            "rule": RULE_DISK_USAGE,
            "service": "/media",
            "severity": "warning",
            "message": "old",
            "fired_at": old_time,
        }
    )
    (store._log_path).write_text(line + "\n")
    assert store.recent_alerts() == []


# ---------------------------------------------------------------------------
# AlertWatcher — disk usage rule
# ---------------------------------------------------------------------------


async def test_watcher_fires_disk_usage_when_above_threshold(settings) -> None:
    watcher = AlertWatcher(settings)
    store = AlertStore(settings.services_dir)
    store.set_rule(RULE_DISK_USAGE, threshold=0.0)  # always fire

    # Patch disk_usage to return 95% used
    fake_usage = type("U", (), {"used": 95, "total": 100, "free": 5})()
    with patch("shutil.disk_usage", return_value=fake_usage):
        rules = store.get_rules()
        await watcher._check_disk_usage(rules[RULE_DISK_USAGE])

    alerts = store.recent_alerts()
    assert len(alerts) == 1
    assert alerts[0].rule == RULE_DISK_USAGE
    assert "95.0%" in alerts[0].message


async def test_watcher_skips_disk_usage_below_threshold(settings) -> None:
    watcher = AlertWatcher(settings)
    store = AlertStore(settings.services_dir)

    fake_usage = type("U", (), {"used": 50, "total": 100, "free": 50})()
    with patch("shutil.disk_usage", return_value=fake_usage):
        rules = store.get_rules()
        await watcher._check_disk_usage(rules[RULE_DISK_USAGE])

    assert store.recent_alerts() == []


# ---------------------------------------------------------------------------
# AlertWatcher — stuck download rule
# ---------------------------------------------------------------------------


async def test_watcher_fires_stuck_download_for_stalled_items(settings) -> None:
    from arr_mcp.services.arr import QueueItem
    from arr_mcp.services.base import ApiResult

    watcher = AlertWatcher(settings)
    stalled = QueueItem(
        id=1,
        title="Show S01E01",
        status="warning",
        tracked_download_state="importFailed",
        size_left_bytes=100,
        raw={},
    )

    mock_client = AsyncMock()
    mock_client.get_queue = AsyncMock(return_value=ApiResult(ok=True, data=[stalled]))

    with (
        patch(
            "arr_mcp.services.registry.ServiceRegistry.get_client",
            return_value=mock_client,
        ),
        patch(
            "arr_mcp.services.registry.ServiceRegistry.available",
            return_value=["sonarr"],
        ),
    ):
        from arr_mcp.tasks.alerts import AlertRule

        rule = AlertRule(
            name=RULE_STUCK_DOWNLOAD, enabled=True, threshold=60, cooldown_minutes=60
        )
        await watcher._check_stuck_downloads(rule)

    store = AlertStore(settings.services_dir)
    alerts = store.recent_alerts()
    assert len(alerts) == 1
    assert alerts[0].rule == RULE_STUCK_DOWNLOAD


# ---------------------------------------------------------------------------
# AlertWatcher — service down rule
# ---------------------------------------------------------------------------


async def test_watcher_fires_service_down_after_threshold_failures(settings) -> None:
    from arr_mcp.services.base import ApiResult

    watcher = AlertWatcher(settings)
    mock_client = AsyncMock()
    mock_client.health = AsyncMock(
        return_value=ApiResult(ok=False, error="unreachable")
    )

    with (
        patch(
            "arr_mcp.services.registry.ServiceRegistry.get_client",
            return_value=mock_client,
        ),
        patch(
            "arr_mcp.services.registry.ServiceRegistry.available",
            return_value=["sonarr"],
        ),
    ):
        rule = AlertRule(
            name=RULE_SERVICE_DOWN, enabled=True, threshold=3, cooldown_minutes=30
        )
        # Simulate 3 consecutive failures
        for _ in range(3):
            await watcher._check_service_down(rule)

    store = AlertStore(settings.services_dir)
    alerts = store.recent_alerts()
    assert len(alerts) == 1
    assert alerts[0].rule == RULE_SERVICE_DOWN
    assert alerts[0].severity == "critical"


async def test_watcher_resets_failure_count_on_recovery(settings) -> None:
    from arr_mcp.services.base import ApiResult

    watcher = AlertWatcher(settings)
    mock_client = AsyncMock()

    with (
        patch(
            "arr_mcp.services.registry.ServiceRegistry.get_client",
            return_value=mock_client,
        ),
        patch(
            "arr_mcp.services.registry.ServiceRegistry.available",
            return_value=["sonarr"],
        ),
    ):
        rule = AlertRule(
            name=RULE_SERVICE_DOWN, enabled=True, threshold=3, cooldown_minutes=30
        )
        # 2 failures
        mock_client.health = AsyncMock(return_value=ApiResult(ok=False, error="down"))
        await watcher._check_service_down(rule)
        await watcher._check_service_down(rule)
        assert watcher._consecutive_failures.get("sonarr", 0) == 2

        # Recovery — counter resets
        mock_client.health = AsyncMock(return_value=ApiResult(ok=True, data={}))
        await watcher._check_service_down(rule)
        assert watcher._consecutive_failures.get("sonarr", 0) == 0


# ---------------------------------------------------------------------------
# AlertWatcher — log errors rule
# ---------------------------------------------------------------------------


async def test_watcher_fires_log_errors_when_threshold_exceeded(
    settings, tmp_path
) -> None:
    watcher = AlertWatcher(settings)
    store = AlertStore(settings.services_dir)
    store.set_rule(RULE_LOG_ERRORS, threshold=2.0)

    # Create a fake log file with error lines
    log_file = tmp_path / "sonarr.txt"
    log_file.write_text("[Error] Something bad\n[Error] Another error\n[Info] Normal\n")

    rules = store.get_rules()
    await watcher._check_log_errors(rules[RULE_LOG_ERRORS])

    alerts = store.recent_alerts()
    assert len(alerts) == 1
    assert alerts[0].rule == RULE_LOG_ERRORS


# ---------------------------------------------------------------------------
# MCP tools integration
# ---------------------------------------------------------------------------


async def test_alert_rules_list_tool(tmp_path) -> None:
    from mcp.server.fastmcp import FastMCP

    from arr_mcp.config import Settings
    from arr_mcp.tools.alerts import register_alert_tools

    mcp = FastMCP("test")
    settings = Settings(services_dir=str(tmp_path))
    register_alert_tools(mcp, settings)

    result = await mcp.call_tool("alert_rules_list", {})
    payload = json.loads(result[0][0].text)
    assert "rules" in payload
    names = [r["name"] for r in payload["rules"]]
    assert RULE_DISK_USAGE in names


async def test_alert_rules_set_tool(tmp_path) -> None:
    from mcp.server.fastmcp import FastMCP

    from arr_mcp.config import Settings
    from arr_mcp.tools.alerts import register_alert_tools

    mcp = FastMCP("test")
    settings = Settings(services_dir=str(tmp_path))
    register_alert_tools(mcp, settings)

    result = await mcp.call_tool(
        "alert_rules_set",
        {"rule": RULE_DISK_USAGE, "threshold": 85.0, "enabled": False},
    )
    payload = json.loads(result[0][0].text)
    assert payload["threshold"] == 85.0
    assert payload["enabled"] is False


async def test_alerts_recent_tool_empty(tmp_path) -> None:
    from mcp.server.fastmcp import FastMCP

    from arr_mcp.config import Settings
    from arr_mcp.tools.alerts import register_alert_tools

    mcp = FastMCP("test")
    settings = Settings(services_dir=str(tmp_path))
    register_alert_tools(mcp, settings)

    result = await mcp.call_tool("alerts_recent", {})
    assert "No recent alerts" in result[0][0].text


async def test_alerts_recent_tool_with_data(tmp_path) -> None:
    from mcp.server.fastmcp import FastMCP

    from arr_mcp.config import Settings
    from arr_mcp.tools.alerts import register_alert_tools

    mcp = FastMCP("test")
    settings = Settings(services_dir=str(tmp_path))
    store = AlertStore(services_dir=str(tmp_path))
    store.append_alert(
        AlertEntry(
            rule=RULE_DISK_USAGE,
            service="/media",
            severity="warning",
            message="Disk at 92%",
            fired_at=_now_iso(),
        )
    )
    register_alert_tools(mcp, settings)

    result = await mcp.call_tool("alerts_recent", {"limit": 5})
    payload = json.loads(result[0][0].text)
    assert payload["count"] == 1
    assert payload["alerts"][0]["rule"] == RULE_DISK_USAGE
