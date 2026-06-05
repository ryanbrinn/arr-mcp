#!/usr/bin/env bash
# Usage: scripts/test-deploy.sh BRANCH=<branch-name>
#
# SSHes to TEST_HOST, checks out the given branch to ~/arr-mcp-test/,
# starts the test stack, and runs arr-mcp on port 8082 against it.
# Production instance on port 8081 is not touched.
#
# Prerequisites:
#   - SSH key access to TEST_HOST
#   - Docker Compose available on TEST_HOST
#   - TEST_HOST env var set, or edit the default below
#
# To stop the test instance: scripts/test-deploy.sh --stop

set -euo pipefail

TEST_HOST="${TEST_HOST:-192.168.2.15}"
TEST_USER="${TEST_USER:-ryanbrinn}"
TEST_PORT="${TEST_PORT:-8082}"
TEST_DIR="${TEST_DIR:-\$HOME/arr-mcp-test}"
TEST_API_KEY="${TEST_API_KEY:-test-key-local}"
REPO_URL="https://github.com/ryanbrinn/arr-mcp.git"

# --- parse args ---
BRANCH=""
STOP=false

for arg in "$@"; do
  case $arg in
    BRANCH=*) BRANCH="${arg#BRANCH=}" ;;
    --stop)   STOP=true ;;
    *) echo "Unknown argument: $arg"; exit 1 ;;
  esac
done

if $STOP; then
  echo "Stopping test instance on $TEST_HOST..."
  ssh "$TEST_USER@$TEST_HOST" "
    set -e
    cd $TEST_DIR 2>/dev/null || exit 0
    pkill -f 'arr-mcp.*8082' 2>/dev/null || true
    docker compose -f test-stack/compose.yaml down 2>/dev/null || true
    echo 'Test instance stopped.'
  "
  exit 0
fi

if [[ -z "$BRANCH" ]]; then
  echo "Error: BRANCH is required."
  echo "Usage: $0 BRANCH=<branch-name>"
  exit 1
fi

echo "Deploying branch '$BRANCH' to $TEST_HOST:$TEST_PORT..."

ssh "$TEST_USER@$TEST_HOST" "
  set -e

  # Clone or update the repo
  if [ -d $TEST_DIR/.git ]; then
    cd $TEST_DIR
    git fetch --all --prune
  else
    git clone $REPO_URL $TEST_DIR
    cd $TEST_DIR
  fi

  cd $TEST_DIR
  git checkout '$BRANCH'
  git pull origin '$BRANCH' 2>/dev/null || true

  # Install deps
  command -v uv >/dev/null 2>&1 || curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
  uv sync --quiet

  # Ensure test stack data dirs exist
  mkdir -p test-stack/data/sonarr test-stack/data/radarr

  # Start test stack containers
  docker compose -f test-stack/compose.yaml up -d
  echo 'Test stack containers started.'

  # Kill any existing test arr-mcp instance
  pkill -f 'arr-mcp.*$TEST_PORT' 2>/dev/null || true
  sleep 1

  # Write a local .env for the test instance
  cat > .env.test <<EOF
ARR_MCP_PORT=$TEST_PORT
ARR_MCP_API_KEY=$TEST_API_KEY
ARR_MCP_SERVICES_DIR=$TEST_DIR/test-stack/data
ARR_MCP_MEDIA_DIR=$TEST_DIR/test-stack/data
ARR_MCP_CONTAINER_RUNTIME=docker-compose
ARR_MCP_COMPOSE_DIR=$TEST_DIR/test-stack
ARR_MCP_DASHBOARD_PUBLIC=true
EOF

  # Start arr-mcp in the background, logging to a file
  nohup uv run arr-mcp > /tmp/arr-mcp-test.log 2>&1 &
  echo \$! > /tmp/arr-mcp-test.pid

  sleep 2
  if kill -0 \$(cat /tmp/arr-mcp-test.pid) 2>/dev/null; then
    echo ''
    echo 'arr-mcp test instance is running.'
    echo \"  Dashboard : http://$TEST_HOST:$TEST_PORT/\"
    echo \"  MCP URL   : http://$TEST_HOST:$TEST_PORT/mcp\"
    echo \"  API key   : $TEST_API_KEY\"
    echo \"  Logs      : ssh $TEST_USER@$TEST_HOST tail -f /tmp/arr-mcp-test.log\"
    echo ''
    echo 'Swap .mcp.json.test into .mcp.json to point Claude at the test instance.'
    echo 'To stop: scripts/test-deploy.sh --stop'
  else
    echo 'ERROR: arr-mcp failed to start. Check logs:'
    cat /tmp/arr-mcp-test.log
    exit 1
  fi
"
