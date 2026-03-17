# ReOS Semantic Layer Build Instructions
## For Claude Code — run after fetch-linux-corpus.sh completes

## What You're Building

A structured semantic registry that maps **human intent → command patterns → flags → safety → undo paths** for Linux system administration. This is NOT a chatbot knowledge base — it's a deterministic lookup layer that a small local LLM (Ollama/llama3.2) can use to reliably resolve natural language requests into safe, executable commands.

Think of it like the SQL Views layer in Project Quarry — collapsing the output space so the small model doesn't need to be omniscient.

## Source Corpus Location

All source material is in `~/reos-corpus/`:

```
~/reos-corpus/
├── tldr/pages/linux/      # PRIMARY: intent-to-command patterns (markdown)
├── tldr/pages/common/     # PRIMARY: cross-platform commands
├── cheatsheets/           # SECONDARY: task-oriented real-world patterns
├── man-pages/man1/        # REFERENCE: comprehensive command docs
├── man-pages/man5/        # REFERENCE: config file formats
├── man-pages/man7/        # REFERENCE: concept overviews
├── man-pages/man8/        # REFERENCE: admin commands
├── arch-wiki/en/          # CONTEXT: how subsystems work together
├── gnu-docs/              # REFERENCE: coreutils, bash, grep, sed, awk, find
└── local-man-pages/       # REFERENCE: this system's installed commands
```

### How to use each source:

1. **tldr-pages** → Extract the intent descriptions and example commands. These ARE the intent mappings.
2. **cheatsheets** → Supplement tldr with additional real-world patterns and flag combinations.
3. **man-pages** → Use for comprehensive flag documentation, but don't try to capture every flag. Focus on the top 5-10 most common flags per command.
4. **arch-wiki** → Use for understanding how subsystems relate (e.g., systemd, networking stack, audio, storage). These inform the DOMAIN groupings.
5. **gnu-docs** → Authoritative reference for coreutils behavior and edge cases.
6. **local-man-pages** → Capture any distro-specific commands not in the generic sources.

## Output Schema

Generate a directory of YAML files organized by domain. Each file covers one domain (service-management, file-operations, networking, etc.). Each command entry follows this structure:

```yaml
# reos-semantic-layer/domains/service-management.yaml

domain: service-management
description: "Managing systemd services, units, timers, and targets"
related_domains:
  - process-management
  - logging

commands:
  - name: systemctl
    description: "Control the systemd system and service manager"
    common_intents:
      - intent: "start a service"
        pattern: "systemctl start {service}"
        example: "systemctl start nginx"
      - intent: "stop a service"
        pattern: "systemctl stop {service}"
        example: "systemctl stop nginx"
      - intent: "restart a service"
        pattern: "systemctl restart {service}"
        example: "systemctl restart nginx"
      - intent: "check if a service is running"
        pattern: "systemctl is-active {service}"
        example: "systemctl is-active sshd"
      - intent: "enable a service at boot"
        pattern: "systemctl enable {service}"
        example: "systemctl enable docker"
      - intent: "see why a service failed"
        pattern: "systemctl status {service}"
        followup: "journalctl -u {service} -e --no-pager"
      - intent: "list all failed services"
        pattern: "systemctl --failed"
      - intent: "list all running services"
        pattern: "systemctl list-units --type=service --state=running"
    key_flags:
      - flag: "--now"
        meaning: "Also start/stop the service immediately when enabling/disabling"
      - flag: "--user"
        meaning: "Operate on user services instead of system services"
    safety:
      level: "moderate"  # safe | moderate | dangerous | blocked
      requires_sudo: true
      confirmation_required_for:
        - "enable"
        - "disable"
        - "mask"
      blocked_patterns: []
    undo:
      "start": "systemctl stop {service}"
      "stop": "systemctl start {service}"
      "enable": "systemctl disable {service}"
      "disable": "systemctl enable {service}"
    distro_notes:
      alpine: "Uses OpenRC: rc-service {service} start"
      void: "Uses runit: sv start {service}"
    related_commands:
      - "journalctl"
      - "systemd-analyze"

  - name: journalctl
    description: "Query the systemd journal (logs)"
    common_intents:
      - intent: "show logs for a service"
        pattern: "journalctl -u {service}"
      - intent: "show recent logs"
        pattern: "journalctl -e --no-pager -n {lines:50}"
      - intent: "follow logs in real time"
        pattern: "journalctl -f -u {service}"
      - intent: "show logs since last boot"
        pattern: "journalctl -b"
      - intent: "show kernel messages"
        pattern: "journalctl -k"
      - intent: "show logs from a time range"
        pattern: 'journalctl --since "{start}" --until "{end}"'
        example: 'journalctl --since "2024-01-01" --until "2024-01-02"'
    key_flags:
      - flag: "-u {unit}"
        meaning: "Filter by systemd unit"
      - flag: "-f"
        meaning: "Follow new entries (like tail -f)"
      - flag: "-e"
        meaning: "Jump to end of log"
      - flag: "-n {N}"
        meaning: "Show last N entries"
      - flag: "--no-pager"
        meaning: "Don't pipe through less"
    safety:
      level: "safe"
      requires_sudo: false  # for most queries
    undo: null  # read-only command
    related_commands:
      - "systemctl"
      - "dmesg"
```

