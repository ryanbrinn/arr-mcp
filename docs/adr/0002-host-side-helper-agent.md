# ADR-0002: Host-Side Helper Agent for Stack and Systemd Management

| | |
|---|---|
| **Status** | Proposed |
| **Date** | 2026-06-01 |
| **Issues** | [#12](https://github.com/ryanbrinn/arr-mcp/issues/12), [#13](https://github.com/ryanbrinn/arr-mcp/issues/13) |

## Context

arr-mcp runs inside a container with access to the Podman/Docker socket. This gives it full container lifecycle control (start, stop, restart, logs, stats) but it cannot:

- Run `podman-compose` — the binary is not in the container
- Run `systemctl --user` — D-Bus session is not available inside the container
- Read or write quadlet files — they live in `~/.config/containers/systemd/` on the host

On rootless Podman installations, quadlets and systemd are the proper way to manage service lifecycles. Without this capability, arr-mcp cannot:

- Start/stop stacks persistently across reboots
- Reload changed compose files (`systemctl --user daemon-reload`)
- Manage stacks the way Dockge does

This is a significant gap given that replacing Dockge is a core project goal.

## Decision

_Not yet decided. This ADR captures the options under consideration._

## Options considered

### Option A: Use the Podman REST API directly

Replace `podman-compose` subprocess calls with direct Podman API calls for compose-equivalent operations. Avoids the binary dependency entirely.

**Pros:** No new components, stays within the existing architecture.
**Cons:** Requires reimplementing compose orchestration logic (dependency ordering, network creation, volume management). Significant scope. Does not solve systemd/quadlet management.

### Option B: Bundle binaries in the container image

Include `podman`, `podman-compose`, and `systemctl` in the arr-mcp container image.

**Pros:** Simple deployment — single container.
**Cons:** Large image. `podman` inside a container requires privileged mode or nested virtualisation. `systemctl` cannot manage the host's systemd from inside a container. Fundamentally broken for quadlet management.

### Option C: Host-side helper agent (preferred)

A small, minimal process running on the host as the media user (UID 1000), exposing a Unix socket that arr-mcp communicates with. The helper executes:

- `podman-compose up/down/pull/restart`
- `systemctl --user start/stop/restart/status/daemon-reload`
- Quadlet file read/write in `~/.config/containers/systemd/`

The socket is bind-mounted into the arr-mcp container. The helper exposes a minimal, well-defined API — no arbitrary shell execution.

**Pros:** Solves both #12 and #13 cleanly. Keeps arr-mcp unprivileged. Minimal attack surface if the API is well-scoped. No changes to the container image.
**Cons:** Adds a new host-side component to deploy and maintain. Requires a deployment mechanism (quadlet or systemd unit for the helper itself).

## Consequences (if Option C is chosen)

- arr-mcp gains full stack lifecycle management on rootless Podman
- The helper must be deployed separately alongside arr-mcp — documentation and packaging will need to cover this
- The helper's socket must be permission-restricted to UID 1000 only
- All helper operations must be logged for auditability
- The arr-mcp run command gains one additional volume mount for the helper socket
