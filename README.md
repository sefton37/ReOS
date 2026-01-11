# Talking Rock - Your AI, Your Rules

**An AI assistant that lives on your computer, not in the cloud. Free forever. No subscriptions. No data harvesting. Just help when you need it.**

---

## For Everyone (Even If You've Never Used Linux Before)

### What Is This?

Talking Rock is like having a helpful friend who:
- **Organizes your life** - Keeps track of your projects, todos, and what needs attention
- **Manages your computer** - Helps you do things on your Linux computer through conversation
- **Helps you code** - If you're a developer, it can write and fix code with you

### Why Should You Care?

Every major AI assistant (ChatGPT, Copilot, Claude) runs on someone else's servers. That means:
- You pay monthly subscriptions forever
- Your private conversations go to their computers
- They can change the rules anytime
- If they shut down, you lose access

**Talking Rock is different:**
- **It runs on YOUR computer** - Your data stays with you
- **It's free** - No subscription, ever
- **You own it** - Open source, can't be taken away
- **It works offline** - No internet required for local models

### Is This For Me?

Talking Rock is for you if:
- You want an AI assistant that respects your privacy
- You're tired of subscription fatigue
- You want to learn Linux with a patient helper
- You're a developer who wants local AI coding assistance
- You believe software should work for users, not advertisers

### What Do I Need?

**The basics:**
- A computer running Linux (Ubuntu, Fedora, Mint, etc.)
- At least 8GB of RAM (16GB recommended for better AI models)
- About 10GB of free disk space

