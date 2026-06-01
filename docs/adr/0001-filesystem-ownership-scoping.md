# ADR-0001: Filesystem Ownership Scoping

| | |
|---|---|
| **Status** | Accepted |
| **Date** | 2026-06-01 |
| **Issue** | [#10](https://github.com/ryanbrinn/arr-mcp/issues/10) |

## Context

arr-mcp is an MCP server that accepts natural language instructions from Claude. Because Claude acts on behalf of a user, a crafted or malicious prompt could instruct arr-mcp to read, write, or operate on files it should have no access to.

The specific trigger for this decision was discovering that `/opt/stacks` contained a `fail2ban` directory owned by root. Without any ownership checks, arr-mcp would:

- List `fail2ban` alongside user-owned stacks
- Allow `file_read` and `file_write` on any file within it (subject only to filesystem permissions)
- Allow `compose_write` to overwrite its compose file

The broader concern is that path-prefix checking alone is not a sufficient security boundary. An attacker who knows (or can guess) a path can bypass directory listing restrictions entirely and target files directly.

## Decision

All filesystem operations in arr-mcp are scoped to resources owned by the same UID as the running process. This is enforced at the `_check_path()` level — the single chokepoint through which all filesystem tools pass — so the guard cannot be bypassed by targeting tools individually.

Specifically:

1. When a path is under `stacks_dir`, the ownership of the stack root directory (the first subdirectory under `stacks_dir`) is checked against `os.getuid()` before any operation is permitted.
2. `stack_list` and `directory_list` silently exclude directories not owned by the current user when iterating the stacks root.
3. Direct stack operations (`compose_read`, `compose_write`, `stack_up`, etc.) reject non-owned stacks with a generic "not found" error to avoid leaking the existence of the directory.

A shared helper `is_owned_by_current_user(path)` in `tools/utils.py` performs the UID check. On non-Linux platforms where `os.getuid()` is unavailable, it returns `True` unconditionally so development and testing on Windows are unaffected.

## Options considered

### Option A: Allowlist specific stack names (rejected)

Maintain an explicit list of permitted stacks in config. Rejected because it requires manual maintenance and fails open if a new root-owned directory appears.

### Option B: Path-prefix checking only (current state, rejected)

Only check that paths fall under allowed roots. Rejected because it provides no protection against operating on resources owned by other users within those roots.

### Option C: UID-based ownership scoping (chosen)

Check that the owning UID of the relevant directory matches the process UID. Automatic, requires no configuration, and correctly excludes any resource the process doesn't own regardless of how it got there.

## Consequences

- **Positive**: Root-owned directories within allowed roots are invisible and inaccessible to arr-mcp regardless of how the prompt is crafted.
- **Positive**: No configuration required — ownership is determined dynamically at runtime.
- **Positive**: Defence in depth — even if a future tool bypasses the listing guard, `_check_path` will still reject the operation.
- **Negative**: On shared systems where multiple non-root users own stacks in the same directory, only stacks owned by the arr-mcp process UID will be accessible. This is intentional and consistent with the principle of least privilege.
- **Note**: This does not prevent access to files within a user-owned stack that happen to be owned by root (e.g. files created by a container running as root). A future ADR may address intra-stack file ownership.
