"""Tests for the AI provider abstraction layer."""

from __future__ import annotations

import json

import httpx
import pytest

from arr_mcp.ai.anthropic import AnthropicProvider
from arr_mcp.ai.null import NullProvider
from arr_mcp.ai.ollama import OllamaProvider
from arr_mcp.ai.provider import AIProvider, get_provider
from arr_mcp.config import Settings

# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


def test_null_provider_implements_protocol() -> None:
    assert isinstance(NullProvider(), AIProvider)


def test_ollama_provider_implements_protocol() -> None:
    provider = OllamaProvider(url="http://localhost:11434", model="llama3.2:3b")
    assert isinstance(provider, AIProvider)


def test_anthropic_provider_implements_protocol() -> None:
    provider = AnthropicProvider(api_key="sk-test", model="claude-haiku-4-5-20251001")
    assert isinstance(provider, AIProvider)


# ---------------------------------------------------------------------------
# get_provider factory
# ---------------------------------------------------------------------------


def test_get_provider_none() -> None:
    settings = Settings(ai_provider="none")
    provider = get_provider(settings)
    assert isinstance(provider, NullProvider)


def test_get_provider_ollama() -> None:
    settings = Settings(ai_provider="ollama")
    provider = get_provider(settings)
    assert isinstance(provider, OllamaProvider)


def test_get_provider_anthropic() -> None:
    settings = Settings(ai_provider="anthropic", anthropic_api_key="sk-test")
    provider = get_provider(settings)
    assert isinstance(provider, AnthropicProvider)


def test_get_provider_anthropic_missing_key() -> None:
    settings = Settings(ai_provider="anthropic", anthropic_api_key="")
    with pytest.raises(ValueError, match="ARR_MCP_ANTHROPIC_API_KEY"):
        get_provider(settings)


def test_get_provider_unknown() -> None:
    settings = Settings(ai_provider="unknown_backend")
    with pytest.raises(ValueError, match="Unknown ARR_MCP_AI_PROVIDER"):
        get_provider(settings)


# ---------------------------------------------------------------------------
# NullProvider
# ---------------------------------------------------------------------------


async def test_null_complete_returns_empty() -> None:
    p = NullProvider()
    result = await p.complete("What is the status?")
    assert result == ""


async def test_null_complete_with_system_returns_empty() -> None:
    p = NullProvider()
    result = await p.complete("prompt", system="system instruction")
    assert result == ""


async def test_null_complete_structured_returns_empty_dict() -> None:
    p = NullProvider()
    result = await p.complete_structured("prompt", {"type": "object"})
    assert result == {}


# ---------------------------------------------------------------------------
# OllamaProvider (mocked HTTP)
# ---------------------------------------------------------------------------


def _ollama_transport(responses: list[tuple[int, object]]) -> httpx.MockTransport:
    """Return a mock transport that cycles through *responses* in order."""
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        idx = min(call_count, len(responses) - 1)
        call_count += 1
        status, body = responses[idx]
        return httpx.Response(status, json=body)

    return httpx.MockTransport(handler)


async def test_ollama_complete_success() -> None:
    transport = _ollama_transport([(200, {"response": "All services healthy."})])
    http = httpx.AsyncClient(transport=transport)
    p = OllamaProvider(url="http://localhost:11434", model="llama3.2:3b", http=http)
    result = await p.complete("Status?")
    assert result == "All services healthy."


async def test_ollama_complete_with_system() -> None:
    transport = _ollama_transport([(200, {"response": "Done."})])
    http = httpx.AsyncClient(transport=transport)
    p = OllamaProvider(url="http://localhost:11434", model="llama3.2:3b", http=http)
    result = await p.complete("prompt", system="You are a diagnostician.")
    assert result == "Done."


async def test_ollama_complete_http_error_returns_empty() -> None:
    transport = _ollama_transport([(500, {"error": "Internal Server Error"})])
    http = httpx.AsyncClient(transport=transport)
    p = OllamaProvider(url="http://localhost:11434", model="llama3.2:3b", http=http)
    result = await p.complete("prompt")
    assert result == ""