**Never used Linux?** That's okay! Here's the simplest path:
1. Install [Linux Mint](https://linuxmint.com/) - it's designed for beginners
2. Follow our [Beginner's Setup Guide](docs/beginners-guide.md) (coming soon)

---

## How It Works

Talking Rock has three specialized helpers (we call them "agents"):

| Agent | What It Does | Example |
|-------|--------------|---------|
| **RIVA** | Writes and verifies code with multi-layer validation | "Add login to my web app" |
| **CAIRN** | Manages your attention and life | "What should I focus on today?" |
| **ReOS** | Controls your computer | "What's using all my memory?" |

You talk to CAIRN by default. It automatically routes to the right helper:
- Code question? Routes to RIVA (with your permission)
- Computer question? Routes to ReOS (with your permission)
- Life question? CAIRN handles it

---

## The Three Agents

```
                        TALKING ROCK

    ┌──────────────────────────────────────────────────────┐
    │                      CAIRN                            │
    │              (Your Default Helper)                    │
    │         Life · Attention · Knowledge Base             │
    │                                                       │
    │   "System problem?" → ReOS                           │
    │   "Coding task?" → RIVA                              │
    │   "Life/planning?" → I've got this                   │
    └───────────────────┬──────────────────────────────────┘
                        │
            ┌───────────┴───────────┐
            ▼                       ▼
    ┌──────────────┐       ┌──────────────┐
    │    ReOS      │       │    RIVA      │
    │   (System)   │       │    (Code)    │
    └──────────────┘       └──────────────┘
```

### RIVA - The Code Verification Engine

**RIVA** (Recursive Intention-Verification Architecture) is a coding assistant that doesn't just write code—it *proves* the code works through multi-layer verification.

Unlike ChatGPT or Copilot that optimize for speed, RIVA optimizes for correctness. It uses free local inference to run multiple verification passes, catching errors before they reach you.

#### The 4-Layer Verification System

Every code change goes through progressive validation:

```
RIVA's Verification Pipeline
├─ Layer 1: SYNTAX (~1ms)
│  └─ Tree-sitter AST parsing + language validators
│     ✓ Catches: Missing brackets, invalid syntax, parse errors
│
├─ Layer 2: SEMANTIC (~10ms)
│  └─ Undefined names, unresolved imports, type checks
│     ✓ Catches: Typos, missing imports, wrong function calls
│
├─ Layer 3: BEHAVIORAL (~100ms-1s)
│  └─ Pytest execution, compilation checks, runtime validation
│     ✓ Catches: Logic errors, test failures, runtime crashes
│
└─ Layer 4: INTENT (~500ms-2s)
   └─ LLM judge comparing code to your request
      ✓ Catches: Correct code that solves the wrong problem
```

**Philosophy**: *"Spend tokens freely to be certain"*

With free local inference, RIVA can afford to:
- Run tests on every change
- Parse code with tree-sitter AST for 7+ languages
- Execute multiple verification passes
- Use LLM judges for intent alignment

The cost is time (1-3 seconds extra), not money. The benefit is confidence: **80% → 98% first-try success rate**.

#### Pattern Learning & Fast Paths

RIVA learns from experience and optimizes common patterns:

```python
# First time: Full verification (2-4 seconds)
You: "Add an import for requests"
RIVA: [Analyzing... Verifying... Done] ✓ Added

# After pattern learned (trust > 0.9):
You: "Add an import for numpy"
RIVA: [Fast path: ADD_IMPORT] ✓ Added (180ms)
```

**4 Fast Path Handlers:**
- `ADD_IMPORT` - Smart import placement (after docstrings, grouped correctly)
- `FIX_IMPORT` - Resolve missing/broken imports
- `CREATE_FUNCTION` - Generate function stubs with type hints
- `ADD_TEST` - Generate pytest-style test functions

Patterns with >90% success rate skip individual verification but still track outcomes.

#### Multi-Language Intelligence

RIVA uses **tree-sitter** for proper AST parsing across languages:

| Language | Support | Capabilities |
|----------|---------|--------------|
| Python | Full | Functions, classes, imports, async, decorators |
| JavaScript/TypeScript | Full | ES6+, arrow functions, imports, async |
| Rust | Coming | Structs, impls, traits |
| Go | Coming | Functions, interfaces, packages |

**No more regex guessing** - RIVA understands code structure natively:
- Nested functions, complex decorators, multiline strings
- Accurate import positioning (respects `__future__`, docstrings)
- Fast incremental parsing (~1-2ms per file)

#### How It Works

```
You: Add user login to my API

RIVA: [Layer 1: Intent Discovery]
      - You want: Authentication for your API
      - I found: src/api/ with Flask routes
      - Pattern: REST_AUTHENTICATION (trust: 0.87)

      [Layer 2: Contract Building]
      ✓ test_login_valid_credentials must pass
      ✓ test_login_invalid_password must pass
      ✓ test_logout_clears_session must pass

      [Layer 3: Execution with Verification]
      1. Create src/auth.py
         └─ SYNTAX ✓ (1ms) → SEMANTIC ✓ (12ms) → Ready
      2. Add routes to src/api/routes.py
         └─ SYNTAX ✓ (1ms) → SEMANTIC ✓ (8ms) → Ready
      3. Create tests/test_auth.py
         └─ SYNTAX ✓ (2ms) → SEMANTIC ✓ (15ms) → Ready
      4. Run pytest
         └─ BEHAVIORAL ✓ (847ms) → All tests pass

      [Layer 4: Intent Check]
      └─ LLM Judge ✓ (1.2s) → Matches request

      Total confidence: 96%
      Approve changes? [y/n]
```

#### Test-First Philosophy

RIVA follows **"If you can't verify it, decompose it"**:

1. **Discover intent** - Analyze your request + codebase context
2. **Build contract** - Define testable acceptance criteria
3. **Write tests first** - Generate test spec before implementation
4. **Implement** - Write code that passes the tests
5. **Verify** - Run all 4 layers to confirm success

If verification fails, RIVA creates a "gap contract" and retries automatically.

#### What RIVA Can Do

**Core Capabilities:**
- ✅ Multi-language AST parsing (Python, JS/TS, Rust, Go)
- ✅ 4-layer progressive verification (syntax → semantic → behavioral → intent)
- ✅ Pattern success tracking with trust scoring
- ✅ Fast path optimization for common tasks (imports, functions, tests)
- ✅ Test-first development with pytest integration
- ✅ Automatic self-debugging loop
- ✅ Git integration (commits, diffs, status)
- ✅ Graceful degradation (falls back if tools unavailable)

**Why RIVA is Different:**

| Approach | ChatGPT/Copilot | RIVA |
|----------|-----------------|------|
| Speed | 5-15 seconds | 15-45 seconds |
| Verification | None (you test it) | 4 layers before showing you |
| First-try success | 90-95% | 85-90% (but safer) |
| Learning | Resets each session | Learns patterns per-repo |
| Cost model | Optimize for tokens | Optimize for correctness |

**The Tradeoff**: RIVA is slower because it spends extra time verifying before acting. You still approve all changes. You just need patience.

**When to Use RIVA:**
- Production code that must be correct
- Unfamiliar codebases (RIVA reads the structure first)
- Test coverage matters
- Learning new languages (RIVA explains as it goes)
- You value correctness over speed

### CAIRN - The Attention Minder

Your calm, non-judgmental life organizer. CAIRN helps you focus on what matters without making you feel guilty about what you haven't done yet.

**Core Philosophy:**
- Shows you the **next thing**, not everything
- **You decide priority** - CAIRN just helps you see when decisions are needed
- Integrates with your calendar (Thunderbird)
- **Never guilt-trips** - "Waiting when you're ready" instead of "You haven't touched this in 30 days!"

**What It Can Do:**
- Track projects, todos, and notes
- Surface what needs attention today
- Link people to projects (knows who's involved in what)
- Keep track of what you're waiting on
- Understand your identity and filter distractions (Coherence Kernel)

### ReOS - The System Helper

Talk to your Linux computer in plain English. ReOS understands your system deeply and explains what it's doing.

```
You: What's using all my memory?

ReOS: Here are the top memory users:
      1. Chrome (2.3 GB)
      2. Docker (1.8 GB)
      3. VS Code (890 MB)

You: Stop all my Docker containers

ReOS: I'll stop these containers:
      - nextcloud-app
      - nextcloud-redis
      - nextcloud-db

      Proceed? [y/n]: y
      Done! All containers stopped.
```

**What It Can Do:**
- Monitor processes and memory
- Manage services (systemd)
- Install and remove packages
- Control Docker containers
- Work with files
- Run shell commands (with safety checks)

**Shell Integration Philosophy:**

ReOS shell integration follows one core principle: **Never obstruct Linux**.

When you install a package and apt asks `Do you want to continue? [Y/n]`, you type Y. That's how Linux works. ReOS enhances your terminal with natural language - it never breaks the normal flow.

This means:
- Commands run with full terminal access (stdin/stdout/stderr connected)
- Interactive prompts work normally - you can always respond
- ReOS adds capability, never removes it
- Prefix with `!` to bypass ReOS entirely: `!apt install vim`

```bash
# Enable shell integration (add to ~/.bashrc)
source /path/to/ReOS/scripts/reos-shell-integration.sh

# Now just type naturally
$ install gimp
[ReOS understands and runs: sudo apt install gimp]
[apt prompts for Y/n - you type normally]
```

**Context-Aware Proposals (Parse Gate):**

ReOS checks your system before proposing commands - it knows what's installed:

```
$ run gimp                           # gimp IS installed
→ Proposal: gimp                     # Just run it

$ run gimp                           # gimp NOT installed
→ Proposal: sudo apt install gimp    # Offer to install

$ picture editor                     # Natural language
→ Found: GIMP (GNU Image Manipulation Program)
→ Proposal: gimp
```

How it works:
1. **Intent Analysis** - Detects verbs: run, install, start, stop, etc.
2. **System Check** - Queries PATH, packages, services
3. **Semantic Search** - Finds programs by description ("picture editor" → GIMP)
4. **Smart Proposal** - Context-aware command suggestion

See [Parse Gate Architecture](docs/parse-gate.md) for technical details.

---

## Safety First

### You're Always in Control

- **Preview before changes** - See exactly what will change before any file is modified
- **Approval required** - All changes need your OK
- **Automatic backups** - Every modified file is backed up
- **Undo anything** - Rollback any change

### Built-in Limits

Talking Rock has safety limits that can be tuned but not disabled:

| Protection | Default | Tunable Range |
|------------|---------|---------------|
| Max iterations per task | 10 | 3-50 |
| Max run time | 5 minutes | 1-30 minutes |
| Sudo commands per session | 10 | 1-20 |
| Auth attempts (rate limit) | 5/minute | N/A |
| Command max length | 8KB | 1-16KB |

### Your Privacy

- **Local by default** - With Ollama, everything stays on your machine
- **No tracking** - We don't know you exist
- **Open source** - Read every line of code
- **Your choice** - Use local AI or cloud APIs

---

## Getting Started

### Quick Install (Experienced Users)

```bash
# 1. Install Ollama (runs AI models locally)
curl -fsSL https://ollama.com/install.sh | sh
ollama pull llama3.2

# 2. Clone and install Talking Rock
git clone https://github.com/sefton37/ReOS
cd ReOS
pip install -e .

# 3. Run the app
cd apps/reos-tauri
npm install
npm run tauri:dev
```

### Step-by-Step Install (Beginners)

**Step 1: Install Ollama**

Ollama lets you run AI models on your own computer. Open a terminal and paste:
```bash
curl -fsSL https://ollama.com/install.sh | sh
```

Then download a model:
```bash
ollama pull llama3.2
```

**Step 2: Install Talking Rock**

```bash
# Clone the code
git clone https://github.com/sefton37/ReOS
cd ReOS

# Install Python dependencies
pip install -e .

# Install the desktop app
cd apps/reos-tauri
npm install
```

**Step 3: Run It**

```bash
npm run tauri:dev
```

A window will open. Start talking to CAIRN!

---

## The Play - Your Personal Knowledge System

Everything in Talking Rock is organized around "The Play" - a hierarchical system for your life:

| Level | Timeframe | Example |
|-------|-----------|---------|
| **The Play** | Your whole life | Your identity, values, goals |
| **Acts** | Major life chapters | "Building my startup", "Learning music" |
| **Scenes** | Projects within acts | "Launch MVP", "Complete album" |
| **Beats** | Tasks within scenes | "Set up database", "Record vocals" |

CAIRN uses this structure to:
- Know what you're working on
- Surface the right things at the right time
- Understand context when you ask questions

---

## How Talking Rock Compares

| Feature | ChatGPT | Copilot | Talking Rock |
|---------|---------|---------|--------------|
| Works offline | No | No | **Yes** |
| Your data stays private | No | No | **Yes** |
| Free forever | No | No | **Yes** |
| Open source | No | No | **Yes** |
| Life organization | No | No | **Yes** |
| Linux system control | No | No | **Yes** |
| Code assistance | Yes | Yes | **Yes** |

### The Honest Tradeoff

> "ChatGPT optimizes for speed. RIVA optimizes for correctness."

| Dimension | Big Tech | Talking Rock |
|-----------|----------|--------------|
| **Speed** | 5-15 seconds | 15-45 seconds |
| **Cost** | $20-500/month | Free |
| **First-try success** | 90-95% | 85-90% (but safer) |
| **Ownership** | Their cloud | Your machine |
| **Trust** | Optimized for speed | Optimized for verification |

**Why choose slower?** Because Talking Rock spends extra cycles verifying before acting. The tradeoff: slower responses, but more rigorous checking. You still approve all changes. All you need is patience.

---

## The Mission

> **Don't rent a data center. Center your data around you.**

Big tech companies want AI to be a subscription you pay forever. They collect your data, train on your conversations, and can change the rules anytime.

We believe AI should be:
- **Owned by you** - Not rented from a corporation
- **Private** - Your thoughts are your own
- **Transparent** - You can see exactly how it works
- **Free** - No subscription, no "we changed our pricing"

**Our goal: Build the best AI assistant in the world. Then give it away.**

---

## What's Built

### RIVA (Code Agent)
- [x] **Multi-Layer Verification System**
  - [x] Layer 1: Syntax validation (~1ms) - Tree-sitter AST parsing
  - [x] Layer 2: Semantic analysis (~10ms) - Undefined names, imports
  - [x] Layer 3: Behavioral testing (~100ms-1s) - Pytest execution
  - [x] Layer 4: Intent alignment (~500ms-2s) - LLM judge (placeholder)
  - [x] Verification strategies (MINIMAL, STANDARD, THOROUGH, MAXIMUM)
  - [x] Confidence scoring with weighted layer contributions
- [x] **Tree-Sitter Multi-Language Parsing**
  - [x] Python parser (functions, classes, imports, async, decorators)
  - [x] JavaScript/TypeScript parser (ES6+, arrow functions, async)
  - [x] Abstract parser interface for extensibility
  - [x] Graceful degradation (fallback to regex if unavailable)
- [x] **Pattern Success Tracking**
  - [x] Per-repo pattern learning with trust scoring
  - [x] Recency decay for adaptive trust
  - [x] Integration with verification layer (>0.9 trust skips checks)
- [x] **Fast Path Optimization**
  - [x] ADD_IMPORT - Smart import placement
  - [x] FIX_IMPORT - Resolve missing imports
  - [x] CREATE_FUNCTION - Generate function stubs
  - [x] ADD_TEST - Generate pytest-style tests
- [x] Intent discovery with codebase context
- [x] Test-first development with contract building
- [x] Self-debugging loop with gap contracts
- [x] Git integration (commits, diffs, status)
- [x] Multi-language support (Python, JS/TS, Rust, Go)

### CAIRN (Attention Minder)
- [x] Knowledge base integration
- [x] Kanban tracking (active, backlog, waiting, done)
- [x] Activity tracking (when you last touched things)
- [x] Priority management
- [x] Calendar integration (Thunderbird)
- [x] Contact knowledge graph
- [x] Smart surfacing ("what needs attention")
- [x] **Coherence Kernel** - Filters distractions based on your identity
- [x] 27 MCP tools

### ReOS (System Agent)
- [x] Natural language system control
- [x] Service, package, container management
- [x] Safety layer with command blocking
- [x] Circuit breakers
- [x] **Parse Gate** - Context-aware command proposals
  - [x] Intent pattern matching (run/install/service verbs)
  - [x] System state lookup (PATH, packages, services)
  - [x] FTS5 full-text search for packages/apps
  - [x] Semantic vector search (synonym matching)
  - [x] Three-layer safety extraction

### Handoff System
- [x] Seamless agent switching
- [x] User approval for all transitions
- [x] Context preservation

---

## Requirements

**Minimum:**
- Linux (Ubuntu, Fedora, Mint, Arch, etc.)
- Python 3.12+
- 8GB RAM
- 10GB disk space

**Recommended:**
- 16GB+ RAM (for better AI models)
- GPU (for faster inference)

**Optional:**
- Node.js 18+ (for desktop app)
- Rust toolchain (for desktop app)
- Thunderbird (for calendar/contacts)

---

## Documentation

- [Beginner's Guide](docs/beginners-guide.md) - New to Linux? Start here
- [Technical Roadmap](docs/tech-roadmap.md) - Development plans
- [App Vision](docs/app-vision.md) - What we're building and why
- [RIVA Performance Strategy](docs/riva-performance-strategy.md) - How we compete with big tech
- [Security Design](docs/security.md) - How we protect your system
- [CAIRN Architecture](docs/cairn_architecture.md) - Attention minder design
- [RIVA Architecture](docs/code_mode_architecture.md) - Code agent design
- [Parse Gate Architecture](docs/parse-gate.md) - Context-aware shell proposals
- [The Play System](docs/the-play.md) - Knowledge organization

---

## Contributing

Talking Rock is open source (MIT license). We welcome:
- Bug reports and feature requests
- Code contributions
- Documentation improvements
- Testing on different Linux distributions
- Translations

See [CONTRIBUTING.md](.github/CONTRIBUTING.md) for guidelines.

---

## Community

- GitHub Issues for bugs and features
- Discussions for questions and ideas

---

## License

MIT - Do whatever you want with it.

---

*Talking Rock: AI that works for you, on your terms.*
