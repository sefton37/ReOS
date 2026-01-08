# ReOS - Your AI, Your Hardware, Your Code

**The open source, local-first AI that gives you everything the trillion-dollar tech companies charge perpetual rent for—running on your own hardware, with your data staying private when you choose local models.**

ReOS is two things:

1. **Natural Language Linux**: Control your entire Linux system through conversation. No more memorizing commands.
2. **Agentic Coding Partner**: A full AI coding assistant that rivals Cursor, Copilot, and Devin—but open source, private, and yours.

Both capabilities share the same philosophy: **AI should be a tool you own, not a service you rent.**

---

## The Vision

The best AI coding tools today—Cursor, GitHub Copilot, Devin—are remarkable. They're also:
- **Subscription-based**: $20-500/month, forever
- **Cloud-dependent**: Your code goes to their servers
- **Proprietary**: You can't see how they work, fix bugs, or add features
- **Lock-in prone**: Switch costs increase over time

ReOS proves there's another way:

| Commercial Tools | ReOS |
|-----------------|------|
| Monthly subscription | One-time install, free forever |
| Code sent to cloud | Local-first (Ollama) or cloud API—your choice |
| Black box | Open source, auditable |
| Their model, their rules | Your choice of model (Ollama, local llama.cpp, or cloud API) |
| Engagement-optimized | Sovereignty-optimized |

**The goal isn't to be "good enough for free." The goal is to be the best—and also free.**

---

## What ReOS Does

### Natural Language Linux

Control your system through conversation:

```bash
$ reos "what's using all my memory"
Top memory users:
1. chrome (2.3 GB)
2. docker (1.8 GB)
3. code (890 MB)

$ reos "stop all nextcloud containers"
Plan:
  1. Stop nextcloud-app
  2. Stop nextcloud-redis
  3. Stop nextcloud-db

Proceed? [y/n]: y
✓ All containers stopped.
```

- **Deep system understanding**: ReOS knows YOUR containers, services, packages by name
- **Transparent actions**: Multi-step plans are previewed before execution
- **Safety first**: Dangerous commands are blocked, risky ones flagged for review
- **Capability transfer**: You learn the patterns through repeated exposure

### Code Mode: Agentic Coding

When an Act in The Play has a repository assigned, ReOS becomes a full coding partner:

```
You: Add user authentication to the API

ReOS: [INTENT] Analyzing request...
      - Action: Add new feature
      - Target: API authentication
      - Codebase: Python/FastAPI, src/ structure

      [CONTRACT] Success criteria:
      ✓ test_login_valid_credentials passes
      ✓ test_login_invalid_password passes
      ✓ test_logout_clears_session passes
      ✓ Code compiles without errors

      [PLAN] 4 steps:
      1. Create src/auth.py with login/logout functions
      2. Add routes to src/api/routes.py
      3. Create tests/test_auth.py
      4. Run tests to verify

      [Showing diff preview...]

      Approve changes? [y/n]
```

**How Code Mode Works:**

```
Intent → Contract → Decompose → Build → Verify → [Debug if failed] → Integrate → Gap Analysis → Repeat
```

1. **Intent Discovery**: Understands what you want from the prompt, your project context (The Play), and the codebase
2. **Contract Generation**: Defines explicit, testable success criteria—actual test code, not vague descriptions
3. **Decomposition**: Breaks the contract into atomic steps
4. **Build**: Writes code for the most concrete step
5. **Verify**: Runs tests, checks compilation—execution output is ground truth
6. **Debug**: If verification fails, analyzes the error and attempts fixes (up to 3 retries)
7. **Integrate**: Merges verified code into the repository
8. **Gap Analysis**: What remains? Loop until complete.

**Perspective Shifting**: Each phase uses a different AI persona:
- **Analyst**: Understands intent deeply before acting
- **Architect**: Designs testable contracts
- **Engineer**: Writes minimal, correct code
- **Critic**: Skeptical of AI output, trusts test results
- **Debugger**: Diagnoses failures, proposes fixes
- **Integrator**: Merges safely

---

## The Play - Your Personal Knowledge System

ReOS includes a hierarchical knowledge system that provides context across everything you do:

| Level | Time Horizon | Example |
|-------|--------------|---------|
| **The Play** | Your life | Your identity, values, long-term vision |
| **Acts** | > 1 year | "Building my startup", "Career at Company X" |
| **Scenes** | > 1 month | "Launch MVP", "Q1 Platform Migration" |
| **Beats** | > 1 week | "Set up CI/CD", "Implement auth" |

When you assign a repository to an Act, ReOS enters Code Mode for requests in that context. The Play provides the "why" behind your code—what you're building and where it fits in your life.

---

