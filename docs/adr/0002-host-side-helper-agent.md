# ADR-0002: Host-Side Helper Agent for Stack and Systemd Management

| | |
|---|---|
| **Status** | Investigating |
| **Date** | 2026-06-01 |
| **Decided** | 2026-06-01 |
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

**Investigating Option C — Host-side helper agent.**

Direction is set: a small host-side process running as the service account, communicating with arr-mcp via a bind-mounted Unix socket. This is an **architectural spike** — the approach is committed to, but the following implementation details are still under investigation:

- Exact API surface (which commands the helper exposes)
- Protocol over the socket (HTTP/JSON vs lightweight custom protocol)
- Deployment mechanism for the helper itself (quadlet, systemd unit, or packaged alongside arr-mcp)
- How the helper handles authentication/authorisation to prevent abuse

**Working hypothesis: Unix socket + JSON over HTTP**

A simple HTTP/JSON API over a Unix socket is the leading candidate:

- **gRPC**: Well-typed but adds significant complexity and build tooling
- **Custom binary protocol**: Minimal overhead but hard to debug and extend
- **HTTP/JSON over Unix socket**: Familiar pattern (same as Podman/Docker API), easy to test with `curl`, straightforward to extend, no extra dependencies

This hypothesis will be validated during the spike. The API surface must be minimal — no arbitrary shell execution. Only explicitly defined operations will be exposed.

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

## Consequences

- arr-mcp gains full stack lifecycle management on rootless Podman
- The helper must be deployed separately alongside arr-mcp — documentation and packaging will need to cover this
- The helper's socket must be permission-restricted to UID 1000 only
- All helper operations must be logged for auditability
- The arr-mcp run command gains one additional volume mount for the helper socket
