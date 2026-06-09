"""OllamaProvider — self-hosted Ollama backend."""

from __future__ import annotations

import json
import logging

import httpx

log = logging.getLogger(__name__)

_MAX_RETRIES = 3


class OllamaProvider:
    """AI provider backed by a local Ollama instance.

    Uses the Ollama generate API (``POST /api/generate``). Structured
    completions request JSON mode and retry up to ``_MAX_RETRIES`` times on
    parse failure.
    """

    def __init__(
        self,
        url: str,
        model: str,
        *,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self._url = url.rstrip("/")
        self._model = model
        self._http = http

    async def complete(self, prompt: str, *, system: str | None = None) -> str:
        """Return a free-text completion from Ollama."""
        payload: dict[str, object] = {
            "model": self._model,
            "prompt": prompt,
            "stream": False,
        }
        if system:
            payload["system"] = system

        return await self._generate(payload)

    async def complete_structured(
        self,
        prompt: str,
        schema: dict[str, object],
        *,
        system: str | None = None,
    ) -> dict[str, object]:
        """Return a structured dict from Ollama with JSON mode enabled.

        Retries up to ``_MAX_RETRIES`` times if the response is not valid JSON.
        Returns an empty dict if all retries are exhausted.
        """
        schema_hint = json.dumps(schema, indent=2)
        full_prompt = f"{prompt}\n\nRespond with a JSON object matching this schema:\n{schema_hint}"
        payload: dict[str, object] = {
            "model": self._model,
            "prompt": full_prompt,
            "stream": False,
            "format": "json",
        }
        if system:
            payload["system"] = system

        for attempt in range(_MAX_RETRIES):
            raw = await self._generate(payload)
            try:
                result = json.loads(raw)
                if isinstance(result, dict):
                    return result
                log.warning("Ollama returned non-dict JSON (attempt %d)", attempt + 1)
            except json.JSONDecodeError:
                log.warning("Ollama returned invalid JSON (attempt %d): %.100s", attempt + 1, raw)

        log.error("Ollama structured completion failed after %d retries", _MAX_RETRIES)
        return {}

    async def _generate(self, payload: dict[str, object]) -> str:
        """POST to /api/generate and return the response text."""
        url = f"{self._url}/api/generate"

        async def _send(client: httpx.AsyncClient) -> str:
            try:
                resp = await client.post(url, json=payload, timeout=60.0)
                resp.raise_for_status()
                data = resp.json()
                return str(data.get("response", ""))
            except httpx.HTTPError as exc:
                log.warning("Ollama request failed: %s", exc)
                return ""
            except Exception as exc:
                log.warning("Ollama unexpected error: %s", exc)
                return ""

        if self._http is not None:
            return await _send(self._http)
        async with httpx.AsyncClient() as client:
            return await _send(client)
