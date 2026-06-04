#!/usr/bin/env bash
# arr-mcp installer
# Sets up arr-mcp and (for Podman) the arr-agent host service.
# Run as the service account (e.g. media), not as root.
#
# Usage:
#   curl -sSL https://raw.githubusercontent.com/ryanbrinn/arr-mcp/main/scripts/install.sh | bash
#   # or locally:
#   bash scripts/install.sh

set -euo pipefail

# ── Colours ──────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BOLD='\033[1m'; RESET='\033[0m'

info()    { echo -e "  ${GREEN}✓${RESET} $*"; }
warn()    { echo -e "  ${YELLOW}!${RESET} $*"; }
error()   { echo -e "  ${RED}✗${RESET} $*" >&2; }
header()  { echo -e "\n${BOLD}$*${RESET}"; }
prompt()  { echo -en "  ${BOLD}$*${RESET} "; }

# ── Prerequisite check ────────────────────────────────────────────────────────
check_prereqs() {
    header "Checking prerequisites"
    local missing=0

    if command -v uv &>/dev/null; then
        info "uv $(uv --version | cut -d' ' -f2)"
    else
        error "uv not found. Install it first: curl -sSL https://astral.sh/uv/install.sh | sh"
        missing=1
    fi

    if [[ "$CONTAINER_RUNTIME" == "podman" ]]; then
        if command -v podman &>/dev/null; then
            info "podman $(podman --version | cut -d' ' -f3)"
        else
            error "podman not found. Install rootless Podman before running this script."
            missing=1
        fi

        if command -v systemctl &>/dev/null && systemctl --user status &>/dev/null 2>&1; then
            info "systemd user session active"
        else
            error "systemd user session not available. Enable linger for this account:"
            error "  sudo loginctl enable-linger $(whoami)"
            missing=1
        fi
    fi

    if [[ "$CONTAINER_RUNTIME" == "docker-compose" || "$CONTAINER_RUNTIME" == "docker" ]]; then
        if command -v docker &>/dev/null; then
            info "docker $(docker --version | cut -d' ' -f3 | tr -d ',')"
        else
            error "docker not found. Install Docker before running this script."
            missing=1
        fi
    fi

    if [[ $missing -ne 0 ]]; then
        echo ""
        error "One or more prerequisites are missing. Fix the above and re-run."
        exit 1
    fi
}

# ── Runtime selection ─────────────────────────────────────────────────────────
select_runtime() {
    header "Container runtime"
    echo ""
    echo "  1) Docker Compose  — stack management + full dashboard (default)"
    echo "  2) Docker Engine   — container management only"
    echo "  3) Podman          — rootless containers via arr-agent"
    echo ""
    prompt "Select [1]:"
    read -r RUNTIME_CHOICE
    RUNTIME_CHOICE="${RUNTIME_CHOICE:-1}"

    case "$RUNTIME_CHOICE" in
        1) CONTAINER_RUNTIME="docker-compose" ;;
        2) CONTAINER_RUNTIME="docker"         ;;
        3) CONTAINER_RUNTIME="podman"         ;;
        *)
            error "Invalid selection: $RUNTIME_CHOICE"
            exit 1
            ;;
    esac
    info "Runtime: $CONTAINER_RUNTIME"
}

# ── Config questions ──────────────────────────────────────────────────────────
collect_config() {
    header "Configuration"
    echo "  Press Enter to accept the default shown in [brackets]."
    echo ""

    # API key — generate a random one if blank
    prompt "API key (leave blank to generate) []:"
    read -rs API_KEY
    echo ""
    if [[ -z "$API_KEY" ]]; then
        API_KEY=$(LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c 32 || true)
        info "Generated API key (save this — it won't be shown again)"
        echo -e "  ${BOLD}${API_KEY}${RESET}"
    else
        info "Using provided API key"
    fi

    prompt "Services directory (arr app configs, logs) [/media-server]:"
    read -r SERVICES_DIR
    SERVICES_DIR="${SERVICES_DIR:-/media-server}"
    info "Services directory: $SERVICES_DIR"

    prompt "Media library directory [/media-server/library]:"
    read -r MEDIA_DIR
    MEDIA_DIR="${MEDIA_DIR:-/media-server/library}"
    info "Media directory: $MEDIA_DIR"

    if [[ "$CONTAINER_RUNTIME" == "docker-compose" ]]; then
        prompt "Compose projects directory []:"
        read -r COMPOSE_DIR
        if [[ -z "$COMPOSE_DIR" ]]; then
            error "Compose directory is required for Docker Compose."
            exit 1
        fi
        info "Compose directory: $COMPOSE_DIR"
    fi

    prompt "Port [8081]:"
    read -r PORT
    PORT="${PORT:-8081}"
    info "Port: $PORT"

    prompt "Make dashboard public (no auth required)? [y/N]:"
    read -r DASHBOARD_PUBLIC_INPUT
    if [[ "${DASHBOARD_PUBLIC_INPUT,,}" == "y" ]]; then
        DASHBOARD_PUBLIC="true"
        info "Dashboard: public (no auth)"
    else
        DASHBOARD_PUBLIC="false"
        info "Dashboard: protected (API key required)"
    fi

    # Derived values
    USER_UID=$(id -u)
    if [[ "$CONTAINER_RUNTIME" == "podman" ]]; then
        PODMAN_SOCK="/run/user/${USER_UID}/podman/podman.sock"
        HELPER_SOCK_HOST="/run/user/${USER_UID}/arr-agent/arr-agent.sock"
        HELPER_SOCK_CONTAINER="/run/arr-agent/arr-agent.sock"
    fi
}

