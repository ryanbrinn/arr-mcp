---
name: manual-testing
description: Stand up a local, disposable arr-mcp instance with seeded test data and walk the dashboard to verify a feature or spec. Activate before opening a PR for a UI/dashboard change, or when investigating a bug that needs a running stack.
compatibility: Requires Docker (with Compose v2), uv
allowed-tools: Bash(scripts/test-stack.sh:*) Bash(git:*)
---

# Manual testing

Verify dashboard/UI changes against a real running instance before opening a
PR, using a local containerized stack seeded with representative data.

## Workflow

1. Start the stack (optionally on a specific branch to test):

   ```bash
   bash scripts/test-stack.sh up [branch]
   ```

   This brings up Sonarr, Radarr, SABnzbd, Plex, and arr-mcp itself as
   containers on a shared network, seeds Sonarr/Radarr with a representative
   media library, seeds the media-interest cache, and seeds a local admin
   account (`admin` / `password123`).

2. Wait for `http://localhost:8081/health` to return 200.

3. Use the Claude Preview tools against `http://localhost:8081`:
   - `preview_start` (if not already running)
   - Sign in with the seeded admin account
   - `preview_snapshot` / `preview_click` / `preview_screenshot` to navigate
     to and exercise the relevant dashboard page

4. Compare observed behavior against the relevant `docs/specs/*.md` and
   `docs/adr/*.md` documents.

5. When done:

   ```bash
   bash scripts/test-stack.sh down
   ```

   (or leave it running for iterative testing — `up` is idempotent and safe
   to re-run).

To fully wipe seeded data and start clean: `bash scripts/test-stack.sh reset`.

## Known limitations

- **Stack-management tools** (compose/quadlet conversion, the host helper
  from ADR-0002) aren't exercised by this setup — there's no host helper
  process in the container. Container list/logs/stats/start/stop work fine
  via the mounted Docker socket.
- **Plex OAuth login** can't be tested end-to-end without a real plex.tv
  account. Use the seeded local admin account for dashboard testing, and rely
  on unit/integration tests for Plex-specific auth flows.
- **Watched-cleanup previews** (`watched_cleanup_preview`,
  `movie_watched_cleanup_preview`) require Sonarr/Radarr to report
  `has_file: true` for seeded media, which the current seed data does not
  provide — these tools will show nothing to act on in this stack.

## This is the local counterpart to `scripts/test-deploy.sh`

`scripts/test-deploy.sh` deploys to a shared remote host for remote/shared
manual testing. `scripts/test-stack.sh` is fully local and disposable — use
it for day-to-day verification during development.
