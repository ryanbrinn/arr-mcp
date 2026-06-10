# ADR-0006: User Interest Model for Content Deletion

| | |
|---|---|
| **Status** | Accepted |
| **Date** | 2026-06-08 |
| **Issue** | [#131](https://github.com/ryanbrinn/arr-mcp/issues/131) |

## Context

Phase 2 introduces watched content cleanup: identifying fully-watched series and seasons and deleting their files to reclaim disk space. The central design question is how to determine that content is safe to delete when multiple users share the media server.

The naive approach — require all users to have watched the content before marking it eligible — fails in households where users have non-overlapping tastes. A user who never watches a particular genre will never mark those shows as watched, permanently blocking cleanup of content they have no interest in keeping. The quorum model treats indifference and active interest identically, which is wrong.

A related problem: a user who has been inactive for months may still hold "interested" states that block deletion. Without an escape valve, stale interest from inactive users accumulates indefinitely.

## Decision

Replace the watch-quorum model with a per-user, per-content 3-state interest model stored in `InterestStore`.

### The three states

| State | Meaning | Effect on deletion |
|---|---|---|
| `interested` | User wants to keep this content | Hard block — no deletion while any user holds this state |
| `watched` | User has seen it; no preference | Neutral — does not block or require deletion |
| `marked_deletion` | User has explicitly approved removal | Positive signal toward cleanup |

### Eligibility rule

Content is eligible for deletion when **no user holds `interested` state** for it. The presence of `marked_deletion` states is a positive signal but not a hard requirement — if all known users are `watched` or `marked_deletion` and none are `interested`, cleanup can proceed.

### Granularity

States are tracked at `series`, `season`, or `episode` level. A state at a coarser granularity is inherited by finer-grained items unless explicitly overridden. A user who marks a series as `interested` protects all seasons and episodes unless they override a specific season.

### Admin review queue

When a user's last activity crosses a configurable inactivity threshold and they still hold `interested` state on content, that content moves to an admin review queue rather than becoming eligible automatically. An admin can:

- Override the inactive user's state and proceed with deletion
- Leave it protected (the default)

This prevents stale interest states from blocking cleanup indefinitely without silently discarding user preferences.

## Options considered

### Option A: Watch-quorum (rejected)

Delete when all users have watched the content. Fails when users have non-overlapping tastes — a user who never watches a show will never contribute to the quorum, blocking cleanup permanently.

### Option B: Majority-rules (rejected)

Delete when more than half of users have watched. Still punishes minority-taste content and doesn't distinguish between "haven't watched yet" and "actively not interested."

### Option C: 3-state interest model (chosen)

Explicitly separates indifference (`watched`) from active protection (`interested`) and active consent (`marked_deletion`). Users who have no opinion on a show don't block cleanup. Users who care either protect it or approve its removal. Admins have an escape valve for inactive users.

## Consequences

- **Positive**: Users who have no interest in a show don't block its cleanup — indifference is correctly modelled as neutral.
- **Positive**: Any user can protect content they care about by marking it `interested`, regardless of watch history.
- **Positive**: The admin review queue prevents stale states from accumulating indefinitely.
- **Positive**: Granularity (series/season/episode) lets users protect specific seasons of a show while allowing others to be cleaned up.
- **Negative**: Requires users to actively manage their interest states. A show no user has ever touched has no states — it defaults to no interest signal, which means cleanup could proceed. Initial state must default to `interested` or require explicit opt-in to cleanup, not opt-out.
- **Note**: The initial state question (opt-in vs opt-out cleanup) must be resolved during implementation of #131.
