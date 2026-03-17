# ReOS Semantic Layer

A structured semantic registry that maps human intent to Linux command patterns, safety metadata, and undo paths. This is not a chatbot knowledge base. It is a deterministic lookup layer that a small local LLM (3–8B parameters, Ollama-hosted) uses to reliably resolve natural language requests into safe, executable commands — without needing to be omniscient about every Linux command and flag.

The semantic layer collapses the output space. The LLM matches intent, retrieves a structured pattern, and fills in parameters. It never generates commands from scratch.

---

## Directory Structure

```
semantic-layer/
├── README.md                  # this file
├── blocked-patterns.yaml      # master list of never-execute patterns
├── intent-index.yaml          # flat intent → command+domain lookup index
└── domains/
    ├── compression.yaml
    ├── docker.yaml
    ├── file-operations.yaml
    ├── logging.yaml
    ├── networking.yaml
    ├── package-management.yaml
    ├── permissions-security.yaml
    ├── process-management.yaml
    ├── scheduling.yaml
    ├── service-management.yaml
    ├── shell-operations.yaml
    ├── ssh-remote.yaml
    ├── storage.yaml
    ├── system-info.yaml
    ├── text-processing.yaml
    └── user-management.yaml
```

---

## Domains

| Domain | Description | Commands | Intents |
|---|---|---|---|
| `system-info` | CPU, memory, disk, uptime, kernel info, hardware, and system identity | 19 | 74 |
| `process-management` | Process listing, monitoring, signaling, priority management, and job control | 20 | 96 |
| `service-management` | Managing systemd services, units, timers, and targets | 8 | 68 |
| `package-management` | Installing, removing, updating, and querying system and language-specific packages | 12 | 95 |
| `file-operations` | File and directory creation, copying, moving, deletion, permissions, and metadata | 16 | 104 |
| `text-processing` | Searching, transforming, filtering, and analyzing text in files and streams | 19 | 79 |
| `networking` | Network configuration, diagnostics, traffic analysis, and firewall management | 20 | 112 |
| `storage` | Disk usage, partitioning, filesystems, mounting, LVM, and block device management | 20 | 73 |
| `user-management` | Creating, modifying, and deleting users and groups; authentication and privilege escalation | 17 | 61 |
| `shell-operations` | Bash builtins, pipes, redirection, job control, history, aliases, and environment variables | 33 | 82 |
| `docker` | Container lifecycle, images, volumes, networks, and Docker Compose orchestration | 23 | 71 |
| `ssh-remote` | Secure shell connections, key management, file transfer, and tunneling | 10 | 54 |
| `compression` | Archiving, compressing, and extracting files and directories | 11 | 53 |
| `scheduling` | Scheduling one-time and recurring tasks with cron, at, and systemd timers | 9 | 36 |
| `logging` | System logs, kernel messages, log rotation, audit trails, and login history | 10 | 57 |
| `permissions-security` | File permissions, ACLs, firewall, SELinux/AppArmor, encryption, and system hardening | 20 | 83 |

**Total: 267 commands, 1,198 mapped intents**

---

## YAML Schema

Each domain file has a top-level header and a list of command entries.

### Top-level fields

```yaml
domain: <string>            # Machine-readable domain identifier, matches filename
description: <string>       # One-line summary of what this domain covers
related_domains:            # Domains that overlap or commonly combine with this one
  - <domain-name>
commands:
  - ...
```

### Command entry fields

```yaml
- name: <string>                    # The actual command name (e.g., ls, kill, systemctl)
  description: <string>             # What the command does
  common_intents:
    - intent: <string>              # Canonical description of what the user wants to do
      alternate_phrasings:          # See below
        - <string>
      pattern: <string>             # Command template with {parameter} placeholders
      example: <string>             # Concrete filled-in example
      followup: <string>            # (optional) Suggested next command after this one
  key_flags:
    - flag: <string>                # The flag as it appears on the command line
      meaning: <string>             # Plain English explanation
  safety:
    level: <safe|moderate|dangerous|blocked>
    requires_sudo: <bool>
    confirmation_required_for:      # List of subcommands or operations needing confirmation
      - <string>
    blocked_patterns:               # Patterns that must never be generated (if any)
      - <string>
  undo:                             # How to reverse each operation, or null if read-only
    "<operation>": "<reverse-command>"
  distro_notes:                     # (optional) Where behavior differs across distros
    <distro>: <string>
  related_commands:
    - <string>
```

### The `alternate_phrasings` field

