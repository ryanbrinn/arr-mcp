"""Contextual AI diagnostics for the dashboard POST /api/diagnose endpoint."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from arr_mcp.ai.provider import AIProvider

log = logging.getLogger(__name__)

_DIAGNOSE_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "narrative": {"type": "string"},
        "remedies": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "label": {"type": "string"},
                    "tool": {"type": "string"},
                    "args": {"type": "object"},
                },
                "required": ["label", "tool", "args"],
            },
        },
    },
    "required": ["narrative", "remedies"],
}

_SYSTEM_PROMPT = (
    "You are a diagnostic assistant for a home media server running arr applications "
    "(Sonarr, Radarr, SABnzbd, Plex, etc.). "
    "Diagnose the issue concisely (1–2 sentences) and suggest 1–3 actionable remedies. "
    "Return JSON only — no markdown, no explanation outside the JSON object."
)

# Rule-based remedies returned when the AI provider is unavailable or returns nothing.
_FALLBACK_REMEDIES: dict[str, list[dict[str, object]]] = {
    "failed_download": [
        {
            "label": "Blacklist release and search for alternative",
            "tool": "sonarr_search",
            "args": {},
        },
        {"label": "Retry download", "tool": "sabnzbd_retry", "args": {}},
        {"label": "Clear queue item", "tool": "sabnzbd_delete", "args": {}},
    ],
    "container_restart_loop": [
        {"label": "View container logs", "tool": "container_logs", "args": {}},
        {"label": "Restart container", "tool": "container_restart", "args": {}},
    ],
    "service_unreachable": [
        {"label": "Check service health via API", "tool": "service_api_health", "args": {}},
        {"label": "View service logs", "tool": "log_read", "args": {}},
    ],
    "disk_pressure": [
        {"label": "Review disk usage", "tool": "filesystem_disk_usage", "args": {}},
        {
            "label": "Preview watched cleanup candidates",
            "tool": "watched_cleanup_preview",
            "args": {},
        },
    ],
}


def _build_prompt(issue_type: str, context: dict[str, Any]) -> str:
    """Assemble a tight diagnostic prompt from the issue type and context bundle."""
    match issue_type:
        case "failed_download":
            return (
                f"A download has failed.\n"
                f"Item: {context.get('title', 'unknown')}\n"
                f"Error: {context.get('error', 'unknown error')}\n"
                f"Indexer: {context.get('indexer', 'unknown')}\n"
                f"Prior failures: {context.get('failure_count', 0)}\n"
                f"Disk free: {context.get('disk_free_gb', 'unknown')} GB\n\n"
                "Diagnose and suggest remedies as JSON."
            )
        case "container_restart_loop":
            log_lines = "\n".join(context.get("log_lines", [])[:20])
            return (
                f"A container is in a restart loop.\n"
                f"Container: {context.get('name', 'unknown')}\n"
                f"Image: {context.get('image', 'unknown')}\n"
                f"Exit code: {context.get('exit_code', 'unknown')}\n"
                f"Restart count: {context.get('restart_count', 0)}\n"
                f"Recent log lines:\n{log_lines or '(none)'}\n\n"
                "Diagnose and suggest remedies as JSON."
            )
        case "service_unreachable":
            return (
                f"A service is unreachable.\n"
                f"Service: {context.get('service', 'unknown')}\n"
                f"Last reachable: {context.get('last_reachable', 'unknown')}\n"
                f"Port: {context.get('port', 'unknown')}\n"
                f"Container status: {context.get('container_status', 'unknown')}\n\n"
                "Diagnose and suggest remedies as JSON."
            )
        case "disk_pressure":
            top_dirs = "\n".join(
                f"  {d.get('path', '?')}: {d.get('size_gb', '?')} GB"
                for d in context.get("top_dirs", [])[:5]
            )
            return (
                f"Disk pressure detected.\n"
                f"Mount: {context.get('path', 'unknown')}\n"
                f"Used: {context.get('used_pct', 'unknown')}%\n"
                f"Largest directories:\n{top_dirs or '(none)'}\n\n"
                "Diagnose and suggest remedies as JSON."
            )
        case _:
            return (
                f"Issue type: {issue_type}\n"
                f"Context: {context}\n\n"
                "Diagnose and suggest remedies as JSON."
            )


async def diagnose(
    ai_provider: AIProvider,
    issue_type: str,
    context: dict[str, Any],
) -> dict[str, object]:
    """Assemble context, call the AI provider, and return narrative + remedies.

    Falls back to rule-based remedies (no narrative) when the provider is
    unavailable (NullProvider returns empty dict) or returns malformed output.
    """
    prompt = _build_prompt(issue_type, context)

    try:
        result = await ai_provider.complete_structured(
            prompt, _DIAGNOSE_SCHEMA, system=_SYSTEM_PROMPT
        )
    except Exception as exc:
        log.warning("AI diagnose call failed for %s: %s", issue_type, exc)
        result = {}

    if result and "narrative" in result and "remedies" in result:
        return result

    # Graceful degradation — rule-based fallback
    remedies = _FALLBACK_REMEDIES.get(issue_type, [])
    return {"remedies": remedies}
