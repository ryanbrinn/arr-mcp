# Spec: Read-only status dashboard

| | |
|---|---|
| **Issue** | [#14](https://github.com/ryanbrinn/arr-mcp/issues/14) |
| **ADR** | [ADR-0003](../adr/0003-frontend-strategy.md) (Option C) |
| **Phase** | 1 — MVP |
| **Status** | Ready for implementation |

## Problem

arr-mcp is only accessible through Claude/MCP today. Household members who aren't technical or don't have a Claude subscription can't see the state of the server — whether containers are running, how much disk is in use, or if a stack is unhealthy.

## Goal

A lightweight, auto-refreshing, read-only HTML dashboard served as additional routes within the existing Starlette app. No new infrastructure, no JavaScript framework, no separate deployment. The dashboard shows what the server is doing right now and provides an "Open in Claude" shortcut for power users who want to take action.

The dashboard is strictly read-only. Write actions (start, stop, restart) remain in chat.

---

## Routes

Two new routes are added to `server.py`:

| Route | Method | Auth | Description |
|---|---|---|---|
| `GET /` | GET | Optional (see below) | HTML dashboard |
| `GET /api/status` | GET | Same as `/` | JSON status data |

All existing routes (`/mcp`, `/health`) are unchanged.

### Auth model

The dashboard uses the **same API key** as the MCP endpoint, passed as a query parameter for browser convenience:

```
GET /?key=<api_key>
```

The dashboard otherwise requires a signed-in session (see ADR-0008 for the
AppUser/session model and login providers).

The `/health` endpoint remains unauthenticated (liveness probe use case).

---

## `/api/status` response

```json
{
  "generated_at": "2026-06-02T14:32:00Z",
  "containers": [
    {
      "id": "abc123",
      "name": "plex",
      "image": "linuxserver/plex:latest",
      "status": "running",
      "health": "healthy",
      "uptime_seconds": 86400
    }
  ],
  "stacks": [
    {
      "name": "media",
      "container_count": 5,
      "running_count": 5,
      "status": "healthy"
    }
  ],
  "disk": [
    {
      "path": "/media-server",
      "total_gb": 4000.0,
      "used_gb": 2100.0,
      "free_gb": 1900.0,
      "used_pct": 52.5
    },
    {
      "path": "/opt/stacks",
      "total_gb": 50.0,
      "used_gb": 2.1,
      "free_gb": 47.9,
      "used_pct": 4.2
    }
  ]
}
```

Stack `status` is derived:
- `healthy` — all containers running
- `degraded` — some containers running, some stopped
- `down` — no containers running
- `unknown` — helper unavailable (stack management not functional)

---

## Dashboard HTML

Server-side rendered with **Jinja2** templates. No client-side JavaScript framework. Auto-refresh via `<meta http-equiv="refresh" content="30">`.

### Template structure

```
src/arr_mcp/dashboard/
    templates/
        base.html       # layout, nav, meta refresh
        index.html      # main dashboard page
    static/
        style.css       # minimal stylesheet (no external CDN)
    routes.py           # Starlette route handlers
    data.py             # builds the status dict from existing tools
```

### Page layout

```
┌─────────────────────────────────────────────────────────┐
│  arr-mcp          Last updated: 14:32:00   [Open Claude] │
├─────────────────────────────────────────────────────────┤
│  DISK USAGE                                              │
│  /media-server   ████████░░░░  52% of 4.0 TB            │
│  /opt/stacks     █░░░░░░░░░░░   4% of 50 GB             │
├─────────────────────────────────────────────────────────┤
│  CONTAINERS                                              │
│  ● plex          running   healthy   up 1d 0h            │
│  ● sonarr        running   healthy   up 1d 0h            │
│  ✕ radarr        stopped   —                             │
├─────────────────────────────────────────────────────────┤
│  STACKS                                                  │
│  media    5/5 running   healthy                          │
│  tools    2/3 running   degraded                         │
└─────────────────────────────────────────────────────────┘
```

Status indicators:
- `●` green — running / healthy
- `◐` yellow — degraded / unhealthy
- `✕` red — stopped / error

### "Open in Claude" button

Links to `https://claude.ai/new?q=<encoded_prompt>` where the prompt is:

```
I'm managing my home media server with arr-mcp at <HOST>. 
Current status: <N> containers running, <disk_used> of <disk_total> used.
```

`HOST` is the `PUBLIC_URL` env var (optional, falls back to the request host).

### Disk usage bar

Plain CSS `<div>` with inline `width` style — no SVG, no canvas, no JavaScript:

```html
<div class="bar-track">
  <div class="bar-fill" style="width: 52%"></div>
</div>
```

---

## Settings

Add to `config.py`:

```python
public_url: str = ""             # PUBLIC_URL env var — used in "Open in Claude" link
```

---

## Implementation notes

- `data.py` calls the same internal functions used by MCP tools — do not duplicate the data-fetching logic
- Container and disk data comes from `ContainerClient` and `shutil.disk_usage` (already used in existing tools)
- Stack status is derived by grouping containers by their stack label (`com.docker.compose.project`)
- If the helper is unavailable, stacks show `unknown` status — the dashboard never errors out
- Jinja2 is not currently a dependency — add with `uv add jinja2`
- Static files are served via Starlette's `StaticFiles` mount at `/static`
- The stylesheet is minimal (~100 lines) — no Tailwind, no Bootstrap

---

## Tests required

File: `tests/dashboard/test_routes.py`

| Test | Description |
|---|---|
| `test_dashboard_returns_200` | `GET /` returns 200 with valid API key |
| `test_dashboard_rejects_missing_key` | `GET /` without key or session → 401 |
| `test_api_status_shape` | `GET /api/status` returns expected JSON keys |
| `test_api_status_disk_fields` | Disk entries contain `total_gb`, `used_gb`, `free_gb`, `used_pct` |
| `test_dashboard_html_contains_containers` | HTML response contains container names |

---

## Out of scope

- Write actions (start/stop/restart buttons) — Phase 2 at earliest
- Plex authentication — Phase 2
- WebSocket live updates — meta-refresh is sufficient for Phase 1
- Dark mode, responsive design beyond readable on desktop — Phase 1 is functional, not polished
- External CSS/JS CDN dependencies — everything must work on a LAN with no internet access
