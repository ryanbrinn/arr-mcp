# ADR-0005: AI Provider Strategy

| | |
|---|---|
| **Status** | Accepted |
| **Date** | 2026-06-08 |
| **Issue** | [#134](https://github.com/ryanbrinn/arr-mcp/issues/134) |

## Context

Phase 2 introduces AI-generated narratives in two places: the dashboard insight blocks and the `POST /api/diagnose` contextual diagnostics endpoint. Both need a language model to produce natural language summaries and structured remedy suggestions from structured data.

The question is which model to target and how to couple the code to it.

arr-mcp is a self-hosted tool. Users run it on a home server alongside their media stack. Many users will not have a Claude API subscription, and requiring one would be a hard deployment dependency that breaks the tool for a large fraction of potential users. At the same time, users who do have access to cloud models should be able to use them for higher quality output.

A secondary concern: AI calls must never reach the client. If the browser or MCP client called an AI API directly it would expose API keys and bypass server-side context assembly.

## Decision

All AI calls are made server-side through a single `AIProvider` interface. The concrete provider is selected at startup from an environment variable and is transparent to callers. Three providers are supported:

- **`ollama`** (default): self-hosted Ollama running on the LAN. No cloud dependency, no subscription required. Default model: `llama3.2:3b` — small enough to run on the same machine as the media stack.
- **`anthropic`**: Claude API. Requires `ARR_MCP_ANTHROPIC_API_KEY`. Higher quality output for users who have access.
- **`none`**: disables AI. All AI-powered features degrade to rule-based fallbacks — structured data is always returned, the narrative field is omitted. No feature hard-fails.

The interface:

```python
class AIProvider(Protocol):
    async def complete(self, prompt: str, *, system: str | None = None) -> str: ...
    async def complete_structured(self, prompt: str, schema: dict, *, system: str | None = None) -> dict: ...
```

`complete_structured` is the primary method. It returns a validated dict matching the caller's JSON schema. The provider is responsible for retrying on schema mismatch — callers receive a valid object or a fallback, never an exception.

The provider is constructed once at server startup via `get_provider(settings)` and injected into services. It is never instantiated inline in tool or route code.

## Options considered

### Option A: Hard-code Claude API (rejected)

Simple, but creates a hard subscription dependency. Fails completely for users without a Claude API key. Hostile to the self-hosted ethos of the project.

### Option B: Ollama only (rejected)

Removes the cloud dependency but gives no upgrade path for users who want higher quality output and are willing to pay for it.

### Option C: Configurable provider with Ollama default (chosen)

Works out of the box for self-hosters. Upgrades gracefully to cloud if the user opts in. Degrades gracefully to no AI if neither is configured. Provider abstraction means adding a future provider (e.g. a local OpenAI-compatible endpoint) requires only a new concrete class.

## Consequences

- **Positive**: No cloud account required to run arr-mcp.
- **Positive**: Users with Claude API access get higher quality output by setting one env var.
- **Positive**: All AI features work without any AI configured — `none` degrades to rule-based results.
- **Positive**: AI call path is entirely server-side; no API keys reach the browser or MCP client.
- **Negative**: Ollama must be running separately — it is not bundled with arr-mcp. Users who want AI features without a cloud account must install Ollama independently.
- **Negative**: Output quality on `llama3.2:3b` will be lower than Claude. For diagnostic narratives this is acceptable; for complex reasoning it may not be.
