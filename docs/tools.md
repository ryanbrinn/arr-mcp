# Tools Reference

This document is the authoritative reference for all MCP tools. It is intended for developers — both as a quick lookup and as a **design guardrail**: before implementing a new tool, check whether the capability already exists, and verify that the proposed tool follows the right approach (see the Approach column and the design principles at the bottom of this page).

## Container lifecycle

| Tool | Description | Approach |
|---|---|---|
| `container_list()` | All containers with status, uptime, and ports | HTTP → Podman/Docker socket (`/v1.41/containers/json`) |
| `container_start(name)` | Start a stopped container | HTTP → Podman/Docker socket |
| `container_stop(name)` | Stop a running container | HTTP → Podman/Docker socket |
| `container_restart(name)` | Restart a container | HTTP → Podman/Docker socket |
| `container_remove(name, confirm=True)` | Remove a container (requires `confirm=True`) | HTTP → Podman/Docker socket |
| `container_logs(name, lines=100)` | Fetch last N log lines | HTTP → Podman/Docker socket, decodes multiplexed stream |
| `container_stats()` | CPU, memory, and network stats for all running containers | HTTP → Podman/Docker socket, one stats call per container |

---

## Stack management

Stack management tools require [arr-agent](getting-started.md#arr-agent) to be running on the host. When arr-agent is unavailable, these tools return a message explaining what's needed — they never silently fail.

| Tool | Description | Approach |
|---|---|---|
| `stack_list()` | List all stacks in the stacks directory | Local filesystem — reads `compose_dir` |
| `stack_up(name)` | Start a stack with `podman-compose up -d` | Delegates to arr-agent via Unix socket |
| `stack_down(name, confirm=True)` | Stop a stack (requires `confirm=True`) | Delegates to arr-agent via Unix socket |
| `stack_pull(name)` | Pull latest images for a stack | Delegates to arr-agent via Unix socket |
| `stack_restart(name)` | Restart a stack (down then up) | Delegates to arr-agent via Unix socket |
| `compose_validate(name)` | Dry-run validate a stack compose file | Delegates to arr-agent via Unix socket |

---

## Compose files

| Tool | Description | Approach |
|---|---|---|
| `compose_read(stack)` | Read the compose.yaml for a stack | Local filesystem — reads `compose_dir/<stack>/compose.yaml` |
| `compose_write(stack, content)` | Write/replace the compose.yaml for a stack | Local filesystem write — scoped to `compose_dir` |

---

## Compose ↔ Quadlet conversion

Tools for migrating between Docker Compose and Podman quadlet unit files. Both tools write to staging locations and never overwrite originals — you review and install the output yourself.

| Tool | Description | Approach |
|---|---|---|
| `compose_to_quadlets(stack)` | Convert `compose.yaml` → `.container` files in `/opt/stacks/<stack>/quadlets/` | Local filesystem, pure in-process transform — no network, no subprocess |
| `quadlets_to_compose(stack)` | Convert `.container` files → `compose.from-quadlets.yaml` | Local filesystem, pure in-process transform — no network, no subprocess |

**Field coverage:** `image`, `container_name`, `environment`, `volumes`, `ports`, `networks`, all four restart policies, `depends_on`, and `healthcheck`. Unsupported compose fields (e.g. `build`, `deploy`) produce warnings in the output but do not fail the conversion.

**Installing generated quadlets:**

```bash
cp /opt/stacks/<stack>/quadlets/*.container ~/.config/containers/systemd/
systemctl --user daemon-reload
```

If [arr-agent](getting-started.md#arr-agent) is running, it can install the files directly via `systemd_daemon_reload`.

---

## Filesystem

All filesystem operations are scoped to allowed roots (`/opt/stacks`, `/media-server`, `/var/log`) and restricted to resources owned by the current user. See [Security](security.md).

| Tool | Description | Approach |
|---|---|---|
| `disk_usage(path="/media-server")` | Disk usage for a path | Local filesystem — `shutil.disk_usage` |
| `directory_list(path)` | List directory contents | Local filesystem — `Path.iterdir()`, ownership-filtered |
| `file_read(path)` | Read a text file | Local filesystem read — blocked on `config.xml` and `.db` files in `services_dir` |
| `file_write(path, content)` | Write a file (creates parent dirs as needed) | Local filesystem write — blocked in `services_dir` entirely |
| `file_delete(path, confirm=True)` | Delete a file (requires `confirm=True`, rejects root-owned files) | Local filesystem delete — ownership check enforced |

---

## Logs

| Tool | Description | Approach |
|---|---|---|
| `log_read(path, lines=100)` | Tail a log file | Local filesystem — path-scoped to `services_dir`, `compose_dir`, `/var/log` |
| `log_search(path, query, lines=50)` | Search a log file (case-insensitive) | Local filesystem — same path scoping as `log_read` |

---

## Service diagnostics

> **Design note:** These tools exist for structured/automated health reporting. For interactive diagnosis ("why is sonarr broken?"), Claude should orchestrate the composable tools above — `container_list`, `container_logs`, `log_read`, and `service_api_health` — rather than relying on a single tool as a one-stop workflow. See [Tool design principles](#tool-design-principles) below.

| Tool | Description | Approach | Verdict |
|---|---|---|---|
| `service_scan()` | Discover installed media services in `services_dir` | Filesystem scan + cross-reference against `container_list` result | ✅ Correct layer — but internally duplicates `container_list`; should accept running-names as input |
| `service_api_health(service)` | Live health check for a single service via its HTTP API (`/api/v3/health` for `*arr` apps) | HTTP, via `ServiceRegistry` + `CredentialStore` | ✅ Correct layer — HTTP-first |
| `service_health_report()` | Structured JSON health summary for all known services | Filesystem scan, then HTTP health check (`service_api_health`) per known service | ✅ Correct layer |
| `service_fix(service, service_dir, fix_type, params, confirm=True)` | Apply a config fix (XML key swap or env var update) | Direct filesystem write to `config.xml` or `compose.yaml` | ⚠️ Narrow coverage, moderate risk surface — review before extending |

---

## Service credentials

Tools for managing per-service API credentials used by the Phase 2 service clients. Stored in `CredentialStore` (encrypted with `ARR_MCP_SECRET`), never in compose files. See [Configuration — Service credentials](configuration.md#service-credentials) and [Security](security.md).

| Tool | Description | Approach |
|---|---|---|
| `credential_set(service, api_key, base_url="")` | Store or update an API credential for a service (e.g. `sonarr`, `radarr`, `plex`) | Encrypted write to `CredentialStore` |
| `credential_list()` | List services that have credentials configured | Read from `CredentialStore` (values not returned) |
| `credential_delete(service)` | Remove the stored credential for a service | Encrypted write to `CredentialStore` |

---

## Cross-service reachability

| Tool | Description | Approach |
|---|---|---|
| `service_api_reachability()` | For each service with credentials configured, check whether its HTTP API is reachable and whether the API key is valid | HTTP health check via `ServiceRegistry` + `CredentialStore` |
| `inter_service_reachability()` | Verify that Sonarr/Radarr can reach their configured download clients | Reads download-client config from each `*arr` database, then HTTP-checks each one |

---

## Media library — watched content cleanup

Cross-reference Sonarr/Radarr library state with Plex watch history to find content that every household user has finished watching and that has files on disk. See [ADR-0006](adr/0006-user-interest-model.md) for the interest model that governs eligibility.

| Tool | Description | Approach |
|---|---|---|
| `watched_cleanup_preview()` | Preview non-current-season episode files where all household Plex users have watched and a file exists in Sonarr (season 0 always excluded) | `SonarrClient` + `PlexClient`, dry run — no files deleted |
| `watched_cleanup_delete(confirm=False)` | Delete the episode files identified by `watched_cleanup_preview` | Same join, then `SonarrClient.delete_episode_file()`. Requires `confirm=True` |
| `movie_watched_cleanup_preview()` | Preview movie files where all household Plex users have watched and a file exists in Radarr | `RadarrClient` + `PlexClient`, dry run — no files deleted |
| `movie_watched_cleanup_delete(confirm=False)` | Delete the movie files identified by `movie_watched_cleanup_preview` | Same join, then `RadarrClient.delete_movie_file()`. Requires `confirm=True` |

---

## User interest states

Per-user, per-content interest tracking that backs the watched-cleanup tools and the dashboard's Media Library tab. See [ADR-0006](adr/0006-user-interest-model.md).

| Tool | Description | Approach |
|---|---|---|
| `interest_set(content_id, user_id, state, username="", content_type="unknown")` | Set a user's interest state (`interested`, `watched`, `marked_deletion`) for a piece of content | Write to `InterestStore` |
| `interest_list(filter="", content_id="")` | List content interest states, optionally filtered by state or content ID | Read from `InterestStore` |
| `interest_pending_review()` | List content with mixed interest states that requires admin review | Read from `InterestStore`, cross-referenced with inactivity threshold |

---

## Alerts

Background alert evaluation via `AlertWatcher`, configurable via `ARR_MCP_ALERT_INTERVAL_SECONDS`.

| Tool | Description | Approach |
|---|---|---|
| `alert_rules_list()` | List configured alert rules (`stuck_download`, `disk_usage`, `service_down`, `log_errors`) and their settings | Read from `AlertWatcher` config |
| `alert_rules_set(rule, enabled=None, threshold=None, cooldown_minutes=None)` | Update an alert rule's enabled state, threshold, or cooldown | Write to `AlertWatcher` config |
| `alerts_recent(limit=20)` | Return recently fired alerts, newest first | Read from the alert log |

---

## Upgrades

| Tool | Description | Approach |
|---|---|---|
| `upgrades_available()` | List services with newer versions available, with changelog summary and risk assessment | Read from `VersionStore` cache, updated daily by `VersionChecker` |

---

## AI diagnostics

`POST /api/diagnose` (dashboard-only, not an MCP tool) takes `{"issue_type": str, "context": dict}` and returns a narrative plus suggested remedies, generated via the configured AI provider (see [ADR-0005](adr/0005-ai-provider-strategy.md)). When no AI provider is configured (`ARR_MCP_AI_PROVIDER=none`), it falls back to rule-based remedies only.

---

## Tool design principles

Before adding a new tool, verify it follows these rules. If it doesn't, reconsider the approach.

| Principle | What it means |
|---|---|
| **Atomic and composable** | Each tool does one thing and returns raw data. Claude decides what to do with the result. |
| **Right layer** | HTTP for live service state (container runtime, service APIs). Filesystem for config and logs that exist regardless of whether services are running. Never duplicate across layers. |
| **No baked-in workflows** | Multi-step conditional logic ("check X, then if Y check Z") belongs in Claude's reasoning, not in a tool. If a tool has branches that depend on earlier results, it's doing too much. |
| **No duplication** | Before writing a new tool, check this table. If the data is already exposed by another tool, compose — don't reimplement. |
| **Agents vs tools** | Use a tool when the operation is discrete, well-defined, and returns structured data. Use Claude as the orchestrator (agentic) when the right next step depends on what you find. Diagnostic workflows are almost always agentic. |
