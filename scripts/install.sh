#!/usr/bin/env bash
# arr-mcp installer
# Installs arr-agent on the host and sets up the arr-mcp container.
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

    if [[ $missing -ne 0 ]]; then
        echo ""
        error "One or more prerequisites are missing. Fix the above and re-run."
        exit 1
    fi
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

    prompt "Media directory [/media-server]:"
    read -r MEDIA_DIR
    MEDIA_DIR="${MEDIA_DIR:-/media-server}"
    info "Media directory: $MEDIA_DIR"

    prompt "Stacks directory [/opt/stacks]:"
    read -r STACKS_DIR
    STACKS_DIR="${STACKS_DIR:-/opt/stacks}"
    info "Stacks directory: $STACKS_DIR"

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
    PODMAN_SOCK="/run/user/${USER_UID}/podman/podman.sock"
    HELPER_SOCK_HOST="/run/user/${USER_UID}/arr-agent/arr-agent.sock"
    HELPER_SOCK_CONTAINER="/run/arr-agent/arr-agent.sock"
}

# ── Install arr-agent ─────────────────────────────────────────────────────────
install_helper() {
    header "Installing arr-agent"

    info "Running: uv tool install arr-mcp-server"
    uv tool install arr-mcp-server --quiet

    # `uv tool dir` (no args) returns the parent tools directory; each tool
    # gets a subdirectory named after the package containing its virtualenv.
    local agent_bin
    local tools_dir
    tools_dir=$(uv tool dir 2>/dev/null || true)
    if [[ -x "${tools_dir}/arr-mcp/bin/arr-agent" ]]; then
        agent_bin="${tools_dir}/arr-mcp/bin/arr-agent"
    else
        # Fall back to PATH search (covers UV_TOOL_BIN_DIR symlinks)
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

    # systemd user unit
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

# ── Write arr-mcp quadlet ─────────────────────────────────────────────────────
write_quadlet() {
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
Environment=ARR_MCP_STACKS_DIR=${STACKS_DIR}
Environment=ARR_MCP_MEDIA_DIR=${MEDIA_DIR}
Environment=ARR_MCP_PORT=${PORT}
Environment=ARR_MCP_SOCKET_PATH=unix://${PODMAN_SOCK}
Environment=ARR_MCP_HELPER_SOCKET=${HELPER_SOCK_CONTAINER}
Environment=ARR_MCP_DASHBOARD_PUBLIC=${DASHBOARD_PUBLIC}
Volume=${PODMAN_SOCK}:${PODMAN_SOCK}:z
Volume=${STACKS_DIR}:${STACKS_DIR}:z
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
        warn "  journalctl --user -u arr-mcp -n 30"
        warn "  journalctl --user -u arr-agent -n 20"
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
    echo "  journalctl --user -u arr-mcp -f      # arr-mcp logs"
    echo "  journalctl --user -u arr-agent -f     # arr-agent logs"
    echo "  systemctl --user status arr-mcp       # service status"
    echo ""
}

# ── Main ──────────────────────────────────────────────────────────────────────
main() {
    echo ""
    echo -e "${BOLD}  arr-mcp installer${RESET}"
    echo -e "  ──────────────────────────────────────────"

    check_prereqs
    collect_config
    install_helper
    write_quadlet
    verify
    print_summary
}

main "$@"
