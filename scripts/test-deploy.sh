#!/usr/bin/env bash
# Usage: scripts/test-deploy.sh BRANCH=<branch-name>
#
# SSHes to TEST_HOST, checks out the given branch to ~/arr-mcp-test/,
# starts the test stack, and runs arr-mcp on port 8082 against it.
# Production instance on port 8081 is not touched.
#
# Prerequisites:
#   - SSH key access to TEST_HOST
#   - Podman available on TEST_HOST
#
# To stop the test instance:       scripts/test-deploy.sh --stop
# To stop and remove everything:   scripts/test-deploy.sh --clean

set -euo pipefail

TEST_HOST="${TEST_HOST:-192.168.2.15}"
TEST_USER="${TEST_USER:-ryanbrinn}"
TEST_PORT="${TEST_PORT:-8082}"
TEST_API_KEY="${TEST_API_KEY:-test-key-local}"
REPO_URL="https://github.com/ryanbrinn/arr-mcp.git"

# --- parse args ---
BRANCH=""
STOP=false
CLEAN=false

for arg in "$@"; do
  case $arg in
    BRANCH=*) BRANCH="${arg#BRANCH=}" ;;
    --stop)   STOP=true ;;
    --clean)  CLEAN=true ;;
    *) echo "Unknown argument: $arg"; exit 1 ;;
  esac
done

# -- stop --
if $STOP; then
  echo "Stopping test instance on $TEST_HOST..."
  ssh "$TEST_USER@$TEST_HOST" bash <<ENDSSH
    pkill -f 'arr-mcp.*$TEST_PORT' 2>/dev/null || true
    cd \$HOME/arr-mcp-test 2>/dev/null || exit 0
    podman compose -f test-stack/compose.yaml down 2>/dev/null || true
    echo 'Test instance stopped.'
ENDSSH
  exit 0
fi

# -- clean (stop + remove everything) --
if $CLEAN; then
  echo "Cleaning up test environment on $TEST_HOST..."
  ssh "$TEST_USER@$TEST_HOST" bash <<ENDSSH
    pkill -f 'arr-mcp.*$TEST_PORT' 2>/dev/null || true
    if [ -d \$HOME/arr-mcp-test ]; then
      cd \$HOME/arr-mcp-test
      podman compose -f test-stack/compose.yaml down --volumes 2>/dev/null || true
      cd \$HOME
      rm -rf \$HOME/arr-mcp-test
    fi
    rm -f /tmp/arr-mcp-test.log /tmp/arr-mcp-test.pid
    echo 'Test environment fully removed.'
ENDSSH
  exit 0
fi

if [[ -z "$BRANCH" ]]; then
  echo "Error: BRANCH is required."
  echo "Usage: $0 BRANCH=<branch-name>"
  exit 1
fi

echo "Deploying branch '$BRANCH' to $TEST_USER@$TEST_HOST:$TEST_PORT..."

# Variables expanded locally (before sending to server): BRANCH, REPO_URL, TEST_PORT, TEST_API_KEY
# Variables escaped (\$HOME, \$PATH) expand on the remote server.
ssh "$TEST_USER@$TEST_HOST" bash <<ENDSSH
  set -e
  export PATH="\$HOME/.local/bin:\$PATH"

  # Clone or update the repo
  if [ -d \$HOME/arr-mcp-test/.git ]; then
    cd \$HOME/arr-mcp-test
    git fetch --all --prune
  else
    git clone $REPO_URL \$HOME/arr-mcp-test
    cd \$HOME/arr-mcp-test
  fi

  cd \$HOME/arr-mcp-test
  git checkout '$BRANCH'
  git pull origin '$BRANCH' 2>/dev/null || true

  # Always use test-stack from main — it may not exist on the branch under test
  git fetch origin main
  git checkout origin/main -- test-stack/

  # Install uv if missing
  command -v uv >/dev/null 2>&1 || curl -LsSf https://astral.sh/uv/install.sh | sh

  uv sync --quiet

  # Ensure test stack data dirs exist
  mkdir -p test-stack/data/sonarr test-stack/data/radarr

  # Start test stack containers (bring down first to ensure clean state)
  podman compose -f test-stack/compose.yaml down 2>/dev/null || true
  podman compose -f test-stack/compose.yaml up -d
  echo 'Test stack containers started.'

  # Kill any existing test arr-mcp instance and wait for port to free
  if [ -f /tmp/arr-mcp-test.pid ]; then
    kill \$(cat /tmp/arr-mcp-test.pid) 2>/dev/null || true
    rm -f /tmp/arr-mcp-test.pid
  fi
  pkill -f 'arr_mcp.server' 2>/dev/null || true
  for i in \$(seq 1 10); do
    ss -tlnp | grep -q ':$TEST_PORT ' || break
    sleep 1
  done

  # Write env file for the test instance
  USER_UID=\$(id -u)
  {
    echo "ARR_MCP_PORT=$TEST_PORT"
    echo "ARR_MCP_API_KEY=$TEST_API_KEY"
    echo "ARR_MCP_SERVICES_DIR=\$HOME/arr-mcp-test/test-stack/data"
    echo "ARR_MCP_MEDIA_DIR=\$HOME/arr-mcp-test/test-stack/data"
    echo "ARR_MCP_CONTAINER_RUNTIME=podman"
    echo "ARR_MCP_COMPOSE_DIR=\$HOME/arr-mcp-test/test-stack"
    echo "ARR_MCP_SOCKET_PATH=unix:///run/user/\${USER_UID}/podman/podman.sock"
    echo "ARR_MCP_DASHBOARD_PUBLIC=true"
  } > .env

  # Ensure Podman socket service is running for this user
  mkdir -p /run/user/\${USER_UID}/podman
  if ! XDG_RUNTIME_DIR=/run/user/\${USER_UID} podman system service --help >/dev/null 2>&1; then
    echo 'WARNING: podman system service not available'
  else
    XDG_RUNTIME_DIR=/run/user/\${USER_UID} podman system service --time=0 unix:///run/user/\${USER_UID}/podman/podman.sock &
    sleep 1
  fi

  # Start arr-mcp in the background
  nohup env XDG_RUNTIME_DIR=/run/user/\${USER_UID} uv run arr-mcp > /tmp/arr-mcp-test.log 2>&1 &
  echo \$! > /tmp/arr-mcp-test.pid

  sleep 2
  if kill -0 \$(cat /tmp/arr-mcp-test.pid) 2>/dev/null; then
    echo ''
    echo 'arr-mcp test instance is running.'
    echo '  Dashboard : http://$TEST_HOST:$TEST_PORT/'
    echo '  MCP URL   : http://$TEST_HOST:$TEST_PORT/mcp'
    echo '  API key   : $TEST_API_KEY'
    echo '  Logs      : ssh $TEST_USER@$TEST_HOST tail -f /tmp/arr-mcp-test.log'
    echo ''
    echo 'Swap .mcp.json.test into .mcp.json to point Claude at the test instance.'
    echo 'To stop: bash scripts/test-deploy.sh --stop'
  else
    echo 'ERROR: arr-mcp failed to start. Check logs:'
    cat /tmp/arr-mcp-test.log
    exit 1
  fi
ENDSSH
