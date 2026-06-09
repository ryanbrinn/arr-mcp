"""AIProvider protocol and factory.

The configured provider is constructed once at server startup and injected
into any service that needs AI completions. Tool code never instantiates a
provider directly.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from arr_mcp.config import Settings

log = logging.getLogger(__name__)


@runtime_checkable
class AIProvider(Protocol):
    """Protocol for AI completion backends."""

    async def complete(self, prompt: str, *, system: str | None = None) -> str:
        """Return a free-text completion for *prompt*."""
        ...

    async def complete_structured(
        self,
        prompt: str,
        schema: dict[str, object],
        *,
        system: str | None = None,
    ) -> dict[str, object]:
        """Return a structured dict matching *schema* for *prompt*.

        The provider retries internally on JSON parse errors before raising.
        Returns an empty dict when AI is unavailable (NullProvider).
        """
        ...


def get_provider(settings: Settings) -> AIProvider:
    """Construct and return the configured AI provider.

    Reads ``settings.ai_provider`` and builds the matching backend.
    Fails fast at startup if required config (e.g. Anthropic API key) is
    missing.
    """
    match settings.ai_provider:
        case "ollama":
            from arr_mcp.ai.ollama import OllamaProvider

            log.info("AI provider: Ollama (%s @ %s)", settings.ollama_model, settings.ollama_url)
            return OllamaProvider(url=settings.ollama_url, model=settings.ollama_model)
        case "anthropic":
            from arr_mcp.ai.anthropic import AnthropicProvider

            if not settings.anthropic_api_key:
                raise ValueError(
                    "ARR_MCP_ANTHROPIC_API_KEY is required when ARR_MCP_AI_PROVIDER=anthropic"
                )
            log.info("AI provider: Anthropic (%s)", settings.anthropic_model)
            return AnthropicProvider(
                api_key=settings.anthropic_api_key,
                model=settings.anthropic_model,
            )
        case "none":
            from arr_mcp.ai.null import NullProvider

            log.info("AI provider: none (rule-based fallbacks only)")
            return NullProvider()
        case _:
            raise ValueError(
                f"Unknown ARR_MCP_AI_PROVIDER={settings.ai_provider!r}. "
                "Valid values: ollama, anthropic, none"
            )
