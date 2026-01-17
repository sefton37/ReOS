# Talking Rock

## The Mission

> **Don't rent a data center. Center your data around you.**

Talking Rock is an AI assistant that runs entirely on your computer. Not a thin client connecting to someone else's servers—the actual AI, running locally, under your control.

**This is our competitive advantage.** Local inference isn't just about privacy (though you get that too). It's about economics:

- **Cloud AI costs money per token.** Every verification pass, every repo analysis, every safety check—they all cost the provider money. So they minimize them.
- **Local inference is essentially free.** Once you have the model, compute costs nothing extra. So we can verify every line of code. Analyze every repository. Check every command. Do things that subscription services can't afford at scale.

Big tech wants AI to be a subscription you pay forever. They collect your data, train on your conversations, and can change the rules anytime.

We believe AI should be:
- **Local** — The AI runs on your machine, not in a data center
- **Private** — Your conversations never leave your computer
- **Free** — No subscription, no "we changed our pricing"
- **Yours** — Open source, can't be taken away

**Our goal: Build the best AI assistant in the world. Then give it away.**

### A Mirror That Doesn't Sell Your Reflection

Every productivity tool asks: *"How can we capture what this person does?"*

Talking Rock asks: *"How can this person see themselves clearly?"*

**Zero trust. Local only. Encrypted at rest. Never phones home.**

The only report goes to the only stakeholder that matters: you.

---

## Development Priorities: Democratizing AI

True democratization means running on hardware people actually have. A 70B model that needs a $2000 GPU isn't democratized—it's just a different kind of paywall.

**Our target: 1-3B parameter models.** These run on 8GB RAM, integrated graphics, and five-year-old laptops. If your computer can run a web browser, it should be able to run Talking Rock.

### Current Priorities

| Priority | Agent | Target Model Size | Status |
|----------|-------|-------------------|--------|
| **1** | CAIRN | 1B parameters | Active development |
| **2** | ReOS | 1-3B parameters | Active development |
| **3** | RIVA | 7-8B+ parameters | Frozen (future work) |

**Why this order:**

1. **CAIRN (Attention Minder)** — Surfacing tasks, managing priorities, and routing requests are achievable at 1B. The model needs to understand intent and match patterns, not generate complex code. This is where we can deliver real value on minimal hardware.

2. **ReOS (System Helper)** — Natural language to shell commands is more constrained than open-ended coding. The Parse Gate provides structure, and most system commands follow predictable patterns. Targeting 1-3B parameters.

3. **RIVA (Code Agent)** — Multi-layer verification with LLM judges, code generation, and intent alignment genuinely requires more capable reasoning. We're freezing RIVA at its current state until CAIRN and ReOS prove the 1B thesis. Future work, likely requiring 7-8B+ models.

**The honest reality:** Not everything can be democratized immediately. Code generation with verification is harder than attention management. We're prioritizing what we can ship on accessible hardware today, not what sounds impressive in a README.

---

## What Talking Rock Does

Talking Rock is three specialized agents working together:

| Agent | Purpose | Model Target | Status |
|-------|---------|--------------|--------|
| **CAIRN** | Manages your attention and life | 1B | Active |
| **ReOS** | Controls your Linux system | 1-3B | Active |
| **RIVA** | Writes and verifies code | 7-8B+ | Frozen |

You talk to CAIRN by default. It routes to the right agent when needed:
- Life/planning → CAIRN handles it directly
- System question → Routes to ReOS (with your approval)
- Code question → Routes to RIVA (with your approval, when unfrozen)

**Why local matters here:** Because routing and verification happen locally, every request can be analyzed, checked, and validated without cost concerns. Cloud services charge per token—we don't.

---

## CAIRN: The Attention Minder (Priority 1)

**Thesis:** CAIRN helps you focus on what matters without overwhelming you. It shows you the next thing, not everything—and never guilt-trips you about what you haven't done.

**Target: 1B parameter models.** Surfacing and prioritization are pattern-matching tasks—achievable with smaller models.

### How CAIRN Works: The Journey of Your Day

