# Talking Rock Foundation

> **The philosophical and architectural bedrock for Talking Rock's AI assistant system.**

This document describes the core principles and architecture that unify CAIRN, ReOS, and RIVA. For detailed implementation, see the linked specialized documents.

---

## Mission

> **Don't rent a data center. Center your data around you.**

Talking Rock is an AI assistant that runs entirely on your computer. Not a thin client connecting to someone else's servers—the actual AI, running locally, under your control.

**Local inference isn't just about privacy (though you get that too). It's about economics:**

- **Cloud AI costs money per token.** Every verification pass, every repo analysis, every safety check—they all cost the provider money. So they minimize them.
- **Local inference is essentially free.** Once you have the model, compute costs nothing extra. So we can verify every line of code. Analyze every repository. Check every command.

---

## The Kernel Principle

> **"If you can't verify it, decompose it."**

This single recursive rule governs all of Talking Rock's operations. Instead of prescribing complexity levels, levels emerge from recursive application of this constraint:

1. Can you verify this operation directly?
2. If yes → execute and verify
3. If no → decompose into smaller operations and repeat

This principle manifests across all agents:
- **RIVA** decomposes complex coding intentions into verifiable contract steps
- **CAIRN** decomposes complex attention demands into verifiable coherence facets
- **ReOS** decomposes natural language into verifiable shell commands

---

## Atomic Operations Architecture

Every user request is decomposed into **atomic operations**—the smallest meaningful units of work that can be classified, verified, and executed.

### The 3x2x3 Taxonomy

Each atomic operation is classified along three dimensions:

| Dimension | Options | Description |
|-----------|---------|-------------|
| **Destination** | `stream`, `file`, `process` | Where does output go? |
| **Consumer** | `human`, `machine` | Who consumes the result? |
| **Execution Semantics** | `read`, `interpret`, `execute` | What action is taken? |

**Examples:**
- "Show memory usage" → `(stream, human, read)` — display to user
- "Save this to notes.txt" → `(file, human, execute)` — persistent output for human
- "Run pytest" → `(process, machine, execute)` — spawn process for machine verification

See [Atomic Operations](./atomic-operations.md) for the complete taxonomy and classification pipeline.

---

## Agents as Operation Generators

The three agents don't replace atomic operations—they **generate** them:

```
User Request
     │
     ▼
┌──────────────────────────────────────────────────────┐
│                  Agent Layer                          │
│  ┌────────────┐  ┌────────────┐  ┌────────────────┐  │
│  │   CAIRN    │  │    ReOS    │  │     RIVA       │  │
│  │ Attention  │  │   System   │  │     Code       │  │
│  │  Minder    │  │   Helper   │  │    Agent       │  │
│  └─────┬──────┘  └─────┬──────┘  └───────┬────────┘  │
│        │               │                  │           │
│        └───────────────┼──────────────────┘           │
│                        ▼                              │
│            ┌──────────────────────┐                   │
│            │  Atomic Operations   │                   │
│            │  (stream/file/proc)  │                   │
│            │  (human/machine)     │                   │
│            │  (read/interp/exec)  │                   │
│            └──────────────────────┘                   │
└──────────────────────────────────────────────────────┘
                        │
                        ▼
┌──────────────────────────────────────────────────────┐
│              Verification Pipeline                    │
│  Syntax → Semantic → Behavioral → Safety → Intent    │
└──────────────────────────────────────────────────────┘
                        │
                        ▼
┌──────────────────────────────────────────────────────┐
│              Execution + RLHF Feedback               │
└──────────────────────────────────────────────────────┘
```

### CAIRN: The Attention Minder

**Target: 1B parameters.** Surfacing and prioritization are pattern-matching tasks.

CAIRN helps you focus on what matters by:
- Surfacing the **next thing**, not everything
- Filtering through your stated identity (Coherence Kernel)
- Managing calendar/contacts via Thunderbird integration

CAIRN generates operations like:
- `CALENDAR` intents → `(stream, human, read)` for queries
- `PLAY` intents → `(file, human, execute)` for Scene creation

See [CAIRN Architecture](./cairn_architecture.md) for details.

### ReOS: The System Helper

**Target: 1-3B parameters.** Shell commands are constrained and predictable.