This is the primary bridge between human language and the intent registry. Each `intent` has a canonical form, but real users don't speak canonically. `alternate_phrasings` captures the range of ways someone might express the same need — including:

- **Terse CLI shorthand:** `"ls -la"`, `"ps aux"`, `"ip addr"`
- **Colloquial questions:** `"what's in this folder"`, `"what is eating all my RAM"`
- **Emotional/frustrated phrasing:** `"why does this directory look empty when I know stuff is in there"`, `"something is hogging resources, show me everything"`
- **Partial descriptions:** `"show dotfiles too"`, `"long listing"`, `"sort by RSS"`

The LLM matches user input against both `intent` and `alternate_phrasings`. A wider phrasing set means better recall without sacrificing precision, because the matched result is always a controlled pattern — not free-form generation.

### Complete example entry

```yaml
- name: ps
  description: "Report a snapshot of currently running processes"
  common_intents:
    - intent: "show all running processes"
      alternate_phrasings:
        - "ps aux"
        - "what is running on this machine right now"
        - "my system is sluggish and I want to see every process that is currently active"
        - "something is hogging resources, show me everything"
        - "list all processes"
      pattern: "ps aux"
      example: "ps aux"
      followup: "grep for a specific process name"
    - intent: "search for a process by name"
      alternate_phrasings:
        - "is nginx running"
        - "find pid of {process_name}"
        - "check if {process_name} is up"
      pattern: "ps aux | grep '[{first_letter}]{rest_of_name}'"
      example: "ps aux | grep '[h]ttpd'"
      followup: "kill {pid}"
  key_flags:
    - flag: "a"
      meaning: "Show processes for all users (BSD syntax)"
    - flag: "u"
      meaning: "User-oriented output format"
    - flag: "x"
      meaning: "Include processes not attached to a terminal"
  safety:
    level: "safe"
    requires_sudo: false
    confirmation_required_for: []
    blocked_patterns: []
  undo:
    "listing": "no-op — ps is read-only"
  related_commands:
    - top
    - htop
    - kill
```

---

## Safety Levels

Safety is set at the command level and applies to all intents under that command unless overridden.

| Level | Meaning |
|---|---|
| `safe` | Read-only. Makes no changes to system state. Can be executed without confirmation. |
| `moderate` | Modifies system state but the change is reversible. Requires `sudo` in most cases. The `undo` field will have a reversal command. |
| `dangerous` | Potentially destructive or difficult to reverse. Requires explicit user confirmation before execution. Examples: formatting a partition, deleting files, stopping a critical service. |
| `blocked` | Must never be executed regardless of user instruction. Matches in `blocked-patterns.yaml`. The pipeline refuses these before they reach the shell. |

The `confirmation_required_for` list refines this within a command. For example, `systemctl` is `moderate` overall, but `enable`, `disable`, and `mask` operations are listed under `confirmation_required_for` because their effects persist across reboots.

---

## Lookup Flow

The NL-to-shell pipeline uses the semantic layer as follows:

1. **User input arrives** — e.g., `"my system feels slow, what's running"`
2. **Intent matching** — The LLM (or a vector similarity search over the index) matches the input against `intent` and `alternate_phrasings` across all domain files, or against the flat `intent-index.yaml` for fast lookup.
3. **Pattern retrieval** — The matched entry returns a `pattern`, `safety.level`, `requires_sudo`, and `undo` path.
4. **Parameter extraction** — The LLM fills `{parameter}` placeholders from the user's input (e.g., a directory name, process name, service name).
5. **Safety gate** — If `level` is `dangerous`, the pipeline surfaces a confirmation prompt. If `blocked`, execution is refused.
6. **Execution** — The filled pattern is passed to the shell executor.

The LLM is never asked to generate a command from scratch. It is only asked to match intent and extract parameters. This keeps a 3–8B model reliable on a task it can actually perform.

---

## Companion Files

### `blocked-patterns.yaml`

The master list of command patterns that the pipeline must refuse to execute under any circumstances. These are patterns where the risk of system damage is catastrophic and irreversible — for example, `rm -rf /`, `mkfs` on a mounted device, or `dd` writing to a live root partition. This file is the hard stop; the `blocked` safety level in domain files points back to it.

### `intent-index.yaml`

A flat index mapping every intent string (and its alternate phrasings) to its command name and domain file. This exists for fast lookup at runtime — rather than scanning all 16 domain files, the pipeline queries this index first to identify the command and domain, then loads only the relevant entry for pattern and metadata. The index is derived from the domain files and should be regenerated whenever domain files change.
