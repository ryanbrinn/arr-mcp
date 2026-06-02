# ADR-0003: Frontend Strategy

| | |
|---|---|
| **Status** | Accepted |
| **Date** | 2026-06-01 |
| **Issue** | [#14](https://github.com/ryanbrinn/arr-mcp/issues/14) |

## Context

arr-mcp started as a pure MCP server — natural language management of a home media stack via Claude. While powerful for technical users, the chat-only interface has limitations:

- Less technical users (household members) don't know what to ask
- Chat lacks rich content — no status cards, visual disk usage, or one-click actions
- No guided navigation or discovery of available features
- Requires a Claude subscription to use at all

A core goal is to make media server management accessible to all household members, not just the person who set it up.

## Decision

**Option C — Hybrid read-only dashboard + chat. Implemented.**

A simple auto-refreshing dashboard is served as additional routes on the existing Starlette app. No new infrastructure, no separate deployment, no JavaScript framework.

Implementation decisions:
- **Jinja2** for server-side rendering — stays in Python, no frontend build tooling
- **`<meta http-equiv="refresh" content="30">`** for auto-refresh — no WebSockets needed for Phase 1
- **CSS-only disk bars** (`<div>` with inline `width` style) — no SVG, no canvas
- **Auth: `?key=` query param**, or `DASHBOARD_PUBLIC=true` for unauthenticated LAN use — same API key as MCP, no separate credential to manage
- **No external CDN** — the stylesheet is self-contained, the dashboard works fully offline on a LAN
- **Read-only in Phase 1** — write actions (start/stop buttons) deferred to Phase 2

## Options considered

### Option A: Full web UI + MCP backend

A rich web interface (React or HTMX/Jinja2) that talks to the arr-mcp REST API. The UI provides dashboards, status cards, and action buttons. Chat sits alongside as an "advanced" mode.

**Pros:** Rich, discoverable UI. Works without Claude. Accessible to all household members.
**Cons:** Significant additional scope. Frontend to build and maintain. Technology choice (React vs server-side rendering) adds decision overhead.

### Option B: Guided chat with contextual suggestions

Keep the MCP/chat approach but surface contextual action suggestions after each response (e.g. after showing container status, offer "Restart", "View Logs", "Stop" buttons).

**Pros:** Minimal additional scope. Stays within the MCP model. Claude generates suggestions contextually.
**Cons:** Depends on MCP client support for interactive UI elements, which is still evolving. Still requires Claude access.

### Option C: Hybrid — read-only dashboard + chat (preferred near-term)

A simple auto-refreshing read-only dashboard built as additional Starlette routes within arr-mcp. Shows container status, disk usage, and stack health. A "chat" button pre-loads Claude with server context for actions.

**Pros:** Low complexity. Single deployable unit — no new infrastructure. Dashboard works without Claude for read-only views. Clean separation: dashboard for status, chat for actions.
**Cons:** Write actions still require chat. Two interaction paradigms to maintain long-term.

## Consequences (if Option C is chosen)

- A `GET /` route is added to the existing Starlette app serving an HTML dashboard
- A `GET /api/status` JSON endpoint provides the data layer
- Dashboard is server-side rendered (Jinja2) to avoid frontend build tooling
- Auth model for the dashboard needs to be decided — same API key, separate password, or open on LAN
- The MCP endpoint and all existing tools remain unchanged
- Long-term, Option A remains viable if the project grows a broader user base

## Open questions

1. Should the dashboard support write actions (start/stop buttons) or remain read-only?
2. Auth model — same API key header, basic auth, or unauthenticated on LAN?
3. Should the dashboard be part of arr-mcp or a separate project?
