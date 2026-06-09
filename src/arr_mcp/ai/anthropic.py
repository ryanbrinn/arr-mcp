"""AnthropicProvider — cloud Claude API backend."""

from __future__ import annotations

import json
import logging

import anthropic as anthropic_sdk

log = logging.getLogger(__name__)

_MAX_RETRIES = 3
_MAX_TOKENS = 1024


class AnthropicProvider:
    """AI provider backed by the Anthropic Messages API.

    Completions use ``claude-haiku-4-5-20251001`` by default (configurable via
    ``ARR_MCP_ANTHROPIC_MODEL``). Structured completions ask for JSON in the
    prompt and retry on parse failure.
    """

    def __init__(self, api_key: str, model: str) -> None:
        self._client = anthropic_sdk.AsyncAnthropic(api_key=api_key)
        self._model = model

    async def complete(self, prompt: str, *, system: str | None = None) -> str:
        """Return a free-text completion from the Anthropic Messages API."""
        kwargs: dict[str, object] = {
            "model": self._model,
            "max_tokens": _MAX_TOKENS,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            kwargs["system"] = system

        try:
            response = await self._client.messages.create(**kwargs)  # type: ignore[arg-type]
            block = response.content[0]
            if block.type == "text":
                return block.text
            return ""
        except anthropic_sdk.APIError as exc:
            log.warning("Anthropic API error: %s", exc)
            return ""

    async def complete_structured(
        self,
        prompt: str,
        schema: dict[str, object],
        *,
        system: str | None = None,
    ) -> dict[str, object]:
        """Return a structured dict from the Anthropic API.

        Asks Claude to respond with JSON matching *schema*. Retries up to
        ``_MAX_RETRIES`` times on JSON parse failure before returning an empty
        dict.
        """
        schema_hint = json.dumps(schema, indent=2)
        full_prompt = (
            f"{prompt}\n\nRespond with a JSON object matching this schema. "
            f"Return only the JSON object, no explanation:\n{schema_hint}"
        )

        for attempt in range(_MAX_RETRIES):
            raw = await self.complete(full_prompt, system=system)
            if not raw:
                continue
            # Strip markdown code fences if present
            cleaned = raw.strip()
            if cleaned.startswith("```"):
                lines = cleaned.split("\n")
                cleaned = "\n".join(lines[1:-1]) if len(lines) > 2 else cleaned
            try:
                result = json.loads(cleaned)
                if isinstance(result, dict):
                    return result
                log.warning("Anthropic returned non-dict JSON (attempt %d)", attempt + 1)
            except json.JSONDecodeError:
                log.warning(
                    "Anthropic returned invalid JSON (attempt %d): %.100s", attempt + 1, raw
                )

        log.error("Anthropic structured completion failed after %d retries", _MAX_RETRIES)
        return {}
