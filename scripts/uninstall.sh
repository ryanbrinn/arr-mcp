#!/usr/bin/env bash
# arr-mcp uninstaller
# Reverses everything install.sh put in place.
# Run as the same service account used during install (e.g. media), not as root.
#
# Usage:
#   bash scripts/uninstall.sh

set -euo pipefail

# ── Colours ──────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BOLD='\033[1m'; RESET='\033[0m'

info()   { echo -e "  ${GREEN}✓${RESET} $*"; }
warn()   { echo -e "  ${YELLOW}!${RESET} $*"; }
header() { echo -e "\n${BOLD}$*${RESET}"; }

# ── Stop and disable arr-mcp quadlet ─────────────────────────────────────────
remove_quadlet() {
    header "Removing arr-mcp container"

    local quadlet_file="${XDG_CONFIG_HOME:-$HOME/.config}/containers/systemd/arr-mcp.container"

    if systemctl --user is-active arr-mcp &>/dev/null; then
        systemctl --user stop arr-mcp
        info "Stopped arr-mcp"
    else
        warn "arr-mcp was not running"
    fi

    if systemctl --user is-enabled arr-mcp &>/dev/null 2>&1; then
        systemctl --user disable arr-mcp 2>/dev/null || true
        info "Disabled arr-mcp"
    fi

    if [[ -f "$quadlet_file" ]]; then
        rm -f "$quadlet_file"
        info "Removed $quadlet_file"
    else
        warn "Quadlet file not found: $quadlet_file"
    fi

    systemctl --user daemon-reload
    info "systemd reloaded"
}

# ── Stop and disable arr-agent service ───────────────────────────────────────
remove_agent_service() {
    header "Removing arr-agent service"

    local unit_file="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/arr-agent.service"

    if systemctl --user is-active arr-agent &>/dev/null; then
        systemctl --user stop arr-agent
        info "Stopped arr-agent"
    else
        warn "arr-agent was not running"
    fi

    if systemctl --user is-enabled arr-agent &>/dev/null 2>&1; then
        systemctl --user disable arr-agent 2>/dev/null || true
        info "Disabled arr-agent"
    fi

    if [[ -f "$unit_file" ]]; then
        rm -f "$unit_file"
        info "Removed $unit_file"
    else
        warn "Service unit not found: $unit_file"
    fi

    systemctl --user daemon-reload
    info "systemd reloaded"
}

# ── Uninstall arr-mcp-server uv tool ─────────────────────────────────────────
remove_uv_tool() {
    header "Uninstalling arr-mcp-server"

    if uv tool list 2>/dev/null | grep -q arr-mcp; then
        uv tool uninstall arr-mcp-server
        info "Uninstalled arr-mcp-server"
    else
        warn "arr-mcp-server not found in uv tools"
    fi
}

# ── Summary ───────────────────────────────────────────────────────────────────
print_summary() {
    echo ""
    echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
    echo -e "${GREEN}${BOLD}  arr-mcp uninstalled${RESET}"
    echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
    echo ""
    echo "  The following were NOT removed (your data):"
    echo "    - Media directory (ARR_MCP_MEDIA_DIR)"
    echo "    - Stacks directory (ARR_MCP_STACKS_DIR)"
    echo "    - Container images (podman rmi ghcr.io/ryanbrinn/arr-mcp)"
    echo ""
    echo "  To reinstall:"
    echo "    bash scripts/install.sh"
    echo ""
}

# ── Main ──────────────────────────────────────────────────────────────────────
main() {
    echo ""
    echo -e "${BOLD}  arr-mcp uninstaller${RESET}"
    echo -e "  ──────────────────────────────────────────"

    remove_quadlet
    remove_agent_service
    remove_uv_tool
    print_summary
}

main "$@"