# ── Install arr-agent (Podman only) ──────────────────────────────────────────
install_helper() {
    header "Installing arr-agent"

    info "Running: uv tool install arr-mcp-server"
    uv tool install arr-mcp-server --quiet

    local agent_bin
    local tools_dir
    tools_dir=$(uv tool dir 2>/dev/null || true)
    if [[ -x "${tools_dir}/arr-mcp/bin/arr-agent" ]]; then
        agent_bin="${tools_dir}/arr-mcp/bin/arr-agent"
    else
        agent_bin=$(command -v arr-agent 2>/dev/null || true)
    fi
    if [[ -z "$agent_bin" ]]; then
        error "arr-agent binary not found after install."
        error "Expected it at: ${tools_dir}/arr-mcp/bin/arr-agent"
        error "Installed tools:"
        uv tool list 2>/dev/null >&2 || true
        exit 1
    fi
    info "arr-agent installed at $agent_bin"

    local unit_dir="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
    mkdir -p "$unit_dir"

    cat > "${unit_dir}/arr-agent.service" <<EOF
[Unit]
Description=arr-mcp host-side agent
After=network.target

[Service]
ExecStart=${agent_bin}
Restart=on-failure
RuntimeDirectory=arr-agent
RuntimeDirectoryMode=0700

[Install]
WantedBy=default.target
EOF

    info "Wrote ${unit_dir}/arr-agent.service"

    systemctl --user daemon-reload
    systemctl --user enable --now arr-agent
    info "arr-agent started"
}

# ── Write arr-mcp quadlet (Podman) ────────────────────────────────────────────
write_podman_quadlet() {
    header "Writing arr-mcp quadlet"

    local quadlet_dir="${XDG_CONFIG_HOME:-$HOME/.config}/containers/systemd"
    mkdir -p "$quadlet_dir"

    cat > "${quadlet_dir}/arr-mcp.container" <<EOF
[Unit]
Description=arr-mcp MCP server
After=network-online.target arr-agent.service
Wants=network-online.target

[Container]
Image=ghcr.io/ryanbrinn/arr-mcp:latest
ContainerName=arr-mcp
Environment=ARR_MCP_API_KEY=${API_KEY}
Environment=ARR_MCP_CONTAINER_RUNTIME=podman
Environment=ARR_MCP_SERVICES_DIR=${SERVICES_DIR}
Environment=ARR_MCP_MEDIA_DIR=${MEDIA_DIR}
Environment=ARR_MCP_PORT=${PORT}
Environment=ARR_MCP_SOCKET_PATH=unix://${PODMAN_SOCK}
Environment=ARR_MCP_HELPER_SOCKET=${HELPER_SOCK_CONTAINER}
Environment=ARR_MCP_DASHBOARD_PUBLIC=${DASHBOARD_PUBLIC}
Volume=${PODMAN_SOCK}:${PODMAN_SOCK}:z
Volume=${SERVICES_DIR}:${SERVICES_DIR}:z
Volume=${MEDIA_DIR}:${MEDIA_DIR}:z
Volume=${HELPER_SOCK_HOST}:${HELPER_SOCK_CONTAINER}:z
PublishPort=${PORT}:${PORT}

[Service]
Restart=on-failure

[Install]
WantedBy=default.target
EOF

    info "Wrote ${quadlet_dir}/arr-mcp.container"

    systemctl --user daemon-reload
    systemctl --user start arr-mcp
    info "arr-mcp started"
}