## Safety & Sovereignty

### You're Always in Control

- **Diff preview**: See exactly what will change before any file is modified
- **Approval required**: All file changes, commands, and plans require your explicit OK
- **Automatic backups**: Every file modification is backed up
- **Rollback**: Undo any change

### Circuit Breakers (The Paperclip Problem)

Built-in limits to prevent runaway operations:

| Protection | Limit | Enforcement |
|------------|-------|-------------|
| Max operations per task | 25 | ✓ Enforced |
| Max execution time | 5 minutes | ✓ Enforced |
| Max sudo escalations | 3 | ✓ Enforced |
| Debug retry attempts | 3 | ✓ Enforced |
| Human checkpoint | After 2 automated recoveries | ✓ Enforced |
| Rate limiting | Per-category (auth, service, package) | ✓ Enforced |

If the AI tries to "fix" your nginx install by deleting system logs? **Blocked.** Tries to run 100 commands? **Stopped at 25.**

### Privacy

- **Local-first**: With Ollama, code never leaves your machine
- **No telemetry**: We don't know you exist
- **Open source**: Audit everything
- **Your choice**: Use Ollama locally, or cloud APIs (Anthropic, OpenAI) if you prefer

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                           ReOS                                       │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│   ┌─────────────────────────────────────────────────────────────┐   │
│   │                    Natural Language Layer                    │   │
│   │              Shell CLI  │  Tauri Desktop App                │   │
│   └─────────────────────────────────────────────────────────────┘   │
│                               │                                      │
│   ┌───────────────────────────┴───────────────────────────┐         │
│   │                                                        │         │
│   │   ┌─────────────────┐         ┌─────────────────────┐ │         │
│   │   │   Linux Mode    │         │     Code Mode       │ │         │
│   │   │                 │         │                     │ │         │
│   │   │ • System info   │         │ • Intent discovery  │ │         │
│   │   │ • Services      │         │ • Contract-based    │ │         │
│   │   │ • Packages      │         │ • Test-first        │ │         │
│   │   │ • Containers    │         │ • Self-debugging    │ │         │
│   │   │ • Files         │         │ • Perspective shift │ │         │
│   │   └─────────────────┘         └─────────────────────┘ │         │
│   │                                                        │         │
│   │   ┌─────────────────────────────────────────────────┐ │         │
│   │   │              Shared Infrastructure               │ │         │
│   │   │                                                  │ │         │
│   │   │  The Play (KB)  │  Safety Layer  │  Model Backend │         │
│   │   │                                                  │ │         │
│   │   │  Ollama │ Anthropic │ OpenAI │ Local llama.cpp  │ │         │
│   │   └─────────────────────────────────────────────────┘ │         │
│   └────────────────────────────────────────────────────────┘         │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Local-First Reliability Philosophy

ReOS is built for a fundamentally different environment than commercial AI coding tools.

### The Reality of Local Models

Commercial tools like Cursor and Copilot assume:
- GPT-4/Claude-level reliability (valid JSON 99%+ of the time)
- Large context windows that preserve all details
- Consistent instruction following
- Fast, always-available cloud infrastructure

Local models (Ollama + Mistral/Llama/etc.) have different characteristics:
- JSON formatting may fail more often
- Smaller context windows = lost details
- Variable instruction following quality
- Need explicit examples, not just instructions

**ReOS is designed for unreliable LLM responses as the norm, not the exception.**

### Graceful Degradation, Not Quality Cliffs

Every layer of ReOS produces useful output. When the LLM fails, we don't fall off a cliff:

```
┌─────────────────────────────────────────────────────────────────────┐
│ TIER 1: LLM Success                                                  │
│ ├── Full intent understanding                                        │
│ ├── Sophisticated decomposition                                      │
│ └── Generated code with tests                                        │
├─────────────────────────────────────────────────────────────────────┤
│ TIER 2: LLM Partial Success                                          │
│ ├── Intent understood, JSON malformed                                │
│ ├── Smart heuristic fallback with real implementations               │
│ └── User notified of degraded mode                                   │
├─────────────────────────────────────────────────────────────────────┤
│ TIER 3: LLM Failure                                                  │
│ ├── Pattern-based code generation (factorial, fibonacci, etc.)       │
│ ├── Template-driven scaffolding                                      │
│ └── Transparent "needs completion" markers                           │
└─────────────────────────────────────────────────────────────────────┘
```

### Execution is Ground Truth

ReOS doesn't trust the LLM's claim that code works. We verify:

1. **Syntax Check**: Code parses without errors
2. **Import Check**: Module can be imported
3. **Function Check**: Functions are callable
4. **Test Execution**: Actual tests run and pass

