# Architecture

## Deployment model

arr-mcp runs as a container alongside the media stack. It communicates with the container runtime via a bind-mounted Unix socket and exposes an MCP endpoint and a read-only dashboard over HTTP.

Stack and systemd management require `arr-agent`, a small host-side process that runs as the service account and communicates with arr-mcp via a bind-mounted Unix socket.

```
Claude (MCP client)          Browser
      │  HTTP + Bearer auth       │  HTTP + Plex OAuth session
      ▼                           ▼
 ┌─────────────────────────────────────────┐
 │           arr-mcp container             │
 │  /mcp   – MCP endpoint                  │
 │  /      – read-only dashboard (Jinja2)  │
 │  /api/status – JSON status              │
 └───────────────┬─────────────────────────┘
                 │  Unix socket (podman.sock / docker.sock)
                 ▼
          Container runtime
                 │
                 ▼
   Media stack containers (plex, sonarr, radarr, ...)

 arr-agent (host process, service account)
      │  Unix socket (arr-agent.sock, bind-mounted into arr-mcp)
      ├── podman-compose up/down/pull/restart
      ├── systemctl --user start/stop/restart/status/daemon-reload
      └── read/write ~/.config/containers/systemd/*.container
```

## Target environment

- **OS**: Debian/Ubuntu
- **Runtime**: Rootless Podman under a dedicated service account (e.g. `media`)
- **Socket**: `/run/user/<UID>/podman/podman.sock` — where `<UID>` is the service account UID (`id media`)
- **Stacks**: `/opt/stacks/<stack-name>/compose.yaml`
- **Media**: `/media-server/`

## Core components

### arr-mcp (container)

| File | Responsibility |
|---|---|
| `src/arr_mcp/server.py` | Starlette ASGI app, API key auth middleware, route assembly, entry point |
| `src/arr_mcp/config.py` | Pydantic settings loaded from environment / `.env` |
| `src/arr_mcp/runtime/detector.py` | Auto-detects Podman or Docker socket at startup |
| `src/arr_mcp/runtime/client.py` | Async HTTP client over the container runtime socket |
| `src/arr_mcp/tools/containers.py` | Container lifecycle tools |
| `src/arr_mcp/tools/stacks.py` | Stack management tools (delegates to arr-agent) |
| `src/arr_mcp/tools/filesystem.py` | Filesystem tools scoped to allowed paths |
| `src/arr_mcp/tools/logs.py` | Log reading and searching tools |
| `src/arr_mcp/tools/conversion.py` | Compose ↔ Quadlet conversion tools |
| `src/arr_mcp/tools/diagnostics.py` | Service health diagnostics (filesystem + API reachability) |
| `src/arr_mcp/tools/services.py` | Static service registry and pure diagnostic logic |
| `src/arr_mcp/tools/utils.py` | Shared utilities (ownership checks, etc.) |
| `src/arr_mcp/helper/client.py` | HTTP/JSON client for the arr-agent Unix socket |
| `src/arr_mcp/dashboard/routes.py` | Dashboard route handlers |
| `src/arr_mcp/dashboard/data.py` | Status data assembly from runtime client |
| `src/arr_mcp/dashboard/templates/` | Jinja2 HTML templates |
| `src/arr_mcp/dashboard/static/` | CSS stylesheet (no external CDN) |

### arr-agent (host process)

| File | Responsibility |
|---|---|
| `src/arr_helper/server.py` | Unix socket HTTP server (hand-rolled, no framework) |
| `src/arr_helper/handlers.py` | Operation dispatch table (14 operations) |
| `src/arr_helper/validation.py` | Input validators — regex-gated, no path traversal possible |
| `src/arr_helper/subprocess.py` | Safe subprocess runner (`create_subprocess_exec`, never `shell=True`) |

## Security boundaries

| Boundary | Mechanism |
|---|---|
| MCP endpoint auth | `Authorization: Bearer <key>` header required on `/mcp` |
| Dashboard auth | Signed-in session (local account or Plex login), or `?key=<key>` |
| Filesystem scope | `_check_path()` restricts to `stacks_dir`, `media_dir`, `/var/log` |
| Ownership check | `is_owned_by_current_user()` blocks operations on root-owned files |
| Helper input | Regex validation on all args; `create_subprocess_exec` prevents injection |
| Helper socket | Mode `0600`, owned by service account — no other process can connect |

See [Security](security.md) and [ADR-0001](adr/0001-filesystem-ownership-scoping.md) for full details.

## Key architectural decisions

| Decision | ADR |
|---|---|
| Filesystem ownership scoping | [ADR-0001](adr/0001-filesystem-ownership-scoping.md) |
| Host-side helper agent | [ADR-0002](adr/0002-host-side-helper-agent.md) |
| Dashboard frontend strategy | [ADR-0003](adr/0003-frontend-strategy.md) |
| Supported runtime configurations | [ADR-0004](adr/0004-supported-runtime-configurations.md) |
| AI provider strategy | [ADR-0005](adr/0005-ai-provider-strategy.md) |
| User interest model | [ADR-0006](adr/0006-user-interest-model.md) |
| Shared service layer | [ADR-0007](adr/0007-shared-service-layer.md) |
| Authentication strategy | [ADR-0008](adr/0008-authentication-strategy.md) |

