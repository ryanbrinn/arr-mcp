"""NullProvider — rule-based fallback when no AI backend is configured."""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)


class NullProvider:
    """No-op AI provider. Returns empty strings and dicts.

    Used when ``ARR_MCP_AI_PROVIDER=none`` or when the configured backend is
    unreachable. Callers receive graceful degradation: structured data without
    an AI narrative rather than a hard failure.
    """

    async def complete(self, prompt: str, *, system: str | None = None) -> str:
        """Return an empty string — no AI narrative available."""
        return ""

    async def complete_structured(
        self,
        prompt: str,
        schema: dict[str, object],
        *,
        system: str | None = None,
    ) -> dict[str, object]:
        """Return an empty dict — no AI data available."""
        return {}