**Step 1: You Ask What Needs Attention**
```
You: "What should I focus on today?"
```

**Step 2: CAIRN Checks Your Context**

CAIRN knows your life structure through "The Play":
```
[Context Check]
├─ Current Act: "Building my startup"
├─ Active Scene: "Launch MVP"
├─ Calendar: Meeting at 2pm, deadline Friday
├─ Waiting on: Response from designer
└─ Last touched: Database schema (3 days ago)
```

**Step 3: Smart Surfacing**

CAIRN surfaces what needs attention based on:
- What's blocking other work
- What has upcoming deadlines
- What you haven't touched recently (without guilt)
- What aligns with your stated priorities

```
[Today's Focus]
1. Database schema needs review (blocking frontend work)
2. Designer response expected today
3. Friday deadline: MVP demo prep

Waiting for you when ready:
- Marketing copy draft
- Test coverage improvements
```

**Step 4: Routing When Needed**

If you ask something outside CAIRN's domain:
```
You: "What's using all my memory?"

CAIRN: That's a system question. Want me to hand off to ReOS?
       [Approve handoff? y/n]
```

### The Play: Your Life Structure

CAIRN organizes everything with deliberate simplicity—just two levels:

| Level | Timeframe | Example |
|-------|-----------|---------|
| **Acts** | Life narratives (months to years) | "Building my startup", "Learning music" |
| **Scenes** | Calendar events within acts | "Launch MVP meeting", "Record vocals session" |

**Why just two levels?** To remove the temptation to obscure responsibility in complexity. Acts answer "What narrative does this belong to?" Scenes answer "When am I doing this?" That's enough.

This structure lets CAIRN understand context. When you say "what's next?", it knows which act you're in and what scenes are coming up.

### Core Capabilities

- **Project tracking** — Acts and Scenes with status and priority
- **Calendar integration** — Syncs with Thunderbird (including recurring events)
- **Contact knowledge** — Knows who's involved in what
- **Waiting-on tracking** — Knows what you're blocked on
- **Coherence Kernel** — Filters distractions based on your stated identity and goals

### Conclusion

CAIRN is a calm, non-judgmental life organizer. It respects your attention by showing you the next thing—not a wall of everything you haven't done. It's a mirror for self-reflection, not a surveillance tool that reports on you. Because it runs locally, your life data stays on your machine. No company sees your priorities, your goals, or your struggles.

---

## ReOS: The System Helper (Priority 2)

**Thesis:** ReOS lets you control your Linux system through natural language while never obstructing normal terminal operation. It enhances your command line—it doesn't replace it.

**Target: 1-3B parameter models.** Shell commands are constrained and predictable. The Parse Gate provides structure that smaller models can work within.

### How ReOS Works: The Journey of a Command

**Step 1: You Type Naturally**
```
$ what's using all my memory?
```

**Step 2: Parse Gate Analysis**

ReOS analyzes your intent and checks system state:
```
[Parse Gate]
├─ Intent: Query memory usage
├─ Verb detected: "using" (diagnostic)
├─ System check: ps, top available
└─ Proposal: Show top memory consumers
```

**Step 3: Context-Aware Response**
```
Here are the top memory users:
1. Chrome (2.3 GB)
2. Docker (1.8 GB)
3. VS Code (890 MB)
```

**Step 4: Follow-Up Actions**
```
You: stop all docker containers

ReOS: I'll stop these containers:
      - nextcloud-app
      - nextcloud-redis
      - nextcloud-db

      Proceed? [y/n]: y
      Done! All containers stopped.
```

### The Parse Gate: Smart Command Proposals

ReOS checks your system before proposing commands:

```
$ run gimp                    # gimp IS installed
→ Proposal: gimp              # Just run it

$ run gimp                    # gimp NOT installed
→ Proposal: sudo apt install gimp   # Offer to install

$ picture editor              # Natural language
→ Found: GIMP (GNU Image Manipulation Program)
→ Proposal: gimp
```