---

## Phase 2 Service Client Layer

Phase 2 introduces direct HTTP communication with running media services (Sonarr, Radarr, Plex, SABnzbd). This section describes the design that all Phase 2 work must follow.

### Design principles

- **One client class per service.** No one-off `httpx` clients in tool code.
- **Credentials never in compose files.** `CredentialStore` is the only source of truth.
- **Registry-driven.** `KNOWN_SERVICES` already defines ports and health paths; the client layer builds on that.
- **Testable without a running service.** All client classes accept an injectable `httpx.AsyncClient` for unit testing.

### Layered class hierarchy

```
BaseServiceClient          — async HTTP, timeout, error normalisation
    └── ArrClient          — shared /api/v3 schema (Sonarr, Radarr, Lidarr)
            ├── SonarrClient
            └── RadarrClient
    └── PlexClient
    └── SABnzbdClient
    └── QBittorrentClient
```

### Component responsibilities

**`CredentialStore`** (`src/arr_mcp/services/credentials.py`)

Secure per-service credential storage. Each entry holds the API key (or token) for one service. Env-var overrides (`SONARR_API_KEY`, `PLEX_TOKEN`, etc.) take precedence over stored values — this enables CI/testing without touching the store.

Storage format is deliberately simple: an encrypted JSON file at a fixed path inside the container's data volume. The encryption key comes from `ARR_MCP_SECRET` in the environment.

**`BaseServiceClient`** (`src/arr_mcp/services/base.py`)

Thin async wrapper around `httpx.AsyncClient`. Responsibilities:
- Accept `base_url` and `api_key` at construction (resolved by `ServiceRegistry`)
- Expose `get()`, `post()`, `delete()` with consistent error normalisation
- Implement `health()` using the service's `api_health_path` from `KNOWN_SERVICES`
- Never raise — return structured error objects

**`ArrClient`** (`src/arr_mcp/services/arr.py`)

Extends `BaseServiceClient` with the API schema shared by all `*arr` applications:
- `/api/v3/system/status`
- `/api/v3/queue`
- `/api/v3/wanted/missing`
- `/api/v3/health`

Sonarr and Radarr extend this with their own resources (series/episodes vs. movies).

**`ServiceRegistry`** (`src/arr_mcp/services/registry.py`)

Combines `KNOWN_SERVICES` (static metadata) with `CredentialStore` (runtime credentials) to produce ready-to-use client instances. The key method:

```python
registry.get_client("sonarr") -> SonarrClient
```

This reads the port from the service's config file (via the existing `extract_service_port` helper), fetches the API key from `CredentialStore`, and returns a configured client. Tool code never assembles URLs or reads credentials directly.

### Background tasks

Phase 2 introduces two long-running background tasks attached to the server lifespan:

**`AlertWatcher`**

Runs on a configurable interval. Evaluates a set of alert rules (stuck downloads, error-rate thresholds, disk usage). When a rule fires it emits a structured notification. Phase 2 delivers: logged alerts + MCP tool to query recent alerts. Phase 3+ can add webhooks / push.

**`VersionChecker`**

Polls GitHub Releases API and Docker Hub tags on a daily schedule. For each monitored service it compares the running image tag against the latest available release, parses the changelog, and surfaces a structured upgrade recommendation. The recommendation includes: current version, latest version, changelog summary, and a risk assessment (major/minor/patch).

### Cross-service intelligence pattern

The signature Phase 2 use case — watched content cleanup — demonstrates the pattern for all cross-service features:

```
Tool receives natural language intent (via Claude)
  → Query PlexClient for watch history
  → Query SonarrClient for library state
  → Join on series title (case-insensitive)
  → Apply business rules (quorum, season exclusions, user protection)
  → Present candidates to user for confirmation
  → Call SonarrClient.delete_episode_file() per confirmed item
```

Every destructive operation requires explicit confirmation. The join and business-rule logic lives in the tool module, not in the client classes — clients are pure data access.

### File layout (Phase 2 additions)

```
src/arr_mcp/
  services/
    __init__.py
    credentials.py      # CredentialStore
    base.py             # BaseServiceClient
    arr.py              # ArrClient
    sonarr.py           # SonarrClient
    radarr.py           # RadarrClient
    plex.py             # PlexClient
    sabnzbd.py          # SABnzbdClient
    registry.py         # ServiceRegistry
  tasks/
    __init__.py
    alerts.py           # AlertWatcher
    versions.py         # VersionChecker
  tools/
    media.py            # watched_cleanup_preview, watched_cleanup_delete
    alerts.py           # list_alerts, configure_alert_rule
    upgrades.py         # list_available_upgrades
```
