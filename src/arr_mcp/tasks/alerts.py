"""AlertWatcher — background threshold monitoring and alert log."""

from __future__ import annotations

import json
import logging
import shutil
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import anyio

if TYPE_CHECKING:
    from arr_mcp.config import Settings

log = logging.getLogger(__name__)

_RULES_FILE = ".arr-mcp-alerts.json"
_LOG_FILE = ".arr-mcp-alert-log.jsonl"
_LOG_RETENTION_DAYS = 30

# Rule names
RULE_STUCK_DOWNLOAD = "stuck_download"
RULE_DISK_USAGE = "disk_usage"
RULE_SERVICE_DOWN = "service_down"
RULE_LOG_ERRORS = "log_errors"

# Stalled/warning queue statuses
_STALLED_STATUSES = {"warning", "failed"}
_STALLED_DOWNLOAD_STATES = {"importFailed", "importFailedNotADirectory", "importPending"}


@dataclass
class AlertRule:
    """Configuration for a single alert rule."""

    name: str
    enabled: bool = True
    threshold: float = 0.0
    cooldown_minutes: int = 60
    last_fired_at: str | None = None


@dataclass
class AlertEntry:
    """A single fired alert stored in the log."""

    rule: str
    service: str
    severity: str
    message: str
    fired_at: str


_RULE_DEFAULTS: dict[str, AlertRule] = {
    RULE_STUCK_DOWNLOAD: AlertRule(
        name=RULE_STUCK_DOWNLOAD, enabled=True, threshold=60, cooldown_minutes=60
    ),
    RULE_DISK_USAGE: AlertRule(
        name=RULE_DISK_USAGE, enabled=True, threshold=90, cooldown_minutes=60
    ),
    RULE_SERVICE_DOWN: AlertRule(
        name=RULE_SERVICE_DOWN, enabled=True, threshold=3, cooldown_minutes=30
    ),
    RULE_LOG_ERRORS: AlertRule(
        name=RULE_LOG_ERRORS, enabled=True, threshold=10, cooldown_minutes=30
    ),
}


class AlertStore:
    """Persists alert rules and the fired-alert log."""

    def __init__(self, services_dir: str) -> None:
        self._dir = Path(services_dir)
        self._rules_path = self._dir / _RULES_FILE
        self._log_path = self._dir / _LOG_FILE

    # ------------------------------------------------------------------
    # Rules
    # ------------------------------------------------------------------

    def get_rules(self) -> dict[str, AlertRule]:
        """Return all rules, merging persisted overrides with defaults."""
        stored = self._read_rules()
        rules: dict[str, AlertRule] = {}
        for name, default in _RULE_DEFAULTS.items():
            override = stored.get(name)
            if override:
                rules[name] = AlertRule(**override)  # type: ignore[arg-type]
            else:
                rules[name] = AlertRule(**asdict(default))
        return rules

    def set_rule(
        self,
        name: str,
        *,
        enabled: bool | None = None,
        threshold: float | None = None,
        cooldown_minutes: int | None = None,
    ) -> AlertRule:
        """Update one or more fields of a rule and persist."""
        if name not in _RULE_DEFAULTS:
            raise ValueError(f"Unknown rule {name!r}. Valid: {list(_RULE_DEFAULTS)}")
        rules = self.get_rules()
        rule = rules[name]
        if enabled is not None:
            rule.enabled = enabled
        if threshold is not None:
            rule.threshold = threshold
        if cooldown_minutes is not None:
            rule.cooldown_minutes = cooldown_minutes
        stored = self._read_rules()
        stored[name] = asdict(rule)
        self._write_rules(stored)
        return rule

    def update_last_fired(self, rule_name: str) -> None:
        """Record the current time as last_fired_at for *rule_name*."""
        stored = self._read_rules()
        entry = stored.get(rule_name, asdict(_RULE_DEFAULTS[rule_name]))
        entry["last_fired_at"] = _now_iso()
        stored[rule_name] = entry
        self._write_rules(stored)

    def is_on_cooldown(self, rule: AlertRule) -> bool:
        """Return True when the rule has fired within its cooldown window."""
        if rule.last_fired_at is None:
            return False
        try:
            fired = datetime.fromisoformat(rule.last_fired_at)
            return datetime.now(UTC) - fired < timedelta(minutes=rule.cooldown_minutes)
        except ValueError:
            return False

    # ------------------------------------------------------------------
    # Alert log
    # ------------------------------------------------------------------

    def append_alert(self, entry: AlertEntry) -> None:
        """Append a fired alert to the JSONL log."""
        try:
            with self._log_path.open("a") as f:
                f.write(json.dumps(asdict(entry)) + "\n")
        except Exception:
            log.error("Failed to write alert log at %s", self._log_path)

    def recent_alerts(self, limit: int = 20) -> list[AlertEntry]:
        """Return the most recent *limit* alerts, newest first."""
        if not self._log_path.exists():
            return []
        try:
            lines = self._log_path.read_text().splitlines()
        except Exception:
            return []

        # Purge old lines (> 30 days) while reading
        cutoff = datetime.now(UTC) - timedelta(days=_LOG_RETENTION_DAYS)
        valid: list[dict[str, str]] = []
        for line in lines:
            try:
                entry = json.loads(line)
                fired = datetime.fromisoformat(entry.get("fired_at", ""))
                if fired >= cutoff:
                    valid.append(entry)
            except (json.JSONDecodeError, ValueError):
                continue

        return [AlertEntry(**e) for e in reversed(valid[-limit:])]

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    def _read_rules(self) -> dict[str, dict[str, object]]:
        if not self._rules_path.exists():
            return {}
        try:
            loaded: dict[str, dict[str, object]] = json.loads(self._rules_path.read_text())
            return loaded if isinstance(loaded, dict) else {}
        except Exception:
            return {}

    def _write_rules(self, data: dict[str, dict[str, object]]) -> None:
        try:
            self._rules_path.write_text(json.dumps(data, indent=2))
        except Exception:
            log.error("Failed to write alert rules at %s", self._rules_path)


