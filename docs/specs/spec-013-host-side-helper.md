# Spec: Host-side helper agent

| | |
|---|---|
| **Issue** | [#13](https://github.com/ryanbrinn/arr-mcp/issues/13) |
| **ADR** | [ADR-0002](../adr/0002-host-side-helper-agent.md) |
| **Phase** | 1 — MVP |
| **Status** | Ready for implementation (spike complete) |
| **Blocks** | #12 (stack management), #17 (compose ↔ quadlet conversion) |

## Problem

arr-mcp runs inside a container. The Podman binary, `podman-compose`, `systemctl`, and the quadlet directory are all on the host and are not accessible from inside the container. This makes all stack management tools non-functional in the primary deployment model.

## Goal

A small host-side helper process (`arr-helper`) that runs as the service account on the host, exposes a Unix domain socket, and executes a minimal, well-defined set of commands on behalf of arr-mcp. The socket is bind-mounted into the arr-mcp container.

---

## Architecture

```
arr-mcp container
      │  HTTP/JSON over Unix socket
      ▼
 arr-helper (host process, runs as `media` user)
      │
      ├── podman-compose up/down/pull/restart
      ├── systemctl --user start/stop/restart/status/daemon-reload
      └── read/write ~/.config/containers/systemd/*.container
```

The helper has no inbound network exposure — it communicates only through the socket.

---

## Protocol

**HTTP/JSON over a Unix domain socket.**

- arr-mcp uses `httpx` (already a dependency) with `transport=httpx.AsyncHTTPTransport(uds=socket_path)`
- All requests are `POST /command` with a JSON body
- All responses are JSON with a consistent envelope (see below)
- The socket path is configurable via `HELPER_SOCKET` env var (default: `/run/arr-helper/arr-helper.sock`)

### Request envelope

```json
{
  "op": "<operation>",
  "args": { "<key>": "<value>" }
}
```

### Response envelope

```json
{
  "ok": true,
  "output": "<stdout/stderr combined>",
  "exit_code": 0
}
```

On error:

```json
{
  "ok": false,
  "error": "<human-readable message>",
  "exit_code": 1
}
```

---

## API surface

The helper exposes a single endpoint: `POST /command`. The `op` field selects the operation. No other routes exist.

### Stack operations

| op | args | Host command |
|---|---|---|
| `stack_up` | `stack: str` | `podman-compose -f /opt/stacks/<stack>/compose.yaml up -d` |
| `stack_down` | `stack: str` | `podman-compose -f /opt/stacks/<stack>/compose.yaml down` |
| `stack_pull` | `stack: str` | `podman-compose -f /opt/stacks/<stack>/compose.yaml pull` |
| `stack_restart` | `stack: str` | `stack_down` then `stack_up` |
| `compose_validate` | `stack: str` | `podman-compose -f /opt/stacks/<stack>/compose.yaml up --dry-run` |

### Systemd operations

| op | args | Host command |
|---|---|---|
| `systemd_start` | `unit: str` | `systemctl --user start <unit>` |
| `systemd_stop` | `unit: str` | `systemctl --user stop <unit>` |
| `systemd_restart` | `unit: str` | `systemctl --user restart <unit>` |
| `systemd_status` | `unit: str` | `systemctl --user status <unit>` |
| `systemd_daemon_reload` | _(none)_ | `systemctl --user daemon-reload` |

### Quadlet operations

| op | args | Behaviour |
|---|---|---|
| `quadlet_read` | `name: str` | Read `~/.config/containers/systemd/<name>.container`, return contents |
| `quadlet_write` | `name: str`, `content: str` | Write `~/.config/containers/systemd/<name>.container` |
| `quadlet_list` | _(none)_ | List all `.container` files in the quadlet directory |
| `quadlet_delete` | `name: str` | Delete `~/.config/containers/systemd/<name>.container` |

**No other operations are supported.** The helper must reject unknown `op` values with HTTP 400.

---

## Security

### Socket permissions
- Socket is created with mode `0600`, owned by the service account (UID 1000)
- The bind-mount in `compose.yaml`/quadlet maps `host_path:/run/arr-helper/arr-helper.sock`
- No other process on the host can connect without being UID 1000

### Input validation
- `stack` names are validated against `^[a-zA-Z0-9_-]+$` — no path traversal
- `unit` names are validated against `^[a-zA-Z0-9_@.-]+\.service$` or `^[a-zA-Z0-9_@.-]+\.container$`
- `name` (quadlet) validated against `^[a-zA-Z0-9_-]+$`
- `content` (quadlet write) has a 64 KB maximum size
- Any validation failure → HTTP 400, no command executed

### No arbitrary shell execution
- All commands are built from a fixed template — no string interpolation of user input into shell commands
- Use `asyncio.create_subprocess_exec` (not `shell=True`) for all subprocess calls

### Logging
- Every request is logged: timestamp, op, args (excluding content), exit_code
- Log to stdout so systemd/quadlet captures it via journald

---

## Deployment

The helper runs as a systemd user service managed by a quadlet `.container` file **or** as a plain systemd user service (`.service` unit). For Phase 1, a plain systemd user service is preferred — simpler, fewer dependencies.

### Unit file: `arr-helper.service`

```ini
[Unit]
Description=arr-mcp host-side helper agent
After=network.target

[Service]
ExecStart=/home/media/.local/bin/arr-helper
Restart=on-failure
RuntimeDirectory=arr-helper
RuntimeDirectoryMode=0700

[Install]
WantedBy=default.target
```

`RuntimeDirectory=arr-helper` causes systemd to create `/run/user/<UID>/arr-helper/` automatically, owned by the service account, mode 0700. The socket is placed here.

### arr-mcp volume mount

In the arr-mcp container:

```yaml
volumes:
  - /run/user/1000/arr-helper/arr-helper.sock:/run/arr-helper/arr-helper.sock:ro
```

The socket mount is read-only from the container's perspective (arr-mcp writes HTTP requests; the socket itself is managed by the helper).

---

## arr-mcp integration

### New module: `src/arr_mcp/helper/client.py`

A thin async client that wraps the socket communication:

```python
class HelperClient:
    async def call(self, op: str, **args: str) -> HelperResponse: ...
    async def is_available(self) -> bool: ...
```

`is_available()` attempts a no-op request and returns `False` (not an exception) if the socket does not exist or the helper is not running.

### Settings

Add to `config.py`:

```python
helper_socket: str = "/run/arr-helper/arr-helper.sock"
```

### Stack tools update

`stacks.py` currently calls `podman-compose` as a subprocess. Replace these calls with `HelperClient.call(op, stack=name)`. If the helper is unavailable, return a clear error message explaining that the host-side helper is required for stack management.

### Graceful degradation

When the helper socket is not present or the helper is not responding:
- Stack management tools return: `"Stack management requires the arr-helper agent running on the host. See docs/setup.md."`
- No exception is raised to the MCP client
- The condition is logged at WARNING level

---

## Helper implementation

The helper is a small Python script (or compiled binary — TBD) in `src/arr_helper/`. It uses the Python standard library only — no additional dependencies beyond what arr-mcp already pulls in.

### Module layout

```
src/arr_helper/
    __main__.py       # entry point, starts the server
    server.py         # Unix socket HTTP server
    handlers.py       # op dispatch table
    validation.py     # input validators
    subprocess.py     # subprocess execution helpers
```

### Entry point

`arr-helper` is registered as a script entry point in `pyproject.toml`:

```toml
[project.scripts]
arr-helper = "arr_helper.__main__:main"
```

This means `uv run arr-helper` starts the helper locally for development.

---

## Tests required

### Unit tests (`tests/helper/`)

| Test | Description |
|---|---|
| `test_validation_stack_name` | Valid and invalid stack name patterns |
| `test_validation_unit_name` | Valid and invalid unit name patterns |
| `test_validation_quadlet_name` | Valid and invalid quadlet name patterns |
| `test_unknown_op_rejected` | Unknown `op` → 400 response |
| `test_content_size_limit` | `quadlet_write` with >64 KB content → 400 |

### Integration tests (`tests/helper/test_client.py`)

| Test | Description |
|---|---|
| `test_helper_unavailable_returns_false` | `is_available()` returns `False` when socket missing |
| `test_stack_tools_degrade_gracefully` | Stack tools return helpful message when helper unavailable |

Full integration tests against a real helper process are out of scope for Phase 1 — cover with mocked socket responses.

---

## Out of scope

- TLS or token auth on the socket — Unix socket file permissions are sufficient for Phase 1
- Multiple simultaneous helper connections — sequential request handling is fine for Phase 1
- Windows or macOS support — Linux / rootless Podman only
- Arbitrary shell execution — never