async def test_ollama_complete_structured_success() -> None:
    payload = {
        "narrative": "Download failed due to wrong password.",
        "severity": "warning",
    }
    transport = _ollama_transport([(200, {"response": json.dumps(payload)})])
    http = httpx.AsyncClient(transport=transport)
    p = OllamaProvider(url="http://localhost:11434", model="llama3.2:3b", http=http)
    schema: dict[str, object] = {
        "type": "object",
        "properties": {"narrative": {"type": "string"}, "severity": {"type": "string"}},
    }
    result = await p.complete_structured("Diagnose this.", schema)
    assert result == payload


async def test_ollama_complete_structured_retries_on_bad_json() -> None:
    """First two attempts return invalid JSON; third returns valid JSON."""
    valid = {"status": "ok"}
    transport = _ollama_transport(
        [
            (200, {"response": "not json at all"}),
            (200, {"response": "still bad"}),
            (200, {"response": json.dumps(valid)}),
        ]
    )
    http = httpx.AsyncClient(transport=transport)
    p = OllamaProvider(url="http://localhost:11434", model="llama3.2:3b", http=http)
    result = await p.complete_structured("prompt", {})
    assert result == valid


async def test_ollama_complete_structured_all_retries_fail() -> None:
    transport = _ollama_transport([(200, {"response": "bad json"})])
    http = httpx.AsyncClient(transport=transport)
    p = OllamaProvider(url="http://localhost:11434", model="llama3.2:3b", http=http)
    result = await p.complete_structured("prompt", {})
    assert result == {}


# ---------------------------------------------------------------------------
# AnthropicProvider (mocked SDK)
# ---------------------------------------------------------------------------


class _FakeTextBlock:
    type = "text"

    def __init__(self, text: str) -> None:
        self.text = text


class _FakeMessage:
    def __init__(self, text: str) -> None:
        self.content = [_FakeTextBlock(text)]


class _FakeMessages:
    def __init__(self, responses: list[str]) -> None:
        self._responses = iter(responses)

    async def create(self, **kwargs: object) -> _FakeMessage:
        return _FakeMessage(next(self._responses))


class _FakeAnthropicClient:
    def __init__(self, responses: list[str]) -> None:
        self.messages = _FakeMessages(responses)


def _make_anthropic_provider(responses: list[str]) -> AnthropicProvider:
    """Build an AnthropicProvider with a fake underlying client."""
    provider = AnthropicProvider(api_key="sk-test", model="claude-haiku-4-5-20251001")
    provider._client = _FakeAnthropicClient(responses)  # type: ignore[assignment]
    return provider


async def test_anthropic_complete_success() -> None:
    p = _make_anthropic_provider(["Sonarr looks healthy."])
    result = await p.complete("Status?")
    assert result == "Sonarr looks healthy."


async def test_anthropic_complete_structured_success() -> None:
    payload = {"narrative": "All good.", "risk": "low"}
    p = _make_anthropic_provider([json.dumps(payload)])
    result = await p.complete_structured("Diagnose.", {})
    assert result == payload


async def test_anthropic_complete_structured_strips_code_fences() -> None:
    payload = {"status": "ok"}
    fenced = f"```json\n{json.dumps(payload)}\n```"
    p = _make_anthropic_provider([fenced])
    result = await p.complete_structured("prompt", {})
    assert result == payload


async def test_anthropic_complete_structured_retries_on_bad_json() -> None:
    valid = {"health": "good"}
    p = _make_anthropic_provider(["not json", "still bad", json.dumps(valid)])
    result = await p.complete_structured("prompt", {})
    assert result == valid


async def test_anthropic_complete_structured_all_retries_fail() -> None:
    p = _make_anthropic_provider(["bad", "bad", "bad"])
    result = await p.complete_structured("prompt", {})
    assert result == {}
