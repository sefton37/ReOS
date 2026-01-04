# ReOS - Natural Language Linux

**Make using Linux as easy as having a conversation.**

ReOS is a local-first AI companion that lets you control your entire Linux system through natural language. No more memorizing commands, reading man pages, or searching Stack Overflow. Just describe what you want to do, and ReOS helps you do it safely.

## What Makes ReOS Different

- **Truly Local**: Runs entirely on your machine using Ollama. No cloud, no latency, no privacy concerns.
- **LLM-First Reasoning**: Every request goes through intelligent intent parsing. The LLM understands what you want and plans accordingly.
- **Deep System Understanding**: ReOS knows YOUR system - your containers, services, packages, and processes by name.
- **Transparent Actions**: Every command is previewed before execution. You always see what's happening.
- **Recoverable Mistakes**: Destructive operations show undo commands. It's conversational - you can say "wait, undo that."
- **Safety First**: Dangerous commands are blocked. Risky operations require confirmation.
- **No Paperclips**: Hard-coded circuit breakers prevent runaway AI execution. [Learn more](#circuit-breakers)

## Examples

```bash
# Simple queries - answered directly
$ reos "what containers are running"
You have 4 containers running: nextcloud-app, nextcloud-redis, portainer, n8n

# Actions - planned and previewed
$ reos "stop all nextcloud containers"

This involves system changes. Here's the plan:
  1. Stop nextcloud-app
  2. Stop nextcloud-redis
  3. Stop nextcloud-db

Proceed? [y/n]: y
✓ Stopped nextcloud-app
✓ Stopped nextcloud-redis
✓ Stopped nextcloud-db

# Conversational context
$ reos "now remove them"
# ReOS remembers the context from previous command

Plan:
  1. Remove nextcloud-app
  2. Remove nextcloud-redis
  3. Remove nextcloud-db

Proceed? [y/n]: y
Done! All 3 containers removed.
```

More examples:
```
You: My disk is almost full, help me clean up
ReOS: [Analyzes disk usage, creates cleanup plan, asks approval]

You: Install docker and set it up for my user
ReOS: [Creates multi-step plan: install, start service, add to group]

You: What services are failing?
ReOS: [Lists failed systemd services - query, no approval needed]

You: Restart the failed ones
ReOS: [Creates plan to restart each failed service, asks approval]
```

## Quick Start

```bash
# 1. Install Ollama (if not already installed)
curl -fsSL https://ollama.com/install.sh | sh
ollama pull llama3.2

# 2. Clone and install ReOS
git clone https://github.com/sefton37/ReOS
cd ReOS
pip install -e .

# 3. Run the desktop app
cd apps/reos-tauri
npm install
npm run tauri:dev
```

## Linux Tools

ReOS provides natural language access to:

| Category | Capabilities |
|----------|-------------|
| **System Info** | CPU, memory, disk, network, load averages, uptime |
| **Process Management** | List, sort by CPU/memory, identify resource hogs |
| **Service Management** | Start/stop/restart systemd services, view status |
| **Package Management** | Search, install, remove packages (apt/dnf/pacman/zypper) |
| **File Operations** | List directories, find files, read logs |
| **Docker** | List containers and images, manage containers |
| **Shell Commands** | Execute any safe command with previews for destructive ops |

## Safety Features

ReOS is designed to prevent accidents:

- **Blocked**: Commands like `rm -rf /`, fork bombs, disk formatting
- **Preview Mode**: Destructive commands show what they'll do first
- **Undo Support**: Many operations provide an undo command
- **Warnings**: Risky patterns are flagged before execution

```
You: Delete all the temp files
ReOS: [Preview] This will delete 47 files in /tmp:
      - /tmp/session_12345
      - /tmp/cache_xyz
      - ... (45 more)
      This action cannot be undone. Proceed? [y/N]
```

## Circuit Breakers

**The "paperclip problem" won't happen here.**

You've heard the thought experiment: tell an AI to make paperclips efficiently, and it converts the entire planet into paperclips because you didn't say when to stop. ReOS has hard-coded limits that **the AI cannot override**:

| Protection | What It Prevents |
|------------|------------------|
| **Operation Limit** | Max 25 commands per plan—no infinite loops |
| **Time Limit** | 5 minute hard cap—no runaway execution |
| **Privilege Cap** | Max 3 sudo escalations—can't keep adding permissions |
| **Scope Lock** | Blocks actions unrelated to your request |
| **Human Checkpoints** | Forces pause after 2 automatic recoveries |

If the AI tries to "fix" your nginx install by deleting system logs? **Blocked.** Tries to run 100 commands to "optimize" your system? **Stopped at 25.** Keeps escalating to root? **Capped at 3.**

```
You: fix everything on my system

ReOS: [After 25 operations]
      ⚠️ Execution paused: Maximum operations reached (25/25)

      Completed: 24 steps
      Pending: 8 steps remaining

      Continue? (This resets the operation counter)
```

These limits are enforced in code, not by the AI's "judgment." The AI literally cannot change them during execution. Only you can modify them in config.

[Full technical details →](docs/reasoning.md#circuit-breakers-paperclip-problem-prevention)

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│          Natural Language Interface                      │
│     Shell CLI  │  Tauri Desktop App  │  HTTP API        │
└─────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│              LLM-First Reasoning Engine                  │
│  ┌─────────────────────────────────────────────────┐   │
│  │ Intent Parser: Query vs Action detection         │   │
│  │ Plan Generator: Step-by-step with rollback       │   │
│  │ System Context: Containers, Services, Packages   │   │
│  └─────────────────────────────────────────────────┘   │
│                         │                               │
│            ┌────────────┴────────────┐                 │
│            ▼                         ▼                 │
│     ┌─────────────┐          ┌─────────────┐          │
│     │   Queries   │          │   Actions   │          │
│     │  (answer)   │          │ (plan+exec) │          │
│     └─────────────┘          └─────────────┘          │
└─────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│                    Python Kernel                         │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────┐ │
│  │ Ollama LLM  │  │ Linux Tools │  │  SQLite State   │ │
│  └─────────────┘  └─────────────┘  └─────────────────┘ │
└─────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│                   Your Linux System                      │
│    systemd │ apt/dnf/pacman │ docker │ files │ ...     │
└─────────────────────────────────────────────────────────┘
```

### How It Works

1. **You speak naturally**: "stop all nextcloud containers"
2. **LLM parses intent**: Understands this is an ACTION on containers matching "nextcloud"
3. **System context**: Looks up actual containers: `nextcloud-app`, `nextcloud-redis`, `nextcloud-db`
4. **Plan generation**: Creates steps: stop each container, then remove if requested
5. **Preview & approval**: Shows exactly what will happen, waits for your OK
6. **Execution**: Runs commands with rollback capability

## Principles

From the [ReOS Charter](.github/ReOS_charter.md):

> ReOS exists to protect, reflect, and return human attention by making Linux transparent.

Applied to terminal usage:
- **Attention is labor**: Time spent Googling flags is attention stolen from real work
- **Transparency over magic**: Every command is previewed, explained, and approved by you
- **Capability transfer**: You learn the patterns through repeated exposure, not dependency
- **Safety without surveillance**: Deep system knowledge without privacy invasion
- **No paperclips**: Hard-coded limits prevent runaway AI execution

ReOS is a **Rosetta Stone** for the terminal, not a black box.

## Requirements

- Linux (any major distro)
- Python 3.12+
- Node.js 18+
- Rust toolchain (for Tauri)
- Ollama with a local model

## Development

```bash
# Run tests
uv run pytest tests/

# Run with debug logging
REOS_LOG_LEVEL=DEBUG npm run tauri:dev
```

## Roadmap

**Completed (M2): Conversational Flows**
- [x] LLM-first intent parsing (query vs action detection)
- [x] System context awareness (containers, services, packages)
- [x] Multi-step plan generation with approval workflow
- [x] Conversation persistence across shell invocations
- [x] Command preview with approval (approve/reject)
- [x] Live output streaming for command execution

**Current Focus (M3): Intelligence & Learning**
- [ ] Personal runbooks (remember past solutions)
- [ ] Proactive monitoring (alert on service failures)
- [ ] Pattern learning (auto-approve safe patterns)
- [ ] Live system state dashboard UI

**Future (M4+): Advanced Capabilities**
- [ ] Configuration file editing with diffs
- [ ] Network troubleshooting workflows
- [ ] Cron/timer management
- [ ] User/group management

See [tech-roadmap.md](docs/tech-roadmap.md) for full details.

## License

MIT

---

*ReOS: Because your computer should understand you, not the other way around.*