**How Parse Gate works:**
1. **Intent Analysis** — Detects verbs: run, install, start, stop, etc.
2. **System Check** — Queries PATH, packages, services
3. **Semantic Search** — Finds programs by description ("picture editor" → GIMP)
4. **Smart Proposal** — Context-aware command suggestion

### Never Obstruct Linux

ReOS follows one core principle: **enhance, don't replace**.

When apt asks `Do you want to continue? [Y/n]`, you type Y. That's how Linux works. ReOS never breaks this flow:

- Commands run with full terminal access (stdin/stdout/stderr connected)
- Interactive prompts work normally
- Valid shell commands execute directly—ReOS only activates on unknown commands

### Core Capabilities

- **Process monitoring** — Memory, CPU, what's running
- **Service management** — Start, stop, restart systemd services
- **Package management** — Install, remove, search packages
- **Container control** — Docker and Podman management
- **File operations** — With safety checks
- **Shell commands** — Natural language to bash

### Conclusion

ReOS makes Linux approachable through conversation while respecting how Linux actually works. All system control happens locally—no cloud service sees your system state, your installed packages, or your running processes.

---

## RIVA: The Code Verification Engine (Frozen)

> **Status: Development frozen.** RIVA requires 7-8B+ parameter models for reliable code generation and verification. We're focusing on CAIRN and ReOS first to prove the small-model thesis. RIVA will resume development after those agents ship successfully on 1-3B models.

**Thesis:** RIVA trades compute time for correctness. Because local inference is cheap, it can verify every line of code through multiple layers before you see it—catching errors that cloud-based assistants can't afford to check for.

### What's Built (Frozen State)

RIVA has significant infrastructure already built:

- **3-layer verification** — Syntax (tree-sitter), Semantic (static analysis), Behavioral (pytest)
- **Intent verification framework** — Ready for LLM integration when we return
- **Pattern learning** — Trust scoring with temporal decay
- **Fast paths** — ADD_IMPORT, CREATE_FUNCTION, ADD_TEST handlers
- **Repo analysis** — Convention extraction at 300x cheaper than cloud
- **Test-first development** — Contract system with test generation
- **Self-debugging loop** — Decomposition and reflection

### Why Frozen

Code generation with verification genuinely requires more capable reasoning than attention management or shell commands. A 1B model can understand "what should I work on today?" but struggles with "implement OAuth2 with PKCE flow and write comprehensive tests."

We could ship RIVA today with 7-8B models, but that defeats the mission. True democratization means waiting until we can run this on accessible hardware—or proving that CAIRN and ReOS deliver enough value on their own.

### Future Work

When RIVA resumes:
1. Complete Intent verification layer (LLM judge integration)
2. Add FIX_IMPORT fast path handler
3. Explore whether fine-tuned smaller models can handle constrained code tasks
4. Consider hybrid approaches (small model for routing, larger for generation)

---

## Safety: You're Always in Control

**Thesis:** Talking Rock has safety limits that can be tuned but not disabled. You approve every change, and everything runs locally where you can see exactly what's happening.

### Approval Required

- **Preview before changes** — See exactly what will change before any file is modified
- **Explicit approval** — All changes need your OK
- **Automatic backups** — Every modified file is backed up
- **Undo anything** — Rollback any change

### Built-in Limits

| Protection | Default | Tunable Range |
|------------|---------|---------------|
| Max iterations per task | 10 | 3-50 |
| Max run time | 5 minutes | 1-30 minutes |
| Sudo commands per session | 10 | 1-20 |
| Auth attempts (rate limit) | 5/minute | N/A |
| Command max length | 8KB | 1-16KB |

### Privacy by Architecture

Because Talking Rock runs locally:
- **No tracking** — We don't know you exist
- **No data collection** — Your conversations stay on your machine
- **No training** — Your data is never used to train models
- **Open source** — Read every line of code

**This isn't a privacy policy—it's architecture.** There's no server to send data to.

---

## Getting Started

### Quick Install (Experienced Users)