*"Verified" means "executed successfully," not "file was created."*

### Transparency Over Hidden Failures

When quality degrades, the user knows:

```
[QUALITY: TIER 1] ✓ LLM generated verified code
[QUALITY: TIER 2] ⚠ Heuristic fallback (LLM JSON failed)
[QUALITY: TIER 3] ⚠ Pattern-based generation (needs review)
```

This philosophy—build for unreliability, degrade gracefully, verify with execution, be transparent—is what makes local-first AI actually work.

---

## Quick Start

```bash
# 1. Install Ollama
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

# 4. (Optional) Assign a repository to an Act for Code Mode
# In the UI: Select an Act → Settings → Assign Repository
```

---

## What's Built (Current State)

### Linux Mode (Complete)
- [x] Natural language system control
- [x] Deep system understanding (containers, services, packages, processes)
- [x] Multi-step plan generation with approval workflow
- [x] Safety layer (command blocking, risk assessment, rate limiting)
- [x] Circuit breakers (25 ops, 5 min, 3 sudo)
- [x] Conversation persistence

### Code Mode (Core Complete, Semantic Understanding Building)
- [x] Repository assignment to Acts
- [x] Code vs sysadmin request routing
- [x] Intent discovery (prompt + Play + codebase patterns)
- [x] Contract-based development (testable success criteria)
- [x] Perspective shifting (Analyst → Architect → Engineer → Critic → Debugger)
- [x] Self-debugging loop (analyze failures, apply fixes, retry)
- [x] Execution-based verification (run tests, trust output)
- [x] Gap analysis and iterative completion
- [x] Quality tier tracking (transparency when LLM falls back to heuristics)
- [ ] Semantic code understanding (dependency graphs, symbol tables) — *in progress*

### What's Next (See Roadmap)
- [ ] Repository map (dependency graph, semantic search)
- [ ] Diff preview UI (see changes before applying)
- [ ] Test-first contracts (generate actual test code)
- [ ] Long-term memory (remember decisions, patterns, corrections)
- [ ] LSP integration (real-time type checking)
- [ ] Multi-path exploration (try multiple approaches)

---

## Comparison: ReOS vs Commercial Tools

| Capability | Cursor | Copilot | Devin | ReOS |
|------------|--------|---------|-------|------|
| Code completion | ✓ | ✓ | ✓ | ✓ |
| Multi-file editing | ✓ | Partial | ✓ | ✓ |
| Test execution | ✓ | ✗ | ✓ | ✓ |
| Self-debugging | Partial | ✗ | ✓ | ✓ |
| Codebase awareness | ✓ | Partial | ✓ | Building |
| Long-term memory | ✗ | ✗ | ✓ | Planned |
| **Local-First Option** | ✗ | ✗ | ✗ | **✓** |
| **Open Source** | ✗ | ✗ | ✗ | **✓** |
| **No Subscription** | ✗ | ✗ | ✗ | **✓** |
| **Data Privacy (with local)** | ✗ | ✗ | ✗ | **✓** |
| Linux sysadmin | ✗ | ✗ | ✗ | **✓** |

---

## The Meaning

Software is eating the world. AI is eating software. And a handful of companies want to be the landlords of AI—charging rent forever for tools that could run on your own hardware.

ReOS is the alternative:
- **User sovereignty**: You control the AI, not the other way around
- **Transparency**: See every decision, every step, every line of reasoning
- **Privacy**: With local models, your code and data stay on your machine
- **Freedom**: No lock-in, no subscription, no "we changed our pricing"
- **Community**: Open source means we all make it better together

The trillion-dollar companies have resources we don't. But they also have incentives we don't—engagement metrics, retention, lock-in. ReOS can be optimized purely for what's best for the user.

**The goal: Make the best AI coding assistant in the world. Then give it away.**

---

## Contributing

ReOS is open source (MIT). Contributions welcome:
- Bug reports and feature requests via GitHub Issues
- Code contributions via Pull Requests
- Documentation improvements
- Testing on different distros and configurations

See [CONTRIBUTING.md](.github/CONTRIBUTING.md) for guidelines.

---

## Requirements

- Linux (any major distro)
- Python 3.12+
- Node.js 18+ (for Tauri UI)
- Rust toolchain (for Tauri)
- Ollama with a local model (or API key for cloud models)

---

## Links

- [Technical Roadmap](docs/tech-roadmap.md) - Full implementation plan
- [Security Design](docs/security-design.md) - How ReOS protects your system
- [ReOS Charter](.github/ReOS_charter.md) - Philosophy and principles
- [The Play Documentation](docs/the-play.md) - Knowledge system details

---

## License

MIT

---

*ReOS: Because AI should work for you, not rent from you.*