class AlertWatcher:
    """Background task that evaluates alert rules on a schedule.

    Start it with ``anyio.create_task_group().start_soon(watcher.run)``.
    The task runs until its surrounding cancel scope is cancelled (e.g. at
    server shutdown).
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._store = AlertStore(settings.services_dir)
        self._interval = settings.alert_interval_seconds
        # In-memory consecutive failure counters for service_down rule
        self._consecutive_failures: dict[str, int] = {}

    async def run(self) -> None:
        """Run the poll loop until cancelled."""
        log.info("AlertWatcher started (interval=%ds)", self._interval)
        while True:
            try:
                await self._poll()
            except Exception:
                log.exception("AlertWatcher poll error")
            await anyio.sleep(self._interval)

    async def _poll(self) -> None:
        """Evaluate all enabled rules and fire alerts when thresholds are crossed."""
        rules = self._store.get_rules()

        async with anyio.create_task_group() as tg:
            for rule in rules.values():
                if rule.enabled and not self._store.is_on_cooldown(rule):
                    tg.start_soon(self._evaluate_rule, rule)

    async def _evaluate_rule(self, rule: AlertRule) -> None:
        """Evaluate a single rule and fire an alert if warranted."""
        match rule.name:
            case "stuck_download":
                await self._check_stuck_downloads(rule)
            case "disk_usage":
                await self._check_disk_usage(rule)
            case "service_down":
                await self._check_service_down(rule)
            case "log_errors":
                await self._check_log_errors(rule)

    # ------------------------------------------------------------------
    # Rule implementations
    # ------------------------------------------------------------------

    async def _check_stuck_downloads(self, rule: AlertRule) -> None:
        """Fire when any queue item is in a stalled or warning state."""
        from arr_mcp.services.arr import QueueItem
        from arr_mcp.services.base import ServiceNotConfiguredError
        from arr_mcp.services.registry import ServiceRegistry

        registry = ServiceRegistry(self._settings.services_dir)
        stalled: list[str] = []

        for service_name in ("sonarr", "radarr"):
            try:
                client = registry.get_client(service_name)
                result = await client.get_queue()  # type: ignore[attr-defined]
                if not result.ok or not isinstance(result.data, list):
                    continue
                for item in result.data:
                    if not isinstance(item, QueueItem):
                        continue
                    if (
                        item.status.lower() in _STALLED_STATUSES
                        or item.tracked_download_state in _STALLED_DOWNLOAD_STATES
                    ):
                        stalled.append(f"{service_name}/{item.title}")
            except ServiceNotConfiguredError:
                continue
            except Exception:
                log.warning("stuck_download check failed for %s", service_name, exc_info=True)

        if stalled:
            self._fire(
                rule,
                service="sonarr/radarr",
                severity="warning",
                message=f"{len(stalled)} stalled download(s): {', '.join(stalled[:3])}",
            )

    async def _check_disk_usage(self, rule: AlertRule) -> None:
        """Fire when any monitored directory exceeds the threshold percentage."""
        dirs_to_check = [self._settings.services_dir, self._settings.media_dir]
        for dir_path in dirs_to_check:
            p = Path(dir_path)
            if not p.exists():
                continue
            try:
                usage = await anyio.to_thread.run_sync(lambda: shutil.disk_usage(str(p)))
                pct = 100.0 * usage.used / usage.total if usage.total > 0 else 0.0
                if pct >= rule.threshold:
                    self._fire(
                        rule,
                        service=dir_path,
                        severity="warning",
                        message=f"Disk usage at {pct:.1f}% (threshold {rule.threshold:.0f}%)",
                    )
                    return  # one alert per poll cycle is enough
            except Exception:
                log.warning("disk_usage check failed for %s", dir_path, exc_info=True)

    async def _check_service_down(self, rule: AlertRule) -> None:
        """Fire when a service has been unreachable for threshold consecutive polls."""
        from arr_mcp.services.base import ServiceNotConfiguredError
        from arr_mcp.services.registry import ServiceRegistry

        registry = ServiceRegistry(self._settings.services_dir)
        for service_name in registry.available():
            try:
                client = registry.get_client(service_name)
                result = await client.health()
                if result.ok:
                    self._consecutive_failures.pop(service_name, None)
                else:
                    self._consecutive_failures[service_name] = (
                        self._consecutive_failures.get(service_name, 0) + 1
                    )
            except ServiceNotConfiguredError:
                continue
            except Exception:
                self._consecutive_failures[service_name] = (
                    self._consecutive_failures.get(service_name, 0) + 1
                )

        for svc, count in list(self._consecutive_failures.items()):
            if count >= rule.threshold:
                self._fire(
                    rule,
                    service=svc,
                    severity="critical",
                    message=f"{svc} has been unreachable for {count} consecutive polls",
                )
                self._consecutive_failures.pop(svc, None)

    async def _check_log_errors(self, rule: AlertRule) -> None:
        """Fire when recent error lines across service logs exceed the threshold."""
        services_path = Path(self._settings.services_dir)
        if not services_path.exists():
            return

        total_errors = 0
        try:
            for log_file in services_path.rglob("*.txt"):
                try:
                    text = await anyio.to_thread.run_sync(log_file.read_text)
                    errors = sum(
                        1 for line in text.splitlines() if "[Error]" in line or "[Fatal]" in line
                    )
                    total_errors += errors
                    if total_errors >= rule.threshold:
                        break
                except Exception:
                    continue
        except Exception:
            return

        if total_errors >= rule.threshold:
            self._fire(
                rule,
                service="logs",
                severity="warning",
                message=f"{total_errors} error line(s) detected in service logs",
            )

    # ------------------------------------------------------------------
    # Helper
    # ------------------------------------------------------------------

    def _fire(self, rule: AlertRule, *, service: str, severity: str, message: str) -> None:
        entry = AlertEntry(
            rule=rule.name,
            service=service,
            severity=severity,
            message=message,
            fired_at=_now_iso(),
        )
        self._store.append_alert(entry)
        self._store.update_last_fired(rule.name)
        log.warning("Alert fired [%s/%s]: %s", rule.name, service, message)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()