```bash
# 1. Install Ollama (runs AI models locally)
curl -fsSL https://ollama.com/install.sh | sh
ollama pull llama3.2:1b  # Start with 1B for CAIRN

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

Then download a small model:
```bash
ollama pull llama3.2:1b
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

## Is This For You?

Talking Rock is for you if:
- You want an AI assistant that respects your privacy
- You're tired of subscription fatigue
- You want to learn Linux with a patient helper
- You have modest hardware (8GB RAM, no GPU required)
- You believe software should work for users, not advertisers

### Requirements

**Minimum (CAIRN only):**
- Linux (Ubuntu, Fedora, Mint, Arch, etc.)
- Python 3.12+
- 8GB RAM
- 10GB disk space
- No GPU required

**Recommended (CAIRN + ReOS):**
- 16GB RAM
- GPU optional (faster inference)

**Future (RIVA):**
- 16GB+ RAM
- GPU recommended
- 7-8B parameter models

### How It Compares

| Feature | ChatGPT | Copilot | Talking Rock |
|---------|---------|---------|--------------|
| Works offline | No | No | **Yes** |
| Your data stays private | No | No | **Yes** |
| Free forever | No | No | **Yes** |
| Open source | No | No | **Yes** |
| Runs on 8GB RAM | N/A | N/A | **Yes (CAIRN)** |
| Life organization | No | No | **Yes** |
| Linux system control | No | No | **Yes** |

---

## What's Built

### CAIRN (Attention Minder) — Active Development
- [x] The Play hierarchy (Acts → Scenes, 2-tier)
- [x] Smart surfacing ("what needs attention")
- [x] Calendar integration (Thunderbird)
- [x] Contact knowledge graph
- [x] Coherence Kernel for distraction filtering
- [x] 45 MCP tools
- [ ] 1B model optimization and testing

### ReOS (System Agent) — Active Development
- [x] Natural language system control
- [x] Parse Gate with FTS5 search (vector embeddings optional)
- [x] Service, package, container management (apt, dnf, pacman, zypper)
- [x] Docker/Podman container management
- [x] Safety layer with command blocking, rate limiting, audit logging
- [ ] 1-3B model optimization and testing

### RIVA (Code Agent) — Frozen
- [x] 3-layer verification (syntax → semantic → behavioral)
- [ ] Intent verification layer (framework ready, paused)
- [x] Tree-sitter parsing for Python, JavaScript/TypeScript
- [x] Pattern learning with trust scoring
- [x] Fast paths: ADD_IMPORT, CREATE_FUNCTION, ADD_TEST
- [ ] Fast path: FIX_IMPORT (paused)
- [x] Repo analysis with convention extraction
- [x] Test-first development with contract building
- [x] Self-debugging loop
- [x] Git integration

### Infrastructure
- [x] Seamless agent handoffs with approval
- [x] Context preservation across agents
- [x] Automatic backups and undo

---

## Documentation

- [Beginner's Guide](docs/beginners-guide.md) — New to Linux? Start here
- [Technical Roadmap](docs/tech-roadmap.md) — Development plans
- [App Vision](docs/app-vision.md) — What we're building and why
- [CAIRN Architecture](docs/cairn_architecture.md) — Attention minder design
- [Parse Gate Architecture](docs/parse-gate.md) — Context-aware shell proposals
- [Security Design](docs/security.md) — How we protect your system
- [The Play System](docs/the-play.md) — Knowledge organization
- [RIVA Architecture](docs/code_mode_architecture.md) — Code agent design (frozen)

---

## Contributing

Talking Rock is open source (MIT license). We welcome:
- Bug reports and feature requests
- Code contributions (especially CAIRN and ReOS optimization)
- Documentation improvements
- Testing on different Linux distributions
- Small model benchmarking and optimization

See [CONTRIBUTING.md](.github/CONTRIBUTING.md) for guidelines.

**Current focus areas:**
1. CAIRN performance on 1B models
2. ReOS accuracy on 1-3B models
3. Prompt engineering for small models
4. Hardware compatibility testing

---

## License

MIT — Do whatever you want with it.

---

*Talking Rock: Local AI, real ownership, accessible hardware.*
