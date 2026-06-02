# Spec: Compose ↔ Quadlet conversion tools

| | |
|---|---|
| **Issue** | [#17](https://github.com/ryanbrinn/arr-mcp/issues/17) |
| **Phase** | 1 — MVP |
| **Status** | Ready for implementation |
| **Depends on** | [#13](https://github.com/ryanbrinn/arr-mcp/issues/13) for full quadlet write support |

## Problem

Users migrating between Docker Compose and rootless Podman with systemd (quadlets) must manually rewrite service definitions. The field mappings are mechanical and error-prone. arr-mcp is well-positioned to automate this — it already reads compose files and understands the stacks directory layout.

## Goal

Two new MCP tools:

- `compose_to_quadlets(stack)` — reads a `compose.yaml` and generates `.container` quadlet files for each service
- `quadlets_to_compose(stack)` — reads `.container` quadlet files and generates a `compose.yaml`

Both tools are **non-destructive** — they write to a staging location and never overwrite without confirmation. Full quadlet directory access requires the host-side helper (#13); before that is available, generated files are written to the stacks directory for manual installation.

---

## Tool specifications

### `compose_to_quadlets(stack: str) -> list[TextContent]`

```
Reads /opt/stacks/<stack>/compose.yaml and generates a .container quadlet file
for each service. Writes output to /opt/stacks/<stack>/quadlets/ (staging).
Returns a summary of files written and any unsupported fields encountered.
```

**Behaviour:**

1. Locate `compose.yaml` via the existing `_stack_path()` / `compose_read` logic
2. Parse the YAML (use `PyYAML`, already a dependency)
3. For each service in `services:`, generate a `.container` file (see field mapping below)
4. Write to `/opt/stacks/<stack>/quadlets/<service>.container`
5. Create the `quadlets/` directory if it does not exist
6. Return a summary:
   - Files written (one line per file)
   - Unsupported fields encountered (warnings, not errors)
   - Instruction for installing: copy files to `~/.config/containers/systemd/` and run `systemctl --user daemon-reload`
7. If the host-side helper (#13) is available, offer to install directly — but do not auto-install without a follow-up confirmation call

**Error conditions:**

| Condition | Response |
|---|---|
| Stack not found | Error: `"Stack not found: <name>"` |
| No compose file found | Error: `"No compose file found in /opt/stacks/<stack>"` |
| Invalid YAML | Error: `"Could not parse compose.yaml: <parse error>"` |
| No `services:` key | Error: `"compose.yaml has no services defined"` |

---

### `quadlets_to_compose(stack: str) -> list[TextContent]`

```
Reads .container quadlet files from /opt/stacks/<stack>/quadlets/ and generates
a compose.yaml. Writes output to /opt/stacks/<stack>/compose.from-quadlets.yaml.
```

**Behaviour:**

1. Read `.container` files from `/opt/stacks/<stack>/quadlets/`
2. If the helper is available, also offer to read from the live quadlet directory — but default to the stacks directory
3. Parse each file as INI (use Python's `configparser`)
4. Reconstruct a `compose.yaml` structure
5. Write to `/opt/stacks/<stack>/compose.from-quadlets.yaml` (never overwrite `compose.yaml` directly)
6. Return the generated YAML content and the path it was written to

**Error conditions:**

| Condition | Response |
|---|---|
| Stack not found | Error: `"Stack not found: <name>"` |
| No quadlet files found | Error: `"No .container files found in /opt/stacks/<stack>/quadlets/"` |
| Malformed quadlet file | Warning in output, skip the file and continue |

---

## Field mapping: Compose → Quadlet

Each service produces a `.container` file with four sections:

```ini
[Unit]
Description=<service name>
After=network-online.target
Wants=network-online.target

[Container]
Image=<image>
ContainerName=<container_name or service name>
# Environment, Volume, PublishPort, Network — one per line each

[Service]
Restart=<mapped restart policy>

[Install]
WantedBy=default.target
```

### Field mapping table

| Compose field | Quadlet section | Quadlet field | Notes |
|---|---|---|---|
| `image` | `[Container]` | `Image` | Direct |
| `container_name` | `[Container]` | `ContainerName` | Falls back to service name |
| `environment` (map or list) | `[Container]` | `Environment` | One `Environment=KEY=VAL` per entry |
| `volumes` | `[Container]` | `Volume` | One `Volume=host:container[:opts]` per entry |
| `ports` | `[Container]` | `PublishPort` | One `PublishPort=host:container` per entry |
| `networks` | `[Container]` | `Network` | One `Network=<name>` per entry |
| `restart: unless-stopped` | `[Service]` | `Restart=always` | |
| `restart: always` | `[Service]` | `Restart=always` | |
| `restart: no` | `[Service]` | `Restart=no` | |
| `restart: on-failure` | `[Service]` | `Restart=on-failure` | |
| `depends_on` | `[Unit]` | `After=<svc>.service` | One `After=` per dependency |
| `healthcheck.test` | `[Container]` | `HealthCmd` | Strip `CMD` / `CMD-SHELL` prefix |
| `healthcheck.interval` | `[Container]` | `HealthInterval` | |
| `healthcheck.timeout` | `[Container]` | `HealthTimeout` | |
| `healthcheck.retries` | `[Container]` | `HealthRetries` | |

### Unsupported compose fields (warn, do not fail)

The following fields have no quadlet equivalent and are noted as warnings in the output:

- `build:` — quadlets require pre-built images
- `profiles:` — no quadlet equivalent
- `deploy:` — Swarm-specific, ignored
- `extends:` — resolve before conversion or warn
- Complex `healthcheck.test` with shell logic

---

## Field mapping: Quadlet → Compose

| Quadlet field | Compose field | Notes |
|---|---|---|
| `Image` | `image` | |
| `ContainerName` | `container_name` | |
| `Environment` (repeated) | `environment` | List format |
| `Volume` (repeated) | `volumes` | |
| `PublishPort` (repeated) | `ports` | |
| `Network` (repeated) | `networks` | |
| `Restart=always` | `restart: unless-stopped` | Conservative mapping |
| `Restart=no` | `restart: "no"` | |
| `Restart=on-failure` | `restart: on-failure` | |
| `After=<svc>.service` | `depends_on: [<svc>]` | Strip `.service` suffix |
| `HealthCmd` | `healthcheck.test` | Prepend `CMD-SHELL` |
| `HealthInterval` | `healthcheck.interval` | |
| `HealthTimeout` | `healthcheck.timeout` | |
| `HealthRetries` | `healthcheck.retries` | |

---

## Implementation

### New module: `src/arr_mcp/tools/conversion.py`

```python
def register_conversion_tools(server: FastMCP, settings: Settings) -> None:
    """Register compose ↔ quadlet conversion tools."""

    @server.tool()
    async def compose_to_quadlets(stack: str) -> list[TextContent]: ...

    @server.tool()
    async def quadlets_to_compose(stack: str) -> list[TextContent]: ...
```

### Parser helpers (keep in `conversion.py` or a sibling `quadlet.py`)

- `parse_compose(path: Path) -> dict` — wraps `yaml.safe_load`, validates top-level structure
- `service_to_quadlet(name: str, service: dict) -> str` — returns the `.container` file content as a string
- `parse_quadlet(path: Path) -> dict` — wraps `configparser`, returns a normalised dict
- `quadlets_to_compose_dict(quadlets: list[dict]) -> dict` — returns a compose structure

Keeping the converters as pure functions (no I/O) makes them straightforward to unit test.

### Registration

Add `register_conversion_tools` call in `server.py` alongside the other `register_*` calls.

---

## Tests required

File: `tests/tools/test_conversion.py`

### Unit tests (pure conversion logic)

| Test | Description |
|---|---|
| `test_service_to_quadlet_basic` | Image, container_name, environment, volumes, ports → correct `.container` output |
| `test_service_to_quadlet_restart_mapping` | All four restart policies map correctly |
| `test_service_to_quadlet_depends_on` | `depends_on` → `After=` in `[Unit]` |
| `test_service_to_quadlet_healthcheck` | Full healthcheck fields mapped correctly |
| `test_service_to_quadlet_unsupported_fields` | `build:` key → warning string in output, not an error |
| `test_quadlet_to_service_basic` | Reverse mapping of basic fields |
| `test_quadlet_to_service_restart_mapping` | `Restart=always` → `restart: unless-stopped` |

### Integration tests (file I/O)

| Test | Description |
|---|---|
| `test_compose_to_quadlets_writes_files` | Given a temp stack with `compose.yaml`, files appear in `quadlets/` |
| `test_compose_to_quadlets_no_overwrite` | Running twice does not raise — files are overwritten in staging (it's safe) |
| `test_compose_to_quadlets_stack_not_found` | Returns error message, no exception |
| `test_compose_to_quadlets_invalid_yaml` | Parse error → clean error message |
| `test_quadlets_to_compose_writes_file` | Given `.container` files, `compose.from-quadlets.yaml` is written |
| `test_quadlets_to_compose_no_files` | Empty staging dir → error message |
| `test_roundtrip` | Compose → quadlets → compose produces equivalent services (order-insensitive) |

---

## Out of scope

- Direct installation to `~/.config/containers/systemd/` — requires helper (#13), deferred
- Support for `docker-compose.yml` v2 syntax (`version:` key) — only v3 / Compose Spec supported
- Podman-specific extensions (e.g. `x-podman:`) — ignored, not generated
- Validation that the generated quadlet files are syntactically correct beyond field mapping
