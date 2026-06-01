# Security Model

## Principles

arr-mcp is designed around a minimal-privilege, ownership-scoped security model. The following principles govern all filesystem and container operations.

### 1. Operations are scoped to owned resources only

arr-mcp may only read, write, or operate on files and directories owned by the same UID as the running process. Directories owned by other users (e.g. root-owned stacks) are silently excluded from listings and rejected from direct access.

See [ADR-0001](adr/0001-filesystem-ownership-scoping.md).

### 2. Filesystem access is bounded by allowed roots

All filesystem operations are restricted to explicitly configured allowed roots:

- `/opt/stacks` — stack compose files
- `/media-server` — media storage
- `/var/log` — log files

Paths outside these roots, including path traversal attempts (`../`), are rejected with a `PermissionError`.

### 3. Destructive operations require explicit confirmation

Any operation that removes or stops a resource requires `confirm=True` to be passed explicitly. This prevents accidental destructive actions from ambiguous prompts.

### 4. No privilege escalation

arr-mcp runs as an unprivileged user (UID 1000) and has no mechanism to switch users, escalate privileges, or execute arbitrary shell commands. The container has no `sudo`, no `setuid` binaries, and communicates with the runtime exclusively via the Podman/Docker socket API.

### 5. API key authentication on all endpoints

All MCP endpoints require a `Authorization: Bearer <key>` header. The `/health` endpoint is the only exception. Keys should be set via `ARR_MCP_API_KEY` and rotated regularly.

## Threat model

| Threat | Mitigation |
|---|---|
| Crafted prompt reads root-owned config | Ownership check in `_check_path` blocks access |
| Crafted prompt writes to root-owned directory | Ownership check rejects before write |
| Path traversal outside allowed roots | `_check_path` resolves and prefix-checks all paths |
| Unauthenticated MCP access | Bearer token required on all routes |
| Prompt causes user switching | No `su`/`sudo`/`setuid` available in container |
| Socket access from other containers | Socket bind-mount is restricted to arr-mcp container |

## Known limitations

- Stack management tools (`stack_up`, `stack_down`, etc.) require `podman-compose` on the host and are non-functional when arr-mcp runs inside a container. See [issue #12](https://github.com/ryanbrinn/arr-mcp/issues/12).
- Quadlet/systemd management is not yet supported. See [issue #13](https://github.com/ryanbrinn/arr-mcp/issues/13).
