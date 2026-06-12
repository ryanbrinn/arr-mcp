# Roadmap

## Overview

arr-mcp is built in four phases, each with a clear architectural goal and a verification step before moving forward. The phases are intentionally sequential — Phase 2 should not begin until Phase 1 is verified complete. Within a phase, items are ordered by priority rather than scheduled to dates — the order below reflects what's tackled first, not when.

---

## Phase Summary

| Phase | Status | Focus |
|---|---|---|
| **Phase 1 — MVP** | Done | Solid, secure, well-tested foundation |
| **Phase 2 — Media Intelligence & MVP Completion** | In progress | Cross-app intelligence (delivered) + remaining MVP gaps: auth, test-stack, docs |
| **Phase 3 — Usability** | Not started | Features that make arr-mcp approachable for non-technical users, including the installation wizard |
| **Phase 4 — Advanced Features** | Not started | Opt-in, config-driven scope expansion for advanced users |

---

## Phase 1 — MVP

### Architectural goal
Build a solid, secure, well-tested foundation that a technical user can deploy today with confidence. Every tool should work correctly, every operation should be safe, and the codebase should be maintainable by anyone picking it up cold.

### What this phase delivers

| Area | Goal |
|---|---|
| **Tools** | All MCP tools functional and tested — containers, stacks, filesystem, logs |
| **Security** | Filesystem operations scoped to owned resources; no privilege escalation possible |
| **Stack management** | Works correctly when arr-mcp runs inside a container (host-side helper) |
| **Migration** | Compose ↔ Quadlet conversion so users can move between Docker and Podman |
| **Frontend** | Read-only dashboard showing container status, disk usage, and stack health |
| **Documentation** | MkDocs site live, ADRs written, CLAUDE.md complete |
| **Quality** | CI passing — ruff, mypy, pytest — on every PR |
| **Diagnostics** | Service API reachability checks, inter-service probes, download path verification |

### Guardrails
- No Phase 2 API integrations (Plex, Sonarr, Radarr, SABnzbd APIs) until Phase 1 is verified complete
- No user authentication features until the dashboard baseline exists
- No installation wizard work until the tools it would install are stable

### Verification checklist
Before declaring Phase 1 complete, confirm:

- [ ] All MCP tools return correct results against a live stack
- [ ] `file_read` / `file_write` reject root-owned paths via `_check_path`
- [ ] `stack_list` and `directory_list` do not expose root-owned directories
- [ ] Stack restart/up/down works via the host-side helper
- [ ] Dashboard loads, auto-refreshes, and shows accurate container status
- [ ] MkDocs site is live on GitHub Pages
- [ ] All tests pass in CI with no skips related to unimplemented features
- [ ] No open `phase-1` security issues

---

## Phase 2 — Media Intelligence & MVP Completion

### Architectural goal
Integrate with the APIs of the media stack applications (Plex, Sonarr, Radarr, SABnzbd) to enable cross-application intelligence that no single app provides — watched content cleanup, storage optimisation, health monitoring, and multi-user protection. Additionally, close the remaining gaps that stand between the current state and a real MVP: robust authentication, a usable local test-stack, and accurate documentation.

Phase 2 is built on a layered service client architecture. The foundation must land before any feature work:

1. **CredentialStore** — secure per-service credential management (never in compose files)
2. **BaseServiceClient** — shared async HTTP client; all service integrations extend this
3. **ArrClient** — shared Sonarr/Radarr/Lidarr behaviour (same API schema)
4. **Per-service clients** — SonarrClient, RadarrClient, PlexClient, SABnzbdClient

Only once that foundation exists should the higher-level features (watched cleanup, alerting, version tracking) be built on top of it.