## Domains to Generate

Based on the Arch Wiki subsystem organization and the ReOS tool categories, generate these domain files:

1. **system-info.yaml** — CPU, memory, disk, uptime, kernel info, hardware
2. **process-management.yaml** — ps, top, htop, kill, nice, renice, nohup
3. **service-management.yaml** — systemctl, journalctl, systemd-analyze
4. **package-management.yaml** — apt, dnf, pacman, zypper, snap, flatpak, winget
5. **file-operations.yaml** — ls, cp, mv, rm, find, locate, chmod, chown, ln, stat, file, tree
6. **text-processing.yaml** — grep, sed, awk, cut, sort, uniq, wc, tr, head, tail, diff, tee
7. **networking.yaml** — ip, ss, curl, wget, ping, dig, nslookup, traceroute, nmap, iptables/nftables
8. **storage.yaml** — df, du, lsblk, mount, umount, fdisk, mkfs, lvm commands
9. **user-management.yaml** — useradd, usermod, userdel, passwd, groups, su, sudo, visudo
10. **shell-operations.yaml** — bash builtins, pipes, redirection, job control, history, aliases
11. **docker.yaml** — docker/podman commands for container management
12. **ssh-remote.yaml** — ssh, scp, rsync, ssh-keygen, ssh-agent
13. **compression.yaml** — tar, gzip, bzip2, xz, zip, unzip, zstd
14. **scheduling.yaml** — cron, crontab, at, systemd timers
15. **logging.yaml** — journalctl, dmesg, /var/log, logrotate, tail -f patterns
16. **permissions-security.yaml** — chmod, chown, ACLs, SELinux/AppArmor basics, firewall

## Build Process

1. Start by reading `tldr/pages/linux/` and `tldr/pages/common/` to build the initial intent mappings for each command.
2. Cross-reference with `cheatsheets/` for additional patterns and real-world flag combinations.
3. Pull key flags and detailed descriptions from `man-pages/` — but keep it to the top flags, not exhaustive.
4. Use `arch-wiki/en/` to inform domain groupings and the `related_commands` and `related_domains` fields. The wiki shows how commands connect into subsystems.
5. Mark safety levels based on the command's potential for system damage:
   - `safe` = read-only, no system changes
   - `moderate` = changes system state but reversible
   - `dangerous` = potentially destructive, confirmation required
   - `blocked` = never execute (rm -rf /, mkfs on mounted device, etc.)
6. Generate undo paths wherever possible.
7. Add distro_notes only where commands genuinely differ (Alpine/OpenRC, Void/runit).

## Output Location

Write all files to `~/ReOS/semantic-layer/domains/`

Also generate:
- `~/ReOS/semantic-layer/README.md` — overview and schema docs
- `~/ReOS/semantic-layer/blocked-patterns.yaml` — master list of blocked/dangerous command patterns
- `~/ReOS/semantic-layer/intent-index.yaml` — flat index mapping every intent string to its command+domain for fast lookup
