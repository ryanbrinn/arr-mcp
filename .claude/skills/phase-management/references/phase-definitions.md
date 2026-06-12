# Phase Definitions and Guardrails

## Phase overview

| Phase | Goal |
|---|---|
| **Phase 1 — MVP** | Solid, secure, well-tested foundation. All tools working. Dashboard. Documentation. |
| **Phase 2 — Media Intelligence & MVP Completion** | Plex/-arr API integrations, watched content cleanup, log monitoring, multi-user support (delivered) + remaining MVP gaps: multi-provider authentication with no unauthenticated access, a usable local test-stack with a manual-testing skill, and a documentation accuracy pass. |
| **Phase 3 — Usability** | Features that make arr-mcp approachable for non-technical users, including the installation wizard as the headline item. |
| **Phase 4 — Advanced Features** | Opt-in, config-driven ways for advanced users to widen the default safety scope without weakening it for everyone else. |

## Guardrails — what NOT to build yet

**In Phase 2, do not:**
- No installation wizard or other Phase 3 usability work
- No Jellyfin support (future state — design for it, don't build it)
- No Phase 4 features — the default media-stack scope must stay solid first

**In Phase 3, do not:**
- Build Phase 4 features — advanced/opt-in scope changes come after the wizard is stable.

**In Phase 1 (reference):**
- No Plex, Sonarr, Radarr, or SABnzbd API integration
- No user authentication or watchlist features
- No installation wizard work
- No Phase 2/3/4 features even if they seem "quick"
