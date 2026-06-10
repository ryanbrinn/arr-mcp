# Documentation Roadmap

Status of every documentation artifact in `docs/`. Use this as the checklist before declaring a phase complete and as the audit trail for keeping docs in sync with code.

| Status | Meaning |
|---|---|
| ✅ Current | Accurate and up to date |
| ⚠️ Needs update | Exists but has known gaps or stale content |
| ❌ Missing | Does not exist yet; must be written |

---

## Core docs

| Doc | Status | Notes |
|---|---|---|
| [architecture.md](../architecture.md) | ✅ Current | Updated with Phase 2 service layer, AI provider, interest model, dashboard redesign, shared service layer principle, and full tool inventory |
| [roadmap.md](../roadmap.md) | ✅ Current | Gantt chart reflects all Phase 1–4 items; Phase 2 has 9 milestones |
| [tools.md](../tools.md) | ✅ Current | Phase 1 tools documented with verdicts; Phase 2 planned tools added (media library, alerts/upgrades, AI diagnostics) |
| [security.md](../security.md) | ✅ Current | Updated with CredentialStore, AI provider security, InterestStore, and expanded threat model |
| [configuration.md](../configuration.md) | ✅ Current | Phase 2 service integration and AI provider env vars added |
| [getting-started.md](../getting-started.md) | ⚠️ Needs update | Phase 1 focused; will need a Phase 2 section covering credential setup and AI provider config |
| [contributing.md](../contributing.md) | ✅ Current | No phase-specific content; review before Phase 3 |
| [index.md](../index.md) | ⚠️ Needs update | MkDocs home — review after dashboard redesign ships |
| [lessons-learned.md](../lessons-learned.md) | ⚠️ Needs update | Capture decisions from this session: shared service layer rule, compound tool pattern, interest model vs quorum model |

---

## ADRs

| ADR | Status | Notes |
|---|---|---|
| [ADR-0001 Filesystem ownership scoping](../adr/0001-filesystem-ownership-scoping.md) | ✅ Current | |
| [ADR-0002 Host-side helper agent](../adr/0002-host-side-helper-agent.md) | ✅ Current | |
| [ADR-0003 Frontend strategy](../adr/0003-frontend-strategy.md) | ⚠️ Needs update | Describes "Option C — read-only Jinja2 dashboard". Now needs to reflect the two-tab redesign (#132) and the `POST /api/diagnose` endpoint |
| [ADR-0004 Supported runtime configurations](../adr/0004-supported-runtime-configurations.md) | ✅ Current | |
| [ADR-0005](../adr/0005-ai-provider-strategy.md) AI provider strategy | ✅ Current | Configurable Ollama / Anthropic / none; Ollama default; graceful degradation |
| [ADR-0006](../adr/0006-user-interest-model.md) User interest model | ✅ Current | 3-state model replaces watch-quorum; admin review queue for inactive users |
| [ADR-0007](../adr/0007-shared-service-layer.md) Shared service layer | ✅ Current | MCP tools and dashboard routes as thin adapters over shared service functions |
| [ADR-0008](../adr/0008-authentication-strategy.md) Authentication strategy | ✅ Current | Plex OAuth for dashboard; Bearer token for MCP; LAN fallback preserved |

---

## Specs

| Spec | Status | Notes |
|---|---|---|
| [spec-011-file-delete.md](spec-011-file-delete.md) | ✅ Current | Shipped in Phase 1 |
| [spec-013-host-side-helper.md](spec-013-host-side-helper.md) | ✅ Current | Shipped in Phase 1 |
| [spec-014-dashboard.md](spec-014-dashboard.md) | ⚠️ Needs update | Describes the Phase 1 single-page dashboard; must be updated or superseded when #132 (tabbed redesign) is implemented |
| [spec-017-compose-quadlet-conversion.md](spec-017-compose-quadlet-conversion.md) | ✅ Current | Shipped in Phase 1 |
| spec for #105 CredentialStore | ❌ Missing | Write before implementation begins |
| spec for #106 BaseServiceClient + ArrClient + ServiceRegistry | ❌ Missing | Write before implementation begins |
| spec for #107 SonarrClient + RadarrClient | ❌ Missing | Write before implementation begins |
| spec for #108 PlexClient | ❌ Missing | Write before implementation begins |
| spec for #109 Watched cleanup rewrite | ❌ Missing | Write before implementation begins |
| spec for #110 AlertWatcher | ❌ Missing | Write before implementation begins |
| spec for #111 VersionChecker | ❌ Missing | Write before implementation begins |
| spec for #131 User interest model (InterestStore) | ❌ Missing | Write before implementation begins |
| spec for #132 Dashboard redesign | ❌ Missing | Write before implementation begins; reference `docs/dashboard-mockup.html` |
| spec for #133 Contextual AI diagnostics | ❌ Missing | Write before implementation begins |
| spec for #134 AI provider abstraction | ❌ Missing | Write before implementation begins |

---

## Documentation discipline rules

1. **Spec before PR.** Every Phase 2 issue needs a spec in `docs/specs/` before implementation begins. The spec is the contract the PR is reviewed against.
2. **ADR before merge.** Any architectural decision captured in the list above must have its ADR written before the first PR that implements it merges.
3. **Gantt on close.** When a PR closes a Gantt item, mark it `:done` in `docs/roadmap.md` in the same commit.
4. **tools.md stays authoritative.** Every new MCP tool must be added to `docs/tools.md` in the same PR that introduces it. No tool ships without a row in the table.
5. **architecture.md gets the file.** Every new source file introduced in Phase 2 must have a row in the Phase 2 component table in `docs/architecture.md`.
