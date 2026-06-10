# ADR-0008: Authentication Strategy

| | |
|---|---|
| **Status** | Accepted |
| **Date** | 2026-06-08 |
| **Issue** | [#135](https://github.com/ryanbrinn/arr-mcp/issues/135) |

## Context

Phase 2 introduces the user interest model (#131), which requires stable, trustworthy user identity — arr-mcp needs to know *who* is marking content for deletion or protection. The current auth mechanism (a shared `?key=` query param) provides no user identity; everyone who has the key is the same anonymous actor.

Two separate concerns need to be addressed:

1. **Human dashboard users** need to identify themselves so their interest states, review queue actions, and deletion approvals are attributed correctly.
2. **Claude (MCP client)** needs to authenticate its tool calls, but it is a single programmatic actor with no concept of OAuth flows.

Additionally, the tool is self-hosted. Any auth mechanism that requires an external cloud service to be reachable imposes an availability dependency on the user's media server. This must be considered.

## Decision

Authentication is split by surface:

### MCP endpoint — Bearer token (unchanged)

`Authorization: Bearer <key>` remains the auth mechanism for `/mcp`. Static, pre-shared, set via `ARR_MCP_API_KEY`. Claude never does OAuth; adding any identity complexity here would break all existing MCP integrations.

### Dashboard — Plex OAuth

Human users authenticate via Plex OAuth, the same pattern used by Overseerr. The flow:

1. User visits dashboard → redirected to sign-in page if no valid session
2. "Sign in with Plex" button opens `app.plex.tv/auth` in a popup
3. User approves → Plex returns an auth token
4. arr-mcp validates the token against the local Plex server (`PlexClient`) — confirms the user is a Plex user *on this server*, not just any Plex account
5. Session cookie (signed with `ARR_MCP_SESSION_SECRET`) is issued
6. `plex_id` from the Plex user record becomes the stable `user_id` in `InterestStore`

### LAN-only fallback

`DASHBOARD_PUBLIC=true` bypasses all dashboard auth, preserving the existing behaviour for users who don't want any auth on a trusted LAN. When set, no Plex server is required for dashboard access.

### Admin designation

Admin role is config-driven: `ARR_MCP_ADMIN_PLEX_USERS` (comma-separated Plex usernames). This is set at deploy time and is not toggleable at runtime via any MCP tool or dashboard action. Admins can: approve the review queue, override inactive-user interest states, and perform content deletions.

## Options considered

### Option A: Shared API key for dashboard (current state, rejected for Phase 2)

Simple, but provides no user identity. Cannot support per-user interest states or per-user deletion protection. The entire interest model depends on knowing who is acting.

### Option B: Local username/password accounts (rejected)

Requires arr-mcp to manage a user database, password hashing, reset flows, and account creation UX. All of this already exists in Plex — reinventing it is pure overhead with no benefit for the target user (someone who already has a Plex server).

### Option C: Google OAuth (deferred, not rejected)

Technically feasible. Adds a GCP project dependency and OAuth credentials to manage. Critically, a Google identity doesn't map to a Plex user — a linking step would be required to connect Google identity to the Plex users sharing the server. Lower value, higher complexity than Plex auth for this specific domain.

### Option D: Plex OAuth (chosen)

Users already have Plex accounts. The Plex server is already the source of truth for who's allowed to use the media stack. Plex user IDs are stable and unique — they slot directly into `InterestStore` as `user_id` without any mapping layer. Validation is against the *local* Plex server, so it works on a LAN without internet if Plex is running locally (Plex typically requires internet for OAuth; see consequences).

## Consequences

- **Positive**: No separate user database — Plex is the source of truth for identity.
- **Positive**: Plex user IDs map directly to `InterestStore` keys; no identity translation layer needed.
- **Positive**: Familiar flow for users of Overseerr or similar tools.
- **Positive**: MCP/Claude auth is completely unaffected.
- **Positive**: `DASHBOARD_PUBLIC=true` preserves the simple LAN-only mode for users who don't need multi-user identity.
- **Negative**: Plex OAuth requires `app.plex.tv` to be reachable during sign-in. If the user's internet is down, sign-in fails. Existing sessions (session cookie) remain valid until expiry.
- **Negative**: Users must have a Plex account and be a member of the Plex server to access the dashboard. Non-Plex users cannot access arr-mcp without `DASHBOARD_PUBLIC=true`.
- **Note**: Google auth and Jellyfin auth are explicitly deferred. The auth provider pattern should be designed to allow adding providers later without changing the session or role model.
