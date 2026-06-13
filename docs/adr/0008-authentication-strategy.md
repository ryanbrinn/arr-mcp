# ADR-0008: Authentication Strategy

| | |
|---|---|
| **Status** | Accepted |
| **Date** | 2026-06-08 |
| **Revised** | 2026-06-12 — restructured around `AppUser` identity for #192 |
| **Issue** | [#135](https://github.com/ryanbrinn/arr-mcp/issues/135), [#192](https://github.com/ryanbrinn/arr-mcp/issues/192) |

## Context

Phase 2 introduces the user interest model (#131), which requires stable, trustworthy user identity — arr-mcp needs to know *who* is marking content for deletion or protection. The current auth mechanism (a shared `?key=` query param) provides no user identity; everyone who has the key is the same anonymous actor.

Two separate concerns need to be addressed:

1. **Human dashboard users** need to identify themselves so their interest states, review queue actions, and deletion approvals are attributed correctly.
2. **Claude (MCP client)** needs to authenticate its tool calls, but it is a single programmatic actor with no concept of OAuth flows.

Additionally, the tool is self-hosted. Any auth mechanism that requires an external cloud service to be reachable imposes an availability dependency on the user's media server. This must be considered.

#192 raised a further requirement: per-user functionality (interest states,
watchlists) must remain stable as a user adopts additional linked accounts
(Plex now, Jellyfin/Google later) or signs in via a local account instead.
Tying `InterestStore` keys directly to a Plex user ID does not survive a
multi-provider future, and #192 also requires that the dashboard never be
reachable without authentication (no `DASHBOARD_PUBLIC` bypass).

## Decision

Authentication is split by surface:

### MCP endpoint — Bearer token (unchanged)

`Authorization: Bearer <key>` remains the auth mechanism for `/mcp`. Static, pre-shared, set via `ARR_MCP_API_KEY`. Claude never does OAuth; adding any identity complexity here would break all existing MCP integrations.

### Dashboard — `AppUser` identity with linked providers

A single internal identity model, `AppUser` (`src/arr_mcp/services/users.py`),
is the source of truth for per-user state. Each `AppUser` has a stable
`app_user_id` (uuid4) and a `linked_identities` map (e.g. `{"plex": "12345"}`).
`InterestStore` and all other per-user records key on `app_user_id`, not on
any single provider's identity — so switching login methods, or adding a
second linked provider, never changes a user's interest history.

Two ways to authenticate into an `AppUser`:

**Plex OAuth** (existing flow, retained):

1. User visits dashboard → redirected to sign-in page if no valid session
2. "Sign in with Plex" button opens `app.plex.tv/auth`
3. User approves → Plex returns an auth token
4. arr-mcp validates the token against the local Plex server (`PlexClient`) — confirms the user is a Plex user *on this server*, not just any Plex account
5. The resulting Plex user ID is looked up via `UserStore.find_by_linked_identity("plex", plex_id)`. If found, that `AppUser` is reused (profile refreshed from Plex). If not found, a new `AppUser` is auto-provisioned and linked — preserving the prior behaviour where any Plex user on the server could sign in.
6. Session cookie (signed with `ARR_MCP_SESSION_SECRET`) is issued, keyed on `app_user_id`.

**Local accounts** (new):

- `POST /auth/local/login` verifies a username/password against `UserStore`
  (pbkdf2-hmac-sha256, per-account salt, 260,000 iterations).
- Accounts are created via `/auth/setup` (first-run only) — there is no
  general self-registration endpoint.

**Account linking**:

- `/auth/link/plex/*` lets a signed-in user (regardless of how they
  authenticated) link a Plex account to their existing `AppUser`. This is the
  mechanism that keeps interest state unified as a person adopts more
  providers.

### First-run setup (replaces `DASHBOARD_PUBLIC`)

The dashboard always requires a session — there is no unauthenticated bypass
beyond the existing `?key=<ARR_MCP_API_KEY>` query-param escape hatch for
programmatic access. To bootstrap the very first account, `/auth/setup` is
shown whenever `UserStore` is empty, offering both a local-admin form and
"Sign in with Plex." Whichever completes first becomes `AppUser` #1 with
`is_admin=True`, unconditionally. Once `UserStore` has any user, `/auth/setup`
redirects to `/auth/signin`.

### Admin designation

Admin status is derived from, in order of precedence:

1. The very first `AppUser` ever created (always admin).
2. The Plex home-user `admin` flag (`PlexClient.get_home_users()`), checked on
   each Plex login.
3. `ARR_MCP_ADMIN_USERS` (comma-separated usernames) — a manual grant,
   primarily for local accounts or shared-user setups where the Plex `admin`
   flag isn't applicable.

Admin status is **sticky**: once granted, it is never automatically revoked on
a subsequent login, even if the Plex home-user flag or `admin_users` list no
longer grants it. Admins can: approve the review queue, override
inactive-user interest states, and perform content deletions.

## Options considered

### Option A: Shared API key for dashboard (current state, rejected for Phase 2)

Simple, but provides no user identity. Cannot support per-user interest states or per-user deletion protection. The entire interest model depends on knowing who is acting.

### Option B: Local username/password accounts (adopted, #192)

Originally rejected as pure overhead given Plex already provides identity.
#192 revisited this: requiring Plex for *every* user closes out non-Plex
households and gives no bootstrap path once `DASHBOARD_PUBLIC` is removed.
Local accounts, scoped to first-run setup plus optional additional accounts,
provide that bootstrap with minimal added surface (stdlib `hashlib.pbkdf2_hmac`,
no new dependency).

### Option C: Google OAuth (deferred, not rejected)

Technically feasible. Adds a GCP project dependency and OAuth credentials to manage. The `AppUser`/`linked_identities` model introduced by #192 makes this a pure additive change — a new `create_linked`/`find_by_linked_identity` call and a route pair, no further session or model changes. Tracked as a follow-up issue.

### Option D: Plex OAuth (chosen, retained)

Users already have Plex accounts. The Plex server is already the source of truth for who's allowed to use the media stack. Plex user IDs are stable and unique, and now map to `AppUser.linked_identities["plex"]` rather than directly to `InterestStore` keys — preserving the original benefit while allowing other providers to coexist.

## Consequences

- **Positive**: `AppUser`/`linked_identities` is a pluggable mechanism for future providers (Jellyfin, Google) — adding one is a new `create_linked`/`find_by_linked_identity` call plus routes, no further session or model changes.
- **Positive**: Interest state and other per-user records are stable across login method changes, because they key on `app_user_id`.
- **Positive**: First-run setup provides a bootstrap path without any unauthenticated dashboard mode.
- **Positive**: MCP/Claude auth is completely unaffected.
- **Negative**: Plex OAuth requires `app.plex.tv` to be reachable during sign-in. If the user's internet is down, sign-in fails. Existing sessions (session cookie) remain valid until expiry.
- **Negative**: Existing `InterestStore` records keyed by raw Plex user ID (pre-#192) will not match the new `app_user_id`-keyed records and will fall back to the protective `interested` default. No migration script is provided.
- **Negative**: Pre-#192 session cookies (missing the `uid` claim) fail verification and simply force re-login — no migration code needed.
- **Note**: Follow-up issue filed — "Add Google/Jellyfin identity providers to dashboard auth," building on `AppUser`/`linked_identities`.