ReOS lets you control your Linux system through natural language while never obstructing normal terminal operation.

ReOS generates operations like:
- "what's using memory?" → `(stream, human, read)`
- "stop docker containers" → `(process, machine, execute)`

See [Parse Gate Architecture](./parse-gate.md) for details.

### RIVA: The Code Agent (Frozen)

**Target: 7-8B+ parameters.** Code generation with verification requires more capable reasoning.

RIVA provides test-first, contract-based development with multi-layer verification.

RIVA generates operations like:
- Code edits → `(file, machine, execute)`
- Test runs → `(process, machine, interpret)`

See [RIVA Architecture](./code_mode_architecture.md) for details.

---

## The Verification Pipeline

Every atomic operation passes through five verification layers:

| Layer | Purpose | Example Check |
|-------|---------|---------------|
| **Syntax** | Structurally valid? | Valid bash/Python syntax |
| **Semantic** | Makes logical sense? | File exists before edit |
| **Behavioral** | Expected side effects? | Command produces output |
| **Safety** | Safe to execute? | No dangerous patterns |
| **Intent** | Matches user's goal? | ML intent verification |

See [Verification Layers](./verification-layers.md) for the complete verification system.

---

## Learning from Feedback (RLHF)

Talking Rock learns from user feedback at multiple levels:

| Feedback Type | Signal | Strength |
|---------------|--------|----------|
| **Explicit Rating** | User rates 1-5 | Medium |
| **Correction** | User fixes classification | High |
| **Approval** | User approves/rejects | Medium |
| **Behavioral** | Retry, undo, abandon | High |
| **Long-term** | Persisted, reused, referenced | Highest |

See [RLHF Learning](./rlhf-learning.md) for the complete learning system.

---

## Philosophy: A Mirror, Not a Manager

> Every productivity tool asks: *"How can we capture what this person does?"*
>
> Talking Rock asks: *"How can this person see themselves clearly?"*

### Non-Coercion Principles

1. **Never guilt-trip** — "You haven't touched X in 30 days" → "X is waiting when you're ready"
2. **User decides priority** — System surfaces the need, user sets the number
3. **Defer is valid** — "Not now" is a legitimate response
4. **Completion isn't the only goal** — Some items are ongoing, some get archived unfinished

### Privacy by Architecture

Because Talking Rock runs locally:
- **No tracking** — We don't know you exist
- **No data collection** — Your conversations stay on your machine
- **No training** — Your data is never used to train models
- **Open source** — Read every line of code

**This isn't a privacy policy—it's architecture.** There's no server to send data to.

---

## Two-Tier Simplicity (The Play)

The Play uses a deliberately simple two-tier structure:

| Level | Timeframe | Purpose |
|-------|-----------|---------|
| **Acts** | Months to years | Life narratives |
| **Scenes** | Calendar events | When you're doing things |

**Why just two levels?** To remove the temptation to obscure responsibility in complexity.

See [The Play](./the-play.md) for the complete organizational system.

---

## Foundation Documents

| Document | Content |
|----------|---------|
| [Atomic Operations](./atomic-operations.md) | 3x2x3 taxonomy and classification pipeline |
| [Verification Layers](./verification-layers.md) | 5-layer verification system |
| [RLHF Learning](./rlhf-learning.md) | Feedback collection and learning loop |
| [Memory System](./memory-system.md) | Hybrid vector-graph memory for relational recall |
| [Classification](./classification.md) | LLM-native classification with few-shot learning |
| [Execution Engine](./execution-engine.md) | Safe execution with undo capability |

## Agent Documentation

| Document | Agent |
|----------|-------|
| [CAIRN Architecture](./cairn_architecture.md) | Attention minder |
| [Parse Gate](./parse-gate.md) | ReOS system helper |
| [RIVA Architecture](./code_mode_architecture.md) | Code agent (frozen) |
| [The Play](./the-play.md) | Life organization |

## Reference Documentation

| Document | Content |
|----------|---------|
| [Blocks API](./blocks-api.md) | Block-based content system |
| [Security](./security.md) | Safety limits and protections |
| [Testing Strategy](./testing-strategy.md) | Test approach |

---

*Talking Rock: Local AI, real ownership, accessible hardware.*
