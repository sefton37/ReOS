#!/usr/bin/env bash
# reos-shell-integration.sh — ReOS shell integration for bash/zsh
#
# Sources this file in your shell rc to enable natural-language command
# interception. When a command looks like natural language rather than a
# shell command, ReOS proposes an equivalent shell command for approval.
#
# Usage: source /path/to/reos-shell-integration.sh

# ─────────────────────────────────────────────────────────────────────────────
# _reos_is_natural_language <input>
#
# Returns 0 (true) if the input looks like natural language, 1 (false) if it
# looks like a shell command or single unrecognised token.
#
# Heuristics:
#   - Two or more words containing at least one common English word → NL
#   - Known shell command as first word → not NL
#   - Single word that is not a known NL trigger word → not NL
# ─────────────────────────────────────────────────────────────────────────────
_reos_is_natural_language() {
    local input="$1"

    # Empty input is not natural language
    [[ -z "$input" ]] && return 1

    # Known shell commands as first token → not natural language
    local first_word
    first_word="${input%% *}"
    local shell_commands=(
        ls cd pwd cat less more head tail grep find sed awk
        cp mv rm mkdir rmdir touch ln chmod chown chgrp
        ps top htop kill killall pkill pgrep
        apt apt-get dnf pacman yum zypper snap flatpak
        systemctl service journalctl
        git docker kubectl helm
        ssh scp rsync curl wget
        tar gzip gunzip zip unzip
        python python3 pip pip3 node npm
        bash sh zsh fish
        sudo su
        echo printf read
        df du free uname hostname uptime
        netstat ss ip ifconfig ping traceroute nmap
        which whereis type hash
        env export unset
        man info help
        vim vi nano emacs
        screen tmux
        source .
    )

    for cmd in "${shell_commands[@]}"; do
        if [[ "$first_word" == "$cmd" ]]; then
            return 1
        fi
    done

    # Count words
    local word_count
    word_count=$(echo "$input" | wc -w)

    # Single unknown word → not natural language
    if [[ "$word_count" -lt 2 ]]; then
        return 1
    fi

    # Multi-word input: check for common English indicator words
    local nl_indicators=(
        install uninstall remove update upgrade search
        show list find display check
        what which how when where who why
        start stop restart enable disable
        is are was were has have
        the a an this that these those
        my my what's how's
        all running using
        disk space memory cpu
        file files directory
    )

    local lower_input
    lower_input=$(echo "$input" | tr '[:upper:]' '[:lower:]')

    for word in "${nl_indicators[@]}"; do
        if [[ "$lower_input" == *"$word"* ]]; then
            return 0
        fi
    done

    # Multi-word input with no known shell command and no indicator: treat as NL
    # (conservative — multi-word inputs are usually NL requests)
    if [[ "$word_count" -ge 3 ]]; then
        return 0
    fi

    # Two words, no indicators, no known command → not NL
    return 1
}

# ─────────────────────────────────────────────────────────────────────────────
# _reos_preexec <command>
#
# Hook called before command execution (compatible with bash-preexec and zsh).
# If the command is natural language, intercept it and call reos-propose.
# ─────────────────────────────────────────────────────────────────────────────
_reos_preexec() {
    local cmd="$1"

    # Only intercept if reos binary is available
    if ! command -v reos &>/dev/null; then
        return 0
    fi

    if _reos_is_natural_language "$cmd"; then
        # Propose command via ReOS (non-blocking; user sees proposal and approves)
        reos propose "$cmd"
    fi
}

# ─────────────────────────────────────────────────────────────────────────────
# Shell hook registration
# ─────────────────────────────────────────────────────────────────────────────

# zsh: use preexec hook
if [[ -n "$ZSH_VERSION" ]]; then
    autoload -Uz add-zsh-hook
    add-zsh-hook preexec _reos_preexec
fi

# bash: use bash-preexec if available, otherwise skip silent integration
if [[ -n "$BASH_VERSION" ]]; then
    if declare -f __bp_install &>/dev/null; then
        # bash-preexec is loaded
        preexec_functions+=(_reos_preexec)
    fi
    # Without bash-preexec we cannot intercept non-destructively in bash.
    # Users can call `reos propose "<query>"` directly.
fi