See [Architecture — Phase 2 Service Layer](architecture.md#phase-2-service-client-layer) for the full design.

### Delivered (done)

| Area | Goal |
|---|---|
| **Credential management** | Secure per-service credential store; env-var override for CI/testing |
| **Service client layer** | `BaseServiceClient`, `ArrClient`, per-service subclasses |
| **API integrations** | Read/write access to Plex, Sonarr, Radarr, SABnzbd APIs |
| **Watched cleanup** | Identify and safely delete fully-watched seasons, with per-user protection |
| **Alert monitoring** | Scheduled checks against configured thresholds; emit notifications |
| **Version tracking** | Poll GitHub releases / Docker Hub tags; surface upgrade recommendations |
| **Log monitoring** | Scheduled error detection across all applications |
| **Multi-user** | Plex authentication on the dashboard; per-user watchlists; deletion protection |
| **Storage** | Surface large, duplicate, and unwatched content for review |

### Remaining priorities (current focus)

1. **Multi-provider authentication & strict access control**
   - Sign-in options: Plex (if detected on the system), local
     username/password managed by the app, account creation, and other OAuth
     identity providers (e.g. Google)
   - No unauthenticated access to any page — every route redirects to sign-in
     until authenticated
   - Extends the existing Plex OAuth + session-cookie implementation
     (`src/arr_mcp/dashboard/auth.py`, ADR-0008), which was designed to allow
     additional providers

2. **Test-stack usability & automation**
   - `test-stack/` environment matches production shape: all env files
     present with realistic mock values, and enough seed data to exercise
     every feature (extends `test-stack/compose.yaml`, `seed-media.sh`,
     `seed_interest_cache.py`)
   - New **manual-testing** skill: spin up a test-stack instance from a given
     branch and walk the dashboard to confirm a feature/spec
   - Follow-up (not built in this phase): configurable test instances —
     choice of media player (Plex/Jellyfin) and authentication scheme

3. **Documentation refresh**
   - Sync `mkdocs.yml` nav with the actual ADR inventory (ADR-0005–0008 exist
     but aren't linked from nav or `docs/adr/index.md`)
   - Reconcile root `CONTRIBUTING.md` with the authoritative
     `docs/contributing.md`
   - Remove orphaned exploratory docs (dashboard mockups, unreferenced specs)
   - General accuracy pass across end-user and contributor docs

### Guardrails
- API credentials for Plex/Sonarr/Radarr/SABnzbd must be stored securely — never in compose files or quadlets
- All service HTTP calls must go through `BaseServiceClient` — no one-off inline `httpx` clients in tool code
- Deletion operations must always require explicit confirmation and check all user watchlists first
- Jellyfin support is future state — design the auth layer to be provider-agnostic but don't implement it in this phase
- No installation wizard work in this phase

### Verification checklist
Before declaring Phase 2 complete, confirm:

- [ ] Plex watch history is readable and correctly cross-referenced with Sonarr library
- [ ] Watched season cleanup presents correct results and does not delete protected content
- [ ] Log monitoring correctly detects and surfaces errors from all applications
- [ ] Dashboard requires sign-in via at least one provider and shows per-user watchlist state
- [ ] No page is reachable without authentication — unauthenticated requests redirect to sign-in
- [ ] Users can sign in via Plex (if detected), local username/password, or another configured OAuth provider, and can create a new local account
- [ ] Deletion of watchlisted content is blocked with a clear user-facing message
- [ ] Alert rules can be configured and fire correctly
- [ ] Version checker surfaces new releases with parsed release notes
- [ ] The local test-stack mirrors production env shape with realistic seed data, and the manual-testing skill can stand up an instance from a branch and walk the dashboard
- [ ] `mkdocs.yml` nav reflects the full ADR inventory and end-user/contributor docs are accurate
- [ ] All Phase 1 verification criteria still pass (no regression)

---

## Phase 3 — Usability

### Architectural goal
Make arr-mcp approachable for non-technical users — both during initial setup and in day-to-day use. The installation wizard is the headline item, but this phase covers usability work more broadly as gaps are identified.

### Items (priority order)

1. **Installation wizard** — self-bootstrapping setup: a non-technical user
   should be able to go from a fresh Debian/Ubuntu machine to a fully running
   media server stack by following the guided wizard, with no manual
   configuration required.

   | Area | Goal |
   |---|---|
   | **System check** | Verify OS, runtime availability, disk space, network before starting |
   | **Runtime setup** | Configure rootless Podman, socket activation, and systemd lingering |
   | **Stack scaffolding** | Generate quadlet files or compose file for chosen services |
   | **Directory structure** | Create and permission the `/media-server/` layout |
   | **Configuration** | Walk through API key setup, download client, and indexer configuration |
   | **Validation** | Verify all services are healthy and correctly connected at the end |

   Guardrails for this item:
   - Every wizard step must be non-destructive and reversible where possible
   - Partial installs must be detectable and resumable — no silent failures
   - Jellyfin must be supported as an alternative to Plex from the start
   - The wizard must work through the dashboard UI, not just chat

Additional usability items will be appended here as they're identified.

### Verification checklist
Before declaring Phase 3 complete, confirm:

- [ ] A fresh Debian/Ubuntu VM can complete the wizard from start to finish without manual intervention
- [ ] A partial install can be detected and resumed correctly
- [ ] All services pass health checks at the end of the wizard
- [ ] Jellyfin path is available as an alternative to Plex
- [ ] All Phase 1 and Phase 2 verification criteria still pass (no regression)

---

## Phase 4 — Advanced Features

### Architectural goal
Give advanced users explicit, opt-in ways to widen arr-mcp's default safety scope on their own terms — without weakening the safe-by-default posture established in Phase 1 (#52) for everyone else. This phase is for capabilities that intentionally trade a larger blast radius for more power, aimed at users who understand and accept that trade-off.

### What this phase delivers

| Area | Goal |
|---|---|
| **Tiered access** | Static, config-driven model for unlocking infrastructure-level tools (nginx, fail2ban, certbot) beyond the default media-stack scope (#54) |

### Guardrails
- Expanded access must be configured statically (install time / config file edit) — never toggled at runtime via MCP tools
- Unlocking infrastructure-level tools must surface a clear, persistent warning that they affect network security and availability
- Default scope for new installs remains the media stack only — advanced tiers are strictly opt-in
- Cloudflare/tunnel/CDN management stays out of scope for direct control; at most, read-only health/status visibility may be considered

### Verification checklist
Before declaring Phase 4 complete, confirm:

- [ ] Tier/allowlist configuration is read only from static config — no MCP tool can change it at runtime
- [ ] Unlocking an advanced tier surfaces a clear warning in both the dashboard and tool responses
- [ ] Default (media-only) installs are unaffected and remain the out-of-the-box behaviour
- [ ] All Phase 1, 2, and 3 verification criteria still pass (no regression)

---

## Project alignment reviews

At the end of each phase, before beginning the next, conduct a structured review:

1. **Did we deliver what we said we would?** — Walk through the verification checklist item by item
2. **Did we introduce any technical debt?** — Identify anything that was deferred and create issues
3. **Are the ADRs still accurate?** — Update any that have been superseded by decisions made during the phase
4. **Has the goal shifted?** — If the project's purpose or target audience has changed, update this roadmap and CLAUDE.md before proceeding
5. **Is the codebase in a state we're proud of?** — Run the full test suite, check coverage, review open security issues
