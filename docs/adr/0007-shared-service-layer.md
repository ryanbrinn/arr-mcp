# ADR-0007: Shared Service Layer for MCP Tools and Dashboard

| | |
|---|---|
| **Status** | Accepted |
| **Date** | 2026-06-08 |
| **Issue** | [#132](https://github.com/ryanbrinn/arr-mcp/issues/132), [#133](https://github.com/ryanbrinn/arr-mcp/issues/133) |

## Context

Phase 2 introduces a two-tab dashboard with active controls (content cleanup, interest state management, AI diagnostics) alongside the existing MCP tool surface. Both surfaces need to trigger the same underlying operations — for example, the dashboard's "Diagnose" button and the `service_diagnose_ai` MCP tool must produce identical results from identical inputs.

Without an explicit architectural rule, business logic tends to drift into whichever layer is being worked on at the time — a route handler here, a tool function there. This leads to duplicated logic, divergent behaviour between the dashboard and MCP surfaces, and tests that only cover one path.

A secondary concern is agentic efficiency: if Claude must chain many small tool calls to accomplish a task, each round-trip consumes context window and latency. Complex operations that require joining data from multiple sources should be pre-packaged as compound tools that return a single rich result.

## Decision

All business logic lives in `src/arr_mcp/services/`. The MCP tool layer (`src/arr_mcp/tools/`) and the dashboard HTTP route layer (`src/arr_mcp/dashboard/routes.py`) are thin adapters that call service functions — they contain no logic of their own.

```
services/    ← pure Python, no HTTP, no MCP — business logic only
tools/       ← MCP adapter: thin wrappers that call service functions
dashboard/   ← HTTP adapter: thin wrappers that call the same service functions
```

**The rule:** before adding any dashboard feature, confirm the MCP tool analog exists. Build the service function first, then wire both surfaces. Logic is never duplicated between tools and routes.

**Compound tools** are the preferred pattern for multi-step operations. A compound tool pre-joins context from multiple service calls and returns a single rich result. Claude orchestrates intent; the tool handles complexity. `service_health_report` and `service_diagnose_ai` are examples of this pattern.

## Options considered

### Option A: Logic in route handlers and tool functions (rejected)

Each surface owns its logic. Simpler in the short term, but produces duplication immediately as Phase 2 features are built. The dashboard and MCP tool for the same feature inevitably diverge.

### Option B: Dashboard calls MCP endpoint internally (rejected)

The dashboard HTTP-calls the MCP endpoint server-side to reuse tool logic. Creates an internal HTTP dependency and couples the dashboard to MCP protocol details. Awkward to test.

### Option C: Shared service layer, thin adapters (chosen)

Both surfaces call the same service functions. Logic is tested once at the service layer. Tool and route code is so thin it rarely needs its own tests. New features automatically get both surfaces by implementing the service function first.

## Consequences

- **Positive**: MCP tool and dashboard route for any feature are guaranteed to behave identically — they call the same code.
- **Positive**: Business logic is tested once at the service layer, not duplicated across tool and route tests.
- **Positive**: Compound tools reduce round-trips for Claude — complex operations return rich, pre-joined results rather than requiring multi-step orchestration.
- **Positive**: New contributors have a clear rule: service first, then wire both adapters.
- **Negative**: Requires discipline to enforce. Nothing technically prevents logic from creeping into a route handler. The rule must be documented (this ADR) and enforced in code review.
- **Negative**: Some operations are inherently HTTP-specific (streaming responses, SSE) or MCP-specific (tool schemas). These are acceptable exceptions — the rule applies to business logic, not protocol mechanics.
