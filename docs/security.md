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

### 6. API credentials are never stored in compose files

Phase 2 service integrations (Sonarr, Radarr, Plex, SABnzbd) require API keys. These are stored exclusively in `CredentialStore` — an encrypted JSON file inside the container's data volume. They are never written to compose files, quadlet units, or environment variables committed to version control.

Env-var overrides (`SONARR_API_KEY`, `PLEX_TOKEN`, etc.) take precedence for CI/testing but are never persisted by arr-mcp.

### 7. AI calls are always server-side

AI provider calls (Ollama, Anthropic) are made exclusively from the server. The browser and MCP client never communicate with an AI provider directly, so API keys are never exposed to the client. See [ADR-0005](adr/0005-ai-provider-strategy.md).

### 8. Interest states are not sensitive, but deletion is irreversible

`InterestStore` data (per-user content interest states) is stored unencrypted — it contains no credentials or personal information beyond watch preferences. However, because content deletion triggered by interest state resolution is irreversible, every deletion operation requires explicit user confirmation regardless of interest state. See [ADR-0006](adr/0006-user-interest-model.md).

## Threat model

| Threat | Mitigation |
|---|---|
| Crafted prompt reads root-owned config | Ownership check in `_check_path` blocks access |
| Crafted prompt writes to root-owned directory | Ownership check rejects before write |
| Path traversal outside allowed roots | `_check_path` resolves and prefix-checks all paths |
| Unauthenticated MCP access | Bearer token required on all routes |
| Prompt causes user switching | No `su`/`sudo`/`setuid` available in container |
| Socket access from other containers | Socket bind-mount is restricted to arr-mcp container |
| Service API key exposure | `CredentialStore` only — never in compose files or VCS |
| AI API key exposure to browser | All AI calls are server-side; client never receives keys |
| Accidental mass deletion | Every destructive operation requires `confirm=True` |
| Stale interest state blocking admin review | Inactivity threshold + admin override queue |
| AI agent reads service config via shell/SSH | Out of scope — see [Guardrail scope](#guardrail-scope) below |

## Guardrail scope

The security controls above protect the **MCP API surface**. They prevent the arr-mcp server from returning credential values through its tools, leaking sensitive files through `file_read`, or executing operations outside its allowed roots.

These controls are **not** a hard boundary against other access paths available to the same AI agent. If the agent running against arr-mcp also has shell access to the server (SSH credentials, a Bash tool, a terminal integration), it can read service config files directly — bypassing guardrails that only apply to MCP tool calls.

**What the guardrails protect against:**

- Accidental credential exposure through MCP tool responses
- Scope creep in what the MCP server can read or return
- A misconfigured or compromised MCP client extracting keys via the API

**What the guardrails do not protect against:**

- An AI agent with SSH or shell access to the same host
- Any process running as the same OS user as the arr-mcp server
- A human operator with normal server access

**The practical boundary:** the guardrails are meaningful when the AI's *only* path to the server is through the MCP tools. The moment the agent also has shell access, the MCP restrictions are bypassed by that channel — not by any flaw in arr-mcp itself.

See [Getting Started — SSH access warning](getting-started.md#a-note-on-ssh-access) for guidance on keeping these channels separate.

## Known limitations

- Stack management tools (`stack_up`, `stack_down`, etc.) require `podman-compose` on the host and are non-functional when arr-mcp runs inside a container. See [issue #12](https://github.com/ryanbrinn/arr-mcp/issues/12).
- Quadlet/systemd management is not yet supported. See [issue #13](https://github.com/ryanbrinn/arr-mcp/issues/13).
- `CredentialStore` encryption key (`ARR_MCP_SECRET`) must be set by the operator — there is no auto-generated default. If unset, Phase 2 service integrations will not start.
