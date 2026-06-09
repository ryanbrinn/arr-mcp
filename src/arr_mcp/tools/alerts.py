"""MCP tools for alert rule management and recent alert retrieval."""

from __future__ import annotations

import json

from mcp.server.fastmcp import FastMCP
from mcp.types import TextContent

from arr_mcp.config import Settings
from arr_mcp.tasks.alerts import AlertStore


def register_alert_tools(server: FastMCP, settings: Settings) -> None:
    """Register alert management tools with the MCP server."""
    store = AlertStore(settings.services_dir)

    @server.tool()
    async def alert_rules_list() -> list[TextContent]:
        """List configured alert rules and their current settings.

        Returns all rules with their enabled state, threshold, cooldown,
        and last fired timestamp.
        """
        rules = store.get_rules()
        result = {
            "rules": [
                {
                    "name": r.name,
                    "enabled": r.enabled,
                    "threshold": r.threshold,
                    "cooldown_minutes": r.cooldown_minutes,
                    "last_fired_at": r.last_fired_at,
                    "on_cooldown": store.is_on_cooldown(r),
                }
                for r in sorted(rules.values(), key=lambda x: x.name)
            ]
        }
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    @server.tool()
    async def alert_rules_set(
        rule: str,
        enabled: bool | None = None,
        threshold: float | None = None,
        cooldown_minutes: int | None = None,
    ) -> list[TextContent]:
        """Update an alert rule's settings.

        Args:
            rule: Rule name — one of: stuck_download, disk_usage,
                  service_down, log_errors.
            enabled: Enable or disable the rule.
            threshold: New threshold value. Meaning depends on rule:
                stuck_download: minutes before firing (default 60);
                disk_usage: percentage full (default 90);
                service_down: consecutive failures (default 3);
                log_errors: error lines count (default 10).
            cooldown_minutes: Suppress re-fire for N minutes after firing.
        """
        try:
            updated = store.set_rule(
                rule,
                enabled=enabled,
                threshold=threshold,
                cooldown_minutes=cooldown_minutes,
            )
        except ValueError as exc:
            return [TextContent(type="text", text=str(exc))]

        result = {
            "name": updated.name,
            "enabled": updated.enabled,
            "threshold": updated.threshold,
            "cooldown_minutes": updated.cooldown_minutes,
        }
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    @server.tool()
    async def alerts_recent(limit: int = 20) -> list[TextContent]:
        """Return recent fired alerts from the alert log, newest first.

        Args:
            limit: Maximum number of alerts to return (default 20).
        """
        alerts = store.recent_alerts(limit=max(1, limit))
        if not alerts:
            return [TextContent(type="text", text="No recent alerts.")]
        result = {
            "count": len(alerts),
            "alerts": [
                {
                    "rule": a.rule,
                    "service": a.service,
                    "severity": a.severity,
                    "message": a.message,
                    "fired_at": a.fired_at,
                }
                for a in alerts
            ],
        }
        return [TextContent(type="text", text=json.dumps(result, indent=2))]
