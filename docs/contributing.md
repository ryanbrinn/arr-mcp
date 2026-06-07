# Contributing

## Prerequisites

- [VS Code](https://code.visualstudio.com/) with the [Dev Containers](https://marketplace.visualstudio.com/items?itemName=ms-vscode-remote.remote-containers) extension
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (Windows/macOS) or Docker Engine (Linux)
- SSH access to your test server
- [uv](https://docs.astral.sh/uv/) — Python package manager

---

## Dev container

The project ships a dev container that gives you a proper Linux environment regardless of your host OS. This is the recommended way to develop and run tests — it matches the target deployment platform and avoids Windows/macOS path and socket quirks.

### First-time setup

1. Open the project in VS Code
2. When prompted **"Reopen in Container"**, click it — or open the Command Palette and run **Dev Containers: Reopen in Container**
3. VS Code rebuilds the container and installs all dependencies via `uv sync`

That's it. The integrated terminal is now running inside a Linux container with Python, uv, ruff, and pyright all available.

### What the container includes

| Tool | Purpose |
|---|---|
| Python 3.11 (Debian Bookworm) | Matches the minimum supported version |
| uv | Dependency management and running tools |
| Ruff | Linting and formatting |
| Pylance | Type checking in the editor |
| docker-outside-of-docker | Allows `docker` commands inside the container to reach the host Docker daemon |

---

## Running tests

All test commands should be run from inside the dev container (VS Code integrated terminal).

### Unit tests

```bash
uv run pytest tests/ -v
```

Or via Make:

```bash
make test
```

The suite currently has ~330 tests. Expected output: all pass, 16 skipped (E2E tests that require a live runtime, and one Linux-path test that is skipped on macOS).

### Linting and formatting

```bash
make fmt        # ruff format + ruff check --fix
make typecheck  # pyright
```

Or individually:

```bash
uv run ruff format .
uv run ruff check .
uv run pyright
```

### Pre-PR checklist

Before opening a pull request, run all three in order:

```bash
make fmt        # 1. Format and lint — fix all errors
make typecheck  # 2. Type check — fix all errors
make test       # 3. Full test suite — fix all failures
```

All three must pass clean. Then run `/review` in Claude Code to check the implementation against the spec.

---

## Manual end-to-end testing

Unit tests cover logic in isolation. Manual E2E testing verifies that tools work correctly against a real container runtime with real services.

**Never test against the production instance.** Use the branch test deployment workflow below.

### How it works

`scripts/test-deploy.sh` SSHes to your server, checks out your branch to a separate directory (`~/arr-mcp-test/`), starts a minimal throwaway stack, and runs arr-mcp on port `8082`. Your production instance on port `8081` is never touched.

```
your machine                        server (192.168.2.15)
────────────────────                ──────────────────────────────────
make test-deploy       ──SSH──▶     ~/arr-mcp-test/  (your branch)
  BRANCH=feat/foo                   arr-mcp running on :8082
                                      └── test-stack/ (throwaway containers)

.mcp.json.test  ◀── swap in ──     http://192.168.2.15:8082/mcp
```

### Step-by-step

**1. Deploy your branch to the test instance**

```bash
make test-deploy BRANCH=feat/your-branch-name
```

The script will print the test instance URL and API key when it's ready:

```
arr-mcp test instance is running.
  Dashboard : http://192.168.2.15:8082/
  MCP URL   : http://192.168.2.15:8082/mcp
  API key   : test-key-local
  Logs      : ssh 192.168.2.15 tail -f /tmp/arr-mcp-test.log
```

**2. Point Claude at the test instance**

Swap `.mcp.json.test` in as your active `.mcp.json`:

```bash
# Back up production config
cp .mcp.json .mcp.json.prod

# Switch to test instance
cp .mcp.json.test .mcp.json
```

Reload the MCP connection in your Claude client (FleetView: disconnect and reconnect the arr-mcp server).

**3. Run your manual tests**

The test instance has four throwaway containers running — `test-sabnzbd`, `test-sonarr`, `test-radarr`, and `test-plex`. Use these to exercise the MCP tools.

**Container and filesystem tools**

- `container_list` / `container_stats` / `container_logs` — verify all four containers appear and report data
- `container_start` / `container_stop` / `container_restart` — verify lifecycle actions against a throwaway container (never run these against production containers)
- `service_scan` / `service_diagnose` / `service_health_report` — verify diagnostic tools run against test service configs
- `service_api_reachability` / `inter_service_reachability` — verify API and cross-service connectivity checks against the test stack's Sonarr/Radarr/Plex/SABnzbd
- `file_read` / `file_write` / `file_delete` / `directory_list` / `disk_usage` — verify filesystem access is scoped to the test-stack data directory
- `log_read` / `log_search` — verify log tools against test service log dirs
- `compose_to_quadlets` / `quadlets_to_compose` — verify conversion against `test-stack/compose.yaml`
- Dashboard at `http://192.168.2.15:8082/` — verify it loads and shows the test containers

**Credential and service-client tools**

- `credential_set` / `credential_list` / `credential_delete` — store and retrieve API keys for `sonarr`, `radarr`, and `plex` against the test instances (never store production credentials here)
- Verify `CredentialStore`'s three-tier resolution (env var → stored credential → XML config auto-discovery) by testing with and without an explicitly stored credential

**Media intelligence tools (Sonarr/Radarr/Plex)**

These need realistic data to exercise meaningfully — register a series in test-Sonarr and a movie in test-Radarr (via their `/api/v3/series` and `/api/v3/movie` endpoints), seed placeholder media files, add matching libraries in test-Plex, and mark items watched via Plex's `/:/scrobble` endpoint. Then:

- `watched_cleanup_preview` — verify it identifies non-current-season episodes that have files on disk and that all household Plex users have watched (season 0 is always excluded)
- `watched_cleanup_delete` — verify it deletes only the previewed candidates and requires `confirm=true`

!!! note "Seeding realistic data"
    The cross-reference logic needs Plex titles to match Sonarr/Radarr titles, files registered as `hasFile` in Sonarr/Radarr, and a season beyond the one under test to be monitored (so Sonarr doesn't treat the seeded season as "current"). Building this seed data is fiddly enough that it's worth scripting if you do it more than once.

**4. Check test instance logs if anything looks wrong**

```bash
ssh 192.168.2.15 "tail -f /tmp/arr-mcp-test.log"
```

**5. Restore production config and tear down the test instance**

```bash
# Restore production MCP config
cp .mcp.json.prod .mcp.json
```

Reload the MCP connection in your Claude client to reconnect to production.

Then choose how much to clean up:

```bash
# Stop arr-mcp and bring containers down — leaves ~/arr-mcp-test intact for next run
bash scripts/test-deploy.sh --stop

# Full teardown — removes containers, volumes, logs, and ~/arr-mcp-test entirely
bash scripts/test-deploy.sh --clean
```

Use `--stop` when you plan to test the same branch again shortly. Use `--clean` when you're done and want nothing left on the server.

---

## Test environment reference

| Command | What it does |
|---|---|
| `bash scripts/test-deploy.sh BRANCH=foo` | Deploy branch, start test stack + arr-mcp on `:8082` |
| `bash scripts/test-deploy.sh --stop` | Kill arr-mcp, bring containers down |
| `bash scripts/test-deploy.sh --clean` | Full teardown — removes everything from the server |

!!! note "No `make` on Windows"
    If you're running from a Windows terminal, use `bash scripts/test-deploy.sh` directly. `make` targets work from inside the dev container or a Linux/macOS terminal.

---

## Test stack

The test stack is defined in `test-stack/compose.yaml`. It runs four lightweight services:

| Container | Image | Port |
|---|---|---|
| `test-sabnzbd` | `linuxserver/sabnzbd` | `18080` |
| `test-sonarr` | `linuxserver/sonarr` | `18989` |
| `test-radarr` | `linuxserver/radarr` | `17878` |
| `test-plex` | `linuxserver/plex` | `33400` |

These use non-standard ports so they never conflict with production. Config and data land in `test-stack/data/` on the server, which is excluded from git.

---

## Environment variables (test instance)

The deploy script generates `.env.test` on the server automatically. The values it uses:

| Variable | Value | Notes |
|---|---|---|
| `ARR_MCP_PORT` | `8082` | Separate from production on `8081` |
| `ARR_MCP_API_KEY` | `test-key-local` | Matches `.mcp.json.test` |
| `ARR_MCP_SERVICES_DIR` | `~/arr-mcp-test/test-stack/data` | Points at test service configs |
| `ARR_MCP_COMPOSE_DIR` | `~/arr-mcp-test/test-stack` | Points at test stack |
| `ARR_MCP_DASHBOARD_PUBLIC` | `true` | No key required for test dashboard |

To override any of these, set the corresponding env var before running the deploy script:

```bash
TEST_API_KEY=my-custom-key make test-deploy BRANCH=feat/foo
```

---

## Commit guidelines

- Use [Conventional Commits](https://www.conventionalcommits.org/): `feat:`, `fix:`, `chore:`, `docs:`, `test:`
- Reference the GitHub issue: `git commit --trailer "Github-Issue:#<number>"`
- One branch per issue — name it `feat/issue-N-short-description` or `fix/issue-N-short-description`
- Never commit directly to `main` — all changes go through a PR
- Run the [pre-PR checklist](#pre-pr-checklist) before opening a PR
