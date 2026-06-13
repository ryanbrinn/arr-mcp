#!/usr/bin/env bash
# Local, disposable test stack for manual testing — runs arr-mcp itself as a
# container alongside the test-stack services via `docker compose`, all on
# one machine. This is the local counterpart to scripts/test-deploy.sh (which
# deploys to a shared remote host); see docs/contributing.md for when to use
# which.
#
# Usage:
#   scripts/test-stack.sh up [branch]   Start the stack (optionally check out
#                                        <branch> first), seed test data, and
#                                        print the dashboard URL.
#   scripts/test-stack.sh down          Stop the stack.
#   scripts/test-stack.sh reset         Stop the stack, remove volumes, and
#                                        delete test-stack/data/.
#   scripts/test-stack.sh logs [service]  Tail logs for the stack (or one
#                                          service).

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STACK_DIR="$ROOT_DIR/test-stack"
COMPOSE="docker compose -f $STACK_DIR/compose.yaml --env-file $STACK_DIR/.env --profile local"

cmd="${1:-}"

case "$cmd" in
  up)
    branch="${2:-}"
    if [[ -n "$branch" ]]; then
      echo "Checking out branch '$branch'..."
      git -C "$ROOT_DIR" checkout "$branch"
    fi

    if [[ ! -f "$STACK_DIR/.env" ]]; then
      echo "Creating test-stack/.env from .env.example..."
      cp "$STACK_DIR/.env.example" "$STACK_DIR/.env"
    fi

    echo "Ensuring data directories exist..."
    mkdir -p "$STACK_DIR/data/sonarr" "$STACK_DIR/data/radarr" \
      "$STACK_DIR/data/sabnzbd" "$STACK_DIR/data/plex" \
      "$STACK_DIR/data/media/tv" "$STACK_DIR/data/media/movies"

    echo "Copying seed configs..."
    for svc in sonarr radarr; do
      if [[ -d "$STACK_DIR/seed/$svc" ]]; then
        cp -n "$STACK_DIR/seed/$svc"/* "$STACK_DIR/data/$svc/" 2>/dev/null || true
      fi
    done
    if [[ -f "$STACK_DIR/seed/credentials.local.json" ]]; then
      cp -n "$STACK_DIR/seed/credentials.local.json" \
        "$STACK_DIR/data/.arr-mcp-credentials.json" 2>/dev/null || true
    fi

    echo "Starting containers..."
    $COMPOSE up -d --build

    echo "Seeding media library test data..."
    bash "$STACK_DIR/seed-media.sh" || echo "WARNING: media seed failed, continuing."

    echo "Seeding media interest cache..."
    (cd "$ROOT_DIR" && uv run python scripts/seed_interest_cache.py \
      --output "$STACK_DIR/data/.arr-mcp-media-interest-cache.json") \
      || echo "WARNING: interest cache seed failed, continuing."

    echo "Seeding local admin user..."
    (cd "$ROOT_DIR" && uv run python scripts/seed_users.py \
      --services-dir "$STACK_DIR/data") \
      || echo "WARNING: user seed failed, continuing."

    echo ""
    echo "Test stack is up."
    echo "  Dashboard : http://localhost:8081/"
    echo "  Admin     : admin / password123"
    echo "To stop: scripts/test-stack.sh down"
    ;;

  down)
    $COMPOSE down
    ;;

  reset)
    $COMPOSE down --volumes
    rm -rf "$STACK_DIR/data"
    echo "Removed test-stack/data."
    ;;

  logs)
    service="${2:-}"
    $COMPOSE logs -f $service
    ;;

  *)
    echo "Usage: $0 {up [branch]|down|reset|logs [service]}"
    exit 1
    ;;
esac