# ── Write docker-compose.yaml (Docker Compose / Docker Engine) ────────────────
write_compose_stack() {
    header "Writing arr-mcp compose file"

    local compose_file="${COMPOSE_DIR:-$HOME}/arr-mcp/docker-compose.yaml"
    mkdir -p "$(dirname "$compose_file")"

    local runtime_env=""
    if [[ "$CONTAINER_RUNTIME" == "docker-compose" ]]; then
        runtime_env="      - ARR_MCP_CONTAINER_RUNTIME=docker-compose
      - ARR_MCP_COMPOSE_DIR=${COMPOSE_DIR}"
    else
        runtime_env="      - ARR_MCP_CONTAINER_RUNTIME=docker"
    fi

    cat > "$compose_file" <<EOF
services:
  arr-mcp:
    image: ghcr.io/ryanbrinn/arr-mcp:latest
    container_name: arr-mcp
    restart: unless-stopped
    ports:
      - "${PORT}:${PORT}"
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - ${SERVICES_DIR}:${SERVICES_DIR}:ro
      - ${MEDIA_DIR}:${MEDIA_DIR}:ro
$(if [[ "$CONTAINER_RUNTIME" == "docker-compose" ]]; then echo "      - ${COMPOSE_DIR}:${COMPOSE_DIR}:rw"; fi)
    environment:
      - ARR_MCP_API_KEY=${API_KEY}
${runtime_env}
      - ARR_MCP_SERVICES_DIR=${SERVICES_DIR}
      - ARR_MCP_MEDIA_DIR=${MEDIA_DIR}
      - ARR_MCP_PORT=${PORT}
      - ARR_MCP_DASHBOARD_PUBLIC=${DASHBOARD_PUBLIC}
EOF

    info "Wrote $compose_file"
    docker compose -f "$compose_file" up -d
    info "arr-mcp started"
}

# ── Health check ──────────────────────────────────────────────────────────────
verify() {
    header "Verifying"

    local retries=8
    local ok=0
    for i in $(seq 1 $retries); do
        if curl -sf "http://localhost:${PORT}/health" &>/dev/null; then
            ok=1
            break
        fi
        sleep 2
    done

    if [[ $ok -eq 1 ]]; then
        info "Health check passed"
    else
        warn "Health check failed after ${retries} attempts — check logs:"
        if [[ "$CONTAINER_RUNTIME" == "podman" ]]; then
            warn "  journalctl --user -u arr-mcp -n 30"
            warn "  journalctl --user -u arr-agent -n 20"
        else
            warn "  docker logs arr-mcp"
        fi
    fi
}

# ── Summary ───────────────────────────────────────────────────────────────────
print_summary() {
    local host_ip
    host_ip=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "your-server-ip")

    echo ""
    echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
    echo -e "${GREEN}${BOLD}  arr-mcp is running!${RESET}"
    echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
    echo ""
    echo -e "  ${BOLD}Runtime${RESET}    $CONTAINER_RUNTIME"
    echo ""
    echo -e "  ${BOLD}Dashboard${RESET}"

    if [[ "$DASHBOARD_PUBLIC" == "true" ]]; then
        echo "  http://${host_ip}:${PORT}/"
    else
        echo "  http://${host_ip}:${PORT}/?key=${API_KEY}"
    fi

    echo ""
    echo -e "  ${BOLD}MCP endpoint${RESET}"
    echo "  http://${host_ip}:${PORT}/mcp"
    echo "  Authorization: Bearer ${API_KEY}"
    echo ""
    echo -e "  ${BOLD}Useful commands${RESET}"
    if [[ "$CONTAINER_RUNTIME" == "podman" ]]; then
        echo "  journalctl --user -u arr-mcp -f      # arr-mcp logs"
        echo "  journalctl --user -u arr-agent -f     # arr-agent logs"
        echo "  systemctl --user status arr-mcp       # service status"
    else
        echo "  docker logs -f arr-mcp               # arr-mcp logs"
        echo "  docker ps                            # container status"
    fi
    echo ""
    echo -e "  ${BOLD}To uninstall${RESET}"
    echo "  curl -sSL https://raw.githubusercontent.com/ryanbrinn/arr-mcp/main/scripts/uninstall.sh | bash"
    echo ""
}

# ── Main ──────────────────────────────────────────────────────────────────────
main() {
    echo ""
    echo -e "${BOLD}  arr-mcp installer${RESET}"
    echo -e "  ──────────────────────────────────────────"

    select_runtime
    check_prereqs
    collect_config

    case "$CONTAINER_RUNTIME" in
        podman)
            install_helper
            write_podman_quadlet
            ;;
        docker-compose|docker)
            write_compose_stack
            ;;
    esac

    verify
    print_summary
}

main "$@"
