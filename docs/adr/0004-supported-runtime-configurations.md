# ADR-0004: Supported Runtime Configurations

| | |
|---|---|
| **Status** | Accepted |
| **Date** | 2026-06-01 |

## Context

arr-mcp can theoretically run alongside several different container runtime configurations. However, not all configurations provide equivalent functionality or are worth maintaining as first-class supported targets. This ADR defines which configurations are officially supported, which are explicitly not supported, and why.

## Decision

Three configurations are officially supported. Two are explicitly out of scope.

## Supported configurations

### 1. Docker with Docker Engine

The container runtime is Docker, managed via the Docker socket (`/var/run/docker.sock`). Containers are started and managed directly via the Docker CLI or API.

**Suitable for:** Users already running Docker who want to add arr-mcp without changing their setup.

**Limitations:** No systemd integration — containers must be manually restarted or managed via Docker's own restart policies.

---

### 2. Docker with Docker Compose

Same as above, with containers defined in a `compose.yaml` file and managed via `docker compose`.

**Suitable for:** Users who prefer declarative stack definitions and are comfortable with Docker Compose workflows.

**Limitations:** Stack management tools require the host-side helper agent (ADR-0002) to function when arr-mcp runs inside a container.

---

### 3. Podman (rootless) with Quadlets

The container runtime is rootless Podman, with service lifecycle managed by systemd via quadlet unit files (`~/.config/containers/systemd/*.container`). Services start on boot via systemd lingering.

**Suitable for:** The primary target deployment — a dedicated media service account running rootless Podman on Debian/Ubuntu.

**Advantages over Docker:**
- No root daemon required
- Full systemd integration — services restart on reboot, obey dependency ordering
- Security isolation via user namespaces
- Native quadlet support in modern Podman (v4.4+)

**Limitations:** Quadlet and systemd management requires the host-side helper agent (ADR-0002).

---

## Unsupported configurations

### ❌ Podman (rootless) with podman-compose

**Reason:** `podman-compose` has no systemd integration. Containers started via `podman-compose up` do not survive system reboots unless a separate crontab or systemd unit is written to restart the compose stack — a fragile, non-standard approach that provides no benefits over the Docker Compose configuration and loses the advantages of the Podman quadlet model.

Users who want Podman should use quadlets. Users who want compose-style workflows should use Docker Compose.

---

### ❌ Podman (rooted)

**Reason:** Root Podman loses the primary security benefit of Podman (unprivileged operation) and provides no meaningful advantage over Docker. It uses the same socket model, the same daemon architecture, and the same operational complexity — but with a less mature tooling ecosystem.

Users choosing rooted container management should use Docker instead.

---

## Consequences

- Documentation, run examples, and configuration must cover all three supported configurations
- The Getting Started guide must clearly indicate which configuration is being described
- The host-side helper agent (ADR-0002, issue #13) is required to fully support both the Podman+Quadlets and Docker Compose configurations
- Future features must be evaluated against all three supported configurations before being documented as available
- Users asking about unsupported configurations should be directed to this ADR
