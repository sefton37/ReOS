#!/usr/bin/env bash
# ReOS Shell Integration
#
# This script makes natural language the PRIMARY interface to your terminal.
# Just type what you want in plain English - ReOS will figure out if it's
# a command or a natural language request.
#
# Installation:
#   Add to your ~/.bashrc or ~/.zshrc:
#     source /path/to/reos/scripts/reos-shell-integration.sh
#
# Usage:
#   Just type naturally:
#     $ if we have any nextcloud containers running, remove them
#     $ what's using port 8080
#     $ show me disk usage
#
#   Real commands still work:
#     $ ls -la
#     $ git status
#     $ docker ps
#
# Configuration:
#   REOS_SHELL_DISABLED=1   - Disable ReOS shell integration temporarily
#   REOS_DEBUG=1            - Show classification decisions

# Find the ReOS installation directory
_reos_find_root() {
    local script_path
    script_path="${BASH_SOURCE[0]:-$0}"

    # Handle symlinks
    if command -v readlink >/dev/null 2>&1; then
        script_path="$(readlink -f "$script_path" 2>/dev/null || echo "$script_path")"
    fi

    # Go up from scripts/ to repo root
    local dir
    dir="$(cd "$(dirname "$script_path")/.." 2>/dev/null && pwd)"

    if [[ -f "$dir/reos" ]]; then
        echo "$dir"
        return 0
    fi

    # Fallback: check if reos is in PATH
    if command -v reos >/dev/null 2>&1; then
        echo "$(dirname "$(command -v reos)")"
        return 0
    fi

    return 1
}

# Cache the ReOS root directory
_REOS_ROOT="$(_reos_find_root)"
_REOS_PYTHON="${_REOS_ROOT}/.venv/bin/python"

# Check if first word is a valid command
_reos_is_command() {
    local first_word="$1"

    # Empty - not a command
    [[ -z "$first_word" ]] && return 1

    # Check if it's a bash builtin
    if builtin type -t "$first_word" &>/dev/null; then
        local cmd_type
        cmd_type="$(builtin type -t "$first_word")"
        case "$cmd_type" in
            builtin|alias|function|file|keyword)
                return 0
                ;;
        esac
    fi

    # Check if it exists in PATH
    command -v "$first_word" &>/dev/null && return 0

    # Check if it's a path to an executable
    [[ -x "$first_word" ]] && return 0

    return 1
}

# Classify input: command or natural language?
_reos_classify_input() {
    local input="$1"

    # Empty input - let bash handle it
    [[ -z "${input// /}" ]] && echo "empty" && return

    # Get first word
    local first_word="${input%% *}"

    # If first word is a valid command, it's probably a command
    # Exception: shell keywords that could be natural language
    case "$first_word" in
        # These are bash keywords but often start natural language
        if|for|while|until|case|select)
            # Check if it looks like real bash syntax
            case "$input" in
                *" then "*|*"; then"*|*" do "*|*"; do"*|*" in "*|*";"*)
                    echo "command"
                    return
                    ;;
            esac
            # Looks like natural language starting with a keyword
            echo "natural"
            return
            ;;
    esac

    # Check if first word is a command
    if _reos_is_command "$first_word"; then
        echo "command"
        return
    fi

    # Not a recognized command - likely natural language
    echo "natural"
}

# Handle Enter key press - intercept before bash parses
_reos_handle_enter() {
    local input="$READLINE_LINE"

    # Disabled check
    if [[ -n "${REOS_SHELL_DISABLED:-}" ]]; then
        # Just accept the line normally
        builtin bind '"\C-m": accept-line'
        return
    fi

    # Classify the input
    local classification
    classification="$(_reos_classify_input "$input")"

    if [[ -n "${REOS_DEBUG:-}" ]]; then
        echo >&2
        printf '\033[90m[ReOS Debug] Input: "%s" -> %s\033[0m\n' "$input" "$classification" >&2
    fi

    case "$classification" in
        empty|command)
            # Let bash handle it - execute the line
            # We need to actually run the command
            READLINE_LINE=""
            READLINE_POINT=0
            echo  # Newline after input
            eval "$input"
            ;;
        natural)
            # Process with ReOS
            READLINE_LINE=""
            READLINE_POINT=0
            echo  # Newline after input

            if [[ -x "$_REOS_PYTHON" ]]; then
                "$_REOS_PYTHON" -m reos.shell_cli "$input"
            else
                echo "ReOS: Python not found at $_REOS_PYTHON" >&2
            fi
            ;;
    esac
}

# Fallback: command_not_found_handle for cases that slip through
command_not_found_handle() {
    local cmd="$1"
    shift
    local full_input="$cmd $*"

    # Disabled check
    if [[ -n "${REOS_SHELL_DISABLED:-}" ]]; then
        printf 'bash: %s: command not found\n' "$cmd" >&2
        return 127
    fi

    # Skip if it looks like a typo of a real command (single word, short)
    if [[ -z "$*" && ${#cmd} -le 3 ]]; then
        printf 'bash: %s: command not found\n' "$cmd" >&2
        return 127
    fi

    # Skip if it starts with common path prefixes (likely a real command attempt)
    case "$cmd" in
        /*|./*|../*|\~/*|./*)
            printf 'bash: %s: command not found\n' "$cmd" >&2
            return 127
            ;;
    esac

    # Find ReOS and process
    if [[ -x "$_REOS_PYTHON" ]]; then
        printf '\033[36m🐧 ReOS:\033[0m Processing: %s\n' "$full_input" >&2
        "$_REOS_PYTHON" -m reos.shell_cli "$full_input"
        return $?
    fi

    printf 'bash: %s: command not found\n' "$cmd" >&2
    return 127
}

# Direct invocation function: reos "natural language query"
reos() {
    if [[ -z "$_REOS_ROOT" ]]; then
        echo "ReOS: Could not find ReOS installation" >&2
        return 1
    fi

    if [[ ! -x "$_REOS_PYTHON" ]]; then
        echo "ReOS: Python venv not found at $_REOS_PYTHON" >&2
        return 1
    fi

    if [[ $# -eq 0 ]]; then
        # No args - launch full GUI/service
        "$_REOS_ROOT/reos" "$@"
    elif [[ "$1" == "--"* ]]; then
        # Has flags - pass to main launcher
        "$_REOS_ROOT/reos" "$@"
    else
        # Natural language prompt
        "$_REOS_PYTHON" -m reos.shell_cli "$@"
    fi
}

# Escape hatch: prefix with ! to force command execution
_reos_force_command() {
    local input="$READLINE_LINE"
    if [[ "$input" == "!"* ]]; then
        # Remove the ! prefix and execute as command
        READLINE_LINE="${input#!}"
        READLINE_POINT=$((READLINE_POINT - 1))
    fi
}

# Alias for quick access
alias ask='reos'

# Export for subshells
export -f command_not_found_handle
export -f reos
export -f _reos_find_root
export -f _reos_is_command
export -f _reos_classify_input
export _REOS_ROOT
export _REOS_PYTHON

# Set up input interception
if [[ -n "${BASH_VERSION:-}" && -t 0 ]]; then
    # Bind Enter key to our handler
    # This intercepts input BEFORE bash parses it
    bind -x '"\C-j": _reos_handle_enter'
    bind -x '"\C-m": _reos_handle_enter'

    echo "🐧 ReOS shell integration active. Just type naturally!" >&2
    echo "   Prefix with ! to force command execution (e.g., !if true; then echo hi; fi)" >&2
fi
