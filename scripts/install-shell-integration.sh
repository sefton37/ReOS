#!/usr/bin/env bash
# ReOS Shell Integration Installer
#
# This script adds ReOS shell integration to your shell configuration.
# It enables natural language processing directly in your terminal.
#
# Usage:
#   ./scripts/install-shell-integration.sh
#   ./scripts/install-shell-integration.sh --uninstall
#
set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Find script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
INTEGRATION_SCRIPT="$SCRIPT_DIR/reos-shell-integration.sh"

# Detect shell configuration file
detect_shell_rc() {
    local shell_name
    shell_name="$(basename "$SHELL")"

    case "$shell_name" in
        bash)
            if [[ -f "$HOME/.bashrc" ]]; then
                echo "$HOME/.bashrc"
            elif [[ -f "$HOME/.bash_profile" ]]; then
                echo "$HOME/.bash_profile"
            else
                echo "$HOME/.bashrc"
            fi
            ;;
        zsh)
            echo "$HOME/.zshrc"
            ;;
        *)
            echo ""
            ;;
    esac
}

# Check if already installed
is_installed() {
    local rc_file="$1"
    grep -q "reos-shell-integration.sh" "$rc_file" 2>/dev/null
}

# Install the integration
install_integration() {
    local rc_file
    rc_file="$(detect_shell_rc)"

    if [[ -z "$rc_file" ]]; then
        echo -e "${RED}Error:${NC} Unsupported shell. ReOS shell integration supports bash and zsh." >&2
        echo "You can manually add this to your shell config:" >&2
        echo "  source \"$INTEGRATION_SCRIPT\"" >&2
        exit 1
    fi

    if is_installed "$rc_file"; then
        echo -e "${YELLOW}Note:${NC} ReOS shell integration is already installed in $rc_file"
        echo "To reinstall, run: $0 --uninstall && $0"
        exit 0
    fi

    # Check that integration script exists
    if [[ ! -f "$INTEGRATION_SCRIPT" ]]; then
        echo -e "${RED}Error:${NC} Integration script not found at $INTEGRATION_SCRIPT" >&2
        exit 1
    fi

    # Check that Python venv exists
    if [[ ! -x "$REPO_ROOT/.venv/bin/python" ]]; then
        echo -e "${RED}Error:${NC} Python venv not found." >&2
        echo "Create it with: python3.12 -m venv .venv && .venv/bin/python -m pip install -e ." >&2
        exit 1
    fi

    echo -e "${CYAN}ReOS Shell Integration Installer${NC}"
    echo ""
    echo "This will add ReOS shell integration to: $rc_file"
    echo ""
    echo "Features:"
    echo "  - Type natural language directly in terminal"
    echo "  - ReOS intercepts 'command not found' errors"
    echo "  - Use 'reos \"query\"' for direct queries"
    echo "  - Use 'ask \"query\"' as a shortcut"
    echo ""
    echo -n "Proceed? [Y/n] "

    local response
    read -r response
    case "$response" in
        n|N|no|NO)
            echo "Cancelled."
            exit 0
            ;;
    esac

    # Add to shell config
    cat >> "$rc_file" << EOF

# ReOS Shell Integration (added by install-shell-integration.sh)
if [[ -f "$INTEGRATION_SCRIPT" ]]; then
    source "$INTEGRATION_SCRIPT"
fi
EOF

    echo ""
    echo -e "${GREEN}Success!${NC} ReOS shell integration installed."
    echo ""
    echo "To activate now, run:"
    echo "  source $rc_file"
    echo ""
    echo "Or open a new terminal."
    echo ""
    echo "Configuration options (add to $rc_file before the source line):"
    echo "  export REOS_SHELL_AUTO=1      # Skip confirmation prompts"
    echo "  export REOS_SHELL_DISABLED=1  # Temporarily disable"
}

# Uninstall the integration
uninstall_integration() {
    local rc_file
    rc_file="$(detect_shell_rc)"

    if [[ -z "$rc_file" ]]; then
        echo -e "${RED}Error:${NC} Unsupported shell." >&2
        exit 1
    fi

    if ! is_installed "$rc_file"; then
        echo -e "${YELLOW}Note:${NC} ReOS shell integration is not installed in $rc_file"
        exit 0
    fi

    echo -e "${CYAN}Uninstalling ReOS Shell Integration${NC}"
    echo ""
    echo "This will remove ReOS shell integration from: $rc_file"
    echo -n "Proceed? [Y/n] "

    local response
    read -r response
    case "$response" in
        n|N|no|NO)
            echo "Cancelled."
            exit 0
            ;;
    esac

    # Create backup
    cp "$rc_file" "$rc_file.bak"

    # Remove the integration block
    sed -i '/# ReOS Shell Integration/,/^fi$/d' "$rc_file"

    echo ""
    echo -e "${GREEN}Success!${NC} ReOS shell integration removed."
    echo "Backup saved to: $rc_file.bak"
    echo ""
    echo "To deactivate in current session, run:"
    echo "  unset -f command_not_found_handle reos _reos_find_root"
    echo "  unalias ask 2>/dev/null"
}

# Show usage
show_usage() {
    echo "ReOS Shell Integration Installer"
    echo ""
    echo "Usage:"
    echo "  $0            Install shell integration"
    echo "  $0 --uninstall  Remove shell integration"
    echo "  $0 --help       Show this help"
}

# Main
case "${1:-}" in
    --uninstall|-u)
        uninstall_integration
        ;;
    --help|-h)
        show_usage
        ;;
    "")
        install_integration
        ;;
    *)
        echo -e "${RED}Error:${NC} Unknown option: $1" >&2
        show_usage
        exit 1
        ;;
esac
