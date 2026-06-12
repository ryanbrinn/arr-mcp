# Configuration

All settings are loaded from environment variables or a `.env` file in the working directory. Every variable is prefixed with `ARR_MCP_`.

## arr-mcp settings

| Variable | Default | Description |
|---|---|---|
| `ARR_MCP_API_KEY` | `changeme` | Bearer token for MCP endpoint auth — **change this** |
| `ARR_MCP_PORT` | `8081` | HTTP listen port |
| `ARR_MCP_SERVICES_DIR` | `/media-server` | Root directory where your arr services live (configs, logs, data) — read-only |
| `ARR_MCP_MEDIA_DIR` | `/media-server/library` | Root directory of your media library |
| `ARR_MCP_COMPOSE_DIR` | `` | Root directory for Docker Compose projects — required for `docker-compose` runtime |
| `ARR_MCP_QUADLETS_DIR` | `~/.config/containers/systemd` | Podman quadlet unit files directory — only used for `podman` runtime |
| `ARR_MCP_CONTAINER_RUNTIME` | `docker-compose` | `docker-compose` / `docker` / `podman` / `auto` |
| `ARR_MCP_SOCKET_PATH` | `` | Explicit socket path — required when running inside a container |
| `ARR_MCP_HELPER_SOCKET` | `/run/arr-agent/arr-agent.sock` | Path to the arr-agent Unix socket |
| `ARR_MCP_DASHBOARD_PUBLIC` | `false` | Serve dashboard without auth (set `true` for LAN-only deployments) |
| `ARR_MCP_SESSION_SECRET` | `` | Secret for signing dashboard session cookies (Plex sign-in) — see [Dashboard](#dashboard) |
| `ARR_MCP_ADMIN_PLEX_USERS` | `` | Comma-separated Plex usernames granted the dashboard admin role |
| `ARR_MCP_LOG_LEVEL` | `info` | `debug` / `info` / `warning` / `error` |

## AI provider settings

Phase 2 features (dashboard insight blocks, `POST /api/diagnose`) use a language model to generate natural-language summaries and remedy suggestions. See [ADR-0005](adr/0005-ai-provider-strategy.md) for the rationale.

| Variable | Default | Description |
|---|---|---|
| `ARR_MCP_AI_PROVIDER` | `ollama` | `ollama` / `anthropic` / `none` — `none` disables AI features and falls back to rule-based remedies |
| `ARR_MCP_OLLAMA_URL` | `http://localhost:11434` | Base URL for a local Ollama instance |
| `ARR_MCP_OLLAMA_MODEL` | `llama3.2:3b` | Ollama model name used for completions |
| `ARR_MCP_ANTHROPIC_API_KEY` | `` | Anthropic API key — required when `ARR_MCP_AI_PROVIDER=anthropic` |
| `ARR_MCP_ANTHROPIC_MODEL` | `claude-haiku-4-5-20251001` | Anthropic model ID used for completions |

## Service credentials

Phase 2 service integrations (Sonarr, Radarr, Plex, SABnzbd) need API keys to talk to those services. These are managed by `CredentialStore` — an encrypted JSON file inside the container's data volume — via the `credential_set` / `credential_list` / `credential_delete` MCP tools, never via compose files.

| Variable | Default | Description |
|---|---|---|
| `ARR_MCP_SECRET` | `` | Encryption key for `CredentialStore`. **Required** for Phase 2 service integrations — without it, credentials are stored in plaintext and a warning is logged |
| `SONARR_API_KEY`, `RADARR_API_KEY`, `PLEX_TOKEN`, `SABNZBD_API_KEY` | `` | Per-service env var overrides. Take precedence over `CredentialStore` — useful for CI/testing |

## Alert watcher

| Variable | Default | Description |
|---|---|---|
| `ARR_MCP_ALERT_INTERVAL_SECONDS` | `300` | How often `AlertWatcher` polls services for threshold violations |

## Runtime modes

The `ARR_MCP_CONTAINER_RUNTIME` setting controls which tools and dashboard sections are available:

| Runtime | Stack tools | Dashboard stacks | Use case |
|---|---|---|---|
| `docker-compose` | ✅ | ✅ | Docker with Compose files (default) |
| `docker` | ❌ | ❌ | Docker Engine, container management only |
| `podman` | ❌ | ❌ | Rootless Podman via arr-agent |

Stack tools (`stack_up`, `stack_down`, `stack_list`, etc.) and the dashboard stacks view are only available when running Docker Compose.

## Directory paths

arr-mcp works with up to four directory roots depending on your runtime:

| Purpose | Variable | Runtime | What lives here |
|---|---|---|---|
| arr service data | `ARR_MCP_SERVICES_DIR` | all | Sonarr, Radarr, SABnzbd configs, logs, databases |
| Media library | `ARR_MCP_MEDIA_DIR` | all | Your actual media files |
| Compose projects | `ARR_MCP_COMPOSE_DIR` | `docker-compose` only | Docker Compose project directories |
| Quadlet units | `ARR_MCP_QUADLETS_DIR` | `podman` only | Systemd quadlet unit files |

These can share a common root (e.g. all under `/media-server`) or live on separate mounts — configure each independently.

**`ARR_MCP_SERVICES_DIR` is read-only.** arr-mcp will never write to your service directories. Additionally, `config.xml` and database files (`*.db`, `*.db-shm`, `*.db-wal`) are blocked from read access to protect credentials and prevent database corruption.

## arr-agent settings

arr-agent reads a single environment variable:

| Variable | Default | Description |
|---|---|---|
| `HELPER_SOCKET` | `/run/arr-agent/arr-agent.sock` | Path where arr-agent creates its Unix socket |

The socket path must match `ARR_MCP_HELPER_SOCKET` on the arr-mcp side.

---

## Socket path

When running arr-mcp inside a container, `ARR_MCP_SOCKET_PATH` must be set to the bind-mounted socket path:

```bash
-e ARR_MCP_SOCKET_PATH=unix:///run/user/1000/podman/podman.sock
```

If omitted, arr-mcp will attempt to auto-detect the socket at startup, which will fail inside a container.

## Helper socket

arr-agent's socket is bind-mounted into the arr-mcp container. The default paths assume systemd's `RuntimeDirectory=arr-agent` places the socket at `/run/user/<UID>/arr-agent/arr-agent.sock` on the host.

In the arr-mcp container (quadlet or compose):

```yaml
volumes:
  - /run/user/1000/arr-agent/arr-agent.sock:/run/arr-agent/arr-agent.sock:z
```

Override the in-container path if needed:

```bash
-e ARR_MCP_HELPER_SOCKET=/run/arr-agent/arr-agent.sock
```

## Dashboard

The dashboard is served at `GET /` and requires authentication by default. Three auth modes:

**Plex sign-in** (default, recommended): household members sign in with their Plex account via `/auth/signin`. A signed session cookie is issued and identifies the user for interest-state tracking and admin actions. Configure:

| Variable | Default | Description |
|---|---|---|
| `ARR_MCP_SESSION_SECRET` | `` | Secret used to sign session cookies. Generate with `python -c "import secrets; print(secrets.token_hex(32))"`. If unset, a random per-process secret is used and sessions do not survive restarts |
| `ARR_MCP_ADMIN_PLEX_USERS` | `` | Comma-separated Plex usernames that receive the admin role (review queue, interest overrides, deletions) |

**Key in query param** (fallback, no Plex identity):

```
http://your-server:8081/?key=your-secret-key
```

**Public mode** (no auth, suitable for LAN-only deployments):

```bash
-e ARR_MCP_DASHBOARD_PUBLIC=true
```

See [ADR-0008](adr/0008-authentication-strategy.md) for the full authentication design.

