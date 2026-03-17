# Plan: Conversational Shell — A Proactive, Atomic-Ops-Driven Terminal Mode

## Context

### What Exists Today

The current ReOS experience inside the Cairn Tauri app (`reosView.ts`) is a split-screen layout:
- **Left:** System dashboard polling `reos/vitals` every 5 seconds
- **Right:** Full PTY terminal (xterm.js + Rust `portable-pty`) with _reactive_ NL interception

The reactive interception model works as follows: the user types something the shell does not recognize, bash emits a "command not found" error, ReOS detects that in the PTY output stream, calls `reos/propose`, and injects the LLM response inline using ANSI sequences. The user then approves with `Y` and the command is run via the PTY.

This mode was deliberately designed to be invisible — the shell behaves as a normal Linux shell, and ReOS enhances it only when the shell fails. From `reos.md` (2026-03-16): "DESIGN DECISION: Reactive only. Shell works as Linux intends. ReOS never intercepts input before the PTY."

### Why a Second Mode Is Needed

The reactive model serves users who know Linux and want occasional assistance. It does not serve users who want to say "help me free up disk space" and have ReOS guide them through a multi-step diagnostic and remediation flow. For that workflow, the model is backwards: rather than the shell prompting NL assistance on failure, the user wants to start from NL and have the system propose commands.

The proposed conversational shell is a _complementary_ mode, not a replacement. It answers a different question:
- PTY terminal: "I know Linux; enhance me when I fail."
- Conversational shell: "Help me figure out what to do."

### How This Fits the Talking Rock Philosophy

Cairn's atomic ops architecture (3x2x3 taxonomy: destination × consumer × semantics) classifies every request before acting on it. The verification pipeline ensures no side-effecting operation executes without intent matching. The "Foreign until confirmed" principle from `shell_propose.py` — proposals are never self-executing — extends naturally to a multi-turn conversational loop. The conversational shell is the full realization of this pipeline as a user-facing experience rather than a background mechanism.

---

## Approach (Recommended): Inline Conversational Mode via xterm.js Custom Renderer

The conversational shell is implemented as a **second tab within the ReOS view** — a sibling to the PTY terminal, not a replacement. Both tabs are always available. The user switches between them via a tab bar at the top of the right panel.

The conversational shell renders in a **custom DOM-based renderer** rather than xterm.js. This is a deliberate choice explained in the alternatives section. The prompt experience mimics a shell visually (dark background, monospace font, prompt sigil, input line) but is rendered as styled `div` elements with a genuine `<input>` element for text entry.

### Why This Is the Right Approach

1. **Tab-based coexistence with the PTY is the lowest-risk architecture.** The PTY and the conversational shell share no state, share no event streams, and share no rendering layer. Introducing the conversational shell cannot break the PTY.

2. **A custom DOM renderer is simpler than abusing xterm.js.** xterm.js is designed for ANSI/VT100 output streams. The conversational shell needs rich cards with approve/reject buttons, expandable command explanations, and structured multi-step flows. Implementing those in xterm.js ANSI sequences is the wrong abstraction and produces worse UX.

3. **The existing `propose_command_with_trace()` pipeline is reusable.** The backend can extend `shell_propose.py` with a conversation-aware variant that carries history context. The frontend calls the same RPC endpoint family.

4. **Atomic ops drives the loop naturally.** Each user turn becomes an `AtomicOperation`. The classification (semantics=`interpret` → ask clarifying questions; semantics=`read` → execute safely; semantics=`execute` → propose and gate) determines what the UI renders. The pipeline already knows how to handle clarification round-trips via `needs_clarification` and `clarification_prompt`.

---

## Alternatives Considered

### Alternative A: Proactive xterm.js Interception

The conversational shell is implemented by making the PTY terminal mode proactive: _all_ user input is intercepted before reaching the PTY, every keystroke goes to the LLM pipeline, and bash is never invoked unless the user explicitly approves a command.

**Assessment:** High risk, high complexity. This would require rewriting the PTY input handling, defeating the purpose of having a PTY at all for the conversational mode. It conflates two fundamentally different UX modes. Rejected in the Phase 3 design decision (2026-03-16) for the reactive PTY, and those reasons apply here as well. The existing PTY investment (Rust `pty.rs`, xterm.js, FitAddon, ResizeObserver) would be partially wasted if we then intercept all input before it reaches the PTY.

### Alternative B: Separate Tauri Window

The conversational shell opens in a separate Tauri window (like `playWindow.ts`), completely decoupled from the ReOS view.

**Assessment:** Logical isolation is clean, but the UX is fragmented. The user has to manage two windows for system work. The system dashboard (left panel) should be shared context for both the PTY and the conversational shell. Tab-based coexistence in the right panel is better: both modes see the same dashboard, same vitals, same context.

### Alternative C: Chat-style UI (Cairn-like)

The conversational shell is modeled after `cairnView.ts` — a scrollable message history with an input box, no shell aesthetic.

**Assessment:** Technically easy (the pattern already exists) but loses the terminal aesthetic that signals "this thing runs commands." The shell visual — prompt sigil, monospace font, command output blocks — is meaningful UX communication. Users understand a shell prompt means "this will do something to your system." A generic chat UI blurs that signal. Rejected on UX grounds.

---

## Data Flow

```
User types at prompt → [Enter]
         │
         ▼
  ConversationManager (frontend)
  - Appends turn to local history
  - Renders user turn in the scroll buffer
         │
         ▼
  reos/converse RPC call
  - natural_language: str
  - conversation_id: str
  - turn_history: list[{role, content}]
  - system_context: ShellContextSummary  (distro, pkg_mgr, service_count)
         │
         ▼
  Backend: ConversationalShellHandler
         │
         ├──► 1. AtomicOpsProcessor.process_request()
         │        - classifies into 3×2×3
         │        - decomposes if needed
         │        - returns ProcessingResult (may have needs_clarification)
         │
         ├──► 2. VerificationPipeline.verify()
         │        - FAST mode for READ/INTERPRET/STREAM
         │        - STANDARD mode for all EXECUTE operations
         │        - FULL mode for sudo / destructive commands
         │
         ├──► 3. CommandGenerator (new)
         │        - takes AtomicOperation + turn_history + system context
         │        - calls propose_command_with_trace() if semantics=execute
         │        - returns ConversationalTurn
         │
         └──► Returns ConversationalTurnResult
                  - turn_type: "clarify" | "inform" | "propose" | "danger" | "refuse"
                  - message: str
                  - command: str | None
                  - explanation: str | None
                  - is_risky: bool
                  - risk_reason: str | None
                  - operation_id: str  (for approval tracking)
                  - classification: dict  (for debug display)
         │
         ▼
  Frontend: renders the turn
  ┌─────────────────────────────────────────────────────┐
  │ turn_type=clarify  → grey info block, no command    │
  │ turn_type=inform   → grey info block, no command    │
  │ turn_type=propose  → command card with Y/N/edit     │
  │ turn_type=danger   → red warning card, Y/N/abort    │
  │ turn_type=refuse   → red block, no approval option  │
  └─────────────────────────────────────────────────────┘
         │
         ▼ (if user approves)
  reos/execute RPC call
  - operation_id: str
  - command: str (as displayed, user may have edited)
         │
         ▼
  Backend: executes via subprocess (NOT PTY)
  - OperationExecutor._execute_process()
  - captures stdout/stderr/exit_code
  - returns ExecutionResult
         │
         ▼
  Frontend: renders output block in scroll buffer
  - exit code indicator
  - stdout/stderr with syntax awareness
  - "copy command" / "copy output" affordances
```

---

## How Atomic Ops Drives the Conversation Loop

The 3×2×3 classification directly controls the turn type rendered in the UI:

| Classification | Turn Type | Behavior |
|---|---|---|
| `stream / human / interpret` | `inform` | Pure conversational response, no command proposed |
| `stream / human / read` | `inform` or `propose` | Safe command proposal, auto-executed after single confirm |
| `process / machine / read` | `propose` | Diagnostic command (ps, df, ls), propose with explanation |
| `process / human / execute` | `propose` | Standard command proposal with Y/N gate |
| `process / machine / execute` | `danger` | Script/pipe execution, red card with explicit risk note |
| `file / human / execute` | `propose` or `danger` | File mutation, checks if destructive |
| Not confident | `clarify` | LLM asks a clarifying question, loop continues |

The `needs_clarification` flag from `AtomicDecomposer` maps directly to the `clarify` turn type. When the decomposer cannot resolve intent from context, it returns a `clarification_prompt` string. The frontend renders this as a system message and the next user input is routed through `_handle_clarification_response()` — the existing Cairn mechanism — before the loop continues.

Multi-step flows (e.g., "free up disk space") produce decomposed operations. Each child operation is presented as a sequential proposal card. The user approves them one at a time. The parent operation tracks overall completion.

---

## Conversation State (What Is Maintained Across Turns)

### Frontend State (in-memory, per session)

```typescript
interface ConversationState {
  conversationId: string;          // UUID for this session
  turns: ConversationTurn[];       // full history for context window
  pendingOperationId: string | null; // operation awaiting approval
  pendingCommand: string | null;   // command awaiting approval
  systemContext: SystemContextSummary; // distro, pkg_mgr, etc. (refreshed on start)
}

interface ConversationTurn {
  role: 'user' | 'assistant' | 'system';
  content: string;
  command?: string;
  commandOutput?: CommandOutputBlock;
  turnType?: 'clarify' | 'inform' | 'propose' | 'danger' | 'refuse';
  timestamp: number;
}
```

The `turns` array is passed to the backend on each RPC call (last N turns, bounded). This provides the conversation history the LLM needs to resolve contextual references ("that service", "the log file from before").

### Backend State (per-call, no session store)

The backend is _stateless across calls_. All conversation history is passed in from the frontend on each request. This avoids session state management on the Python side and keeps the RPC handler simple.

The atomic ops store (SQLite) tracks `AtomicOperation` records for audit and undo. Operations created during the conversational shell session are tagged `source_agent="reos"`.

### What Is NOT Maintained

- No persistent conversation history between application restarts (unlike Cairn's compression pipeline)
- No semantic memory extraction from the conversational shell (the session is ephemeral system work, not life context)
- No RLHF feedback loop in Phase 1 (added in Phase 3)

This is intentional. The conversational shell is a task-oriented session tool, not a life management system. Cairn owns persistent memory; ReOS owns transient system work.

---

## Frontend Design

### Tab Bar

The right panel of the ReOS view acquires a tab bar above xterm.js:

```
[ Terminal ]  [ Conversational ]
```

Both tabs share the left dashboard panel. Switching tabs does not stop/start the PTY — the PTY remains running in the background when the Conversational tab is active (so long-running commands aren't interrupted by an accidental tab switch).

### Conversational Shell Renderer

The conversational shell is a `div`-based scroll buffer with a sticky input row at the bottom. No xterm.js is used for this panel.

```
┌─────────────────────────────────────────────────────────┐
│  reos@hostname:~$  [dark header bar]                    │
├─────────────────────────────────────────────────────────┤
│  Scroll buffer                                          │
│                                                         │
│  > free up disk space                                   │ ← user turn
│                                                         │
│  Your / filesystem is 87% full. Let me check what's    │ ← inform turn
│  consuming the most space.                              │
│                                                         │
│  ┌─────────────────────────────────────────────────┐   │ ← propose card
│  │  du -sh /* 2>/dev/null | sort -rh | head -20    │   │
│  │  Shows top-level directories sorted by size.    │   │
│  │  [Run]  [Edit]  [Skip]                          │   │
│  └─────────────────────────────────────────────────┘   │
│                                                         │
│  $ du -sh /* 2>/dev/null | sort -rh | head -20         │ ← output block
│  ─────────────────────────────────────────────────      │
│  35G    /home                                           │
│  12G    /usr                                            │
│  ...                                                    │
│                                                         │
│  Based on this, /home is the primary consumer.          │ ← inform turn
│  Want me to look deeper into /home?                     │
│                                                         │
├─────────────────────────────────────────────────────────┤
│  reos@hostname:~$ ▌                           [↑] [↓]  │ ← input row
└─────────────────────────────────────────────────────────┘
```

**Visual conventions (matching existing reosView.ts aesthetic):**
- Background: `rgba(0,0,0,0.9)` — dark, terminal-like
- Font: `JetBrains Mono, monospace` — same as xterm.js PTY
- User turns: dim prefix `>` + white text
- Assistant turns: no prefix, `rgba(255,255,255,0.7)` — visually distinguished
- Command cards: `rgba(255,255,255,0.04)` background, `1px solid rgba(255,255,255,0.08)` border
- Danger cards: `rgba(239,68,68,0.1)` background, red border — matches `percentColor()` red
- Output blocks: `rgba(0,0,0,0.3)` background, monospace, scrollable up to max height
- Exit code indicator: green dot (0) or red dot (non-0) before the command

**Command card interaction:**
- `[Run]` — calls `reos/execute`, streams output into an output block below the card
- `[Edit]` — makes the command text editable in-place before running
- `[Skip]` — marks the operation as rejected, continues conversation
- Keyboard shortcut: `y` / `n` when a card is the "active" card (most recent)

**Input row:**
- Standard `<input type="text">` element
- `[↑]` / `[↓]` buttons cycle through turn history (session-local)
- No readline (PTY terminal owns that experience)

### TypeScript Module

New file: `/home/kellogg/dev/Cairn/apps/cairn-tauri/src/reosConversationalView.ts`

Exports a factory function parallel to `createReosView`:

```typescript
export function createConversationalShell(callbacks: ReosConversationalCallbacks): {
  container: HTMLElement;
  activate: () => void;
  deactivate: () => void;
}
```

The `reosView.ts` is modified to add the tab bar and instantiate `createConversationalShell` alongside the existing PTY terminal.

---

## Backend Architecture

### New RPC Endpoints

#### `reos/converse`

The primary turn endpoint. Called on every user input.

```python
def handle_reos_converse(
    db: Any = None,
    *,
    natural_language: str,
    conversation_id: str,
    turn_history: list[dict],  # [{role, content}, ...]
    system_context: dict,      # {distro, package_manager, active_service_count}
) -> dict[str, Any]:
    """
    Returns:
        turn_type: "clarify" | "inform" | "propose" | "danger" | "refuse"
        message: str
        command: str | None
        explanation: str | None
        is_risky: bool
        risk_reason: str | None
        operation_id: str
        classification: dict  # {destination, consumer, semantics, domain, confident}
        latency_ms: int
    """
```

**Implementation path:**

1. Build `memory_context` string from `turn_history` (last 5 turns formatted as dialogue)
2. Call `AtomicOpsProcessor.process_request(natural_language, user_id="reos", source_agent="reos", memory_context=memory_context)`
3. If `needs_clarification`: return `turn_type="clarify"`, `message=clarification_prompt`
4. Run `VerificationPipeline.verify()` — mode determined by classification semantics
5. If verification failed (blocked pattern): return `turn_type="refuse"`
6. If semantics is `interpret` / domain is `conversation`: call `propose_command_with_trace()` for context but may return a pure conversational response (no command)
7. If semantics is `execute` or `read` with `destination=process`: call `propose_command_with_trace()` to generate the command
8. Apply soft-risky patterns from `_SOFT_RISKY_PATTERNS` (already in `rpc_handlers/propose.py`)
9. Determine `turn_type` from classification + risky flags
10. Return the structured result

The `conversation_id` is used to tag `AtomicOperation` records. It is not used for server-side session state.

#### `reos/execute`

Executes an approved command.

```python
def handle_reos_execute(
    db: Any = None,
    *,
    operation_id: str,
    command: str,
    conversation_id: str,
) -> dict[str, Any]:
    """
    Returns:
        success: bool
        exit_code: int | None
        stdout: str
        stderr: str
        duration_ms: int
        truncated: bool  # True if output was capped
    """
```

**Implementation path:**

1. Safety re-check: `is_safe_command(command)` — re-validate even on approved commands (defense in depth)
2. Call `OperationExecutor._execute_process()` with `ExecutionContext(user_id="reos", approved=True)`
3. Capture stdout/stderr, truncate at 50KB
4. Update `AtomicOperation` status to COMPLETE or FAILED
5. Return `ExecutionResult` fields

The executor already handles subprocess management, timeout (30s default), and output truncation (1MB cap in `executor.py`; we use a lower 50KB cap for conversational display). This is all existing infrastructure.

#### `reos/converse/abort`

Clears a pending operation without executing it.

```python
def handle_reos_converse_abort(
    db: Any = None,
    *,
    operation_id: str,
) -> dict[str, Any]:
    # Updates operation status to FAILED, returns {"aborted": True}
```

### New Python Module

`/home/kellogg/dev/ReOS/src/reos/rpc_handlers/converse.py`

Contains `handle_reos_converse`, `handle_reos_execute`, `handle_reos_converse_abort`.

This module imports from:
- `reos.shell_propose` — `propose_command_with_trace()`, `is_safe_command()`, `_SOFT_RISKY_PATTERNS` (or re-export)
- `reos.shell_context` — `get_context_for_proposal()`
- `trcore.atomic_ops.processor` — `AtomicOpsProcessor`
- `trcore.atomic_ops.verifiers.pipeline` — `VerificationPipeline`, `VerificationMode`
- `trcore.atomic_ops.executor` — `OperationExecutor`, `ExecutionContext`
- `trcore.providers` — `get_provider()`
- `trcore.db` — `get_db()`

### Registration

The new handlers must be registered in Cairn's RPC dispatch table. The exact registration point depends on how ReOS RPC handlers are registered in `src/cairn/ui_rpc_server.py` (the same mechanism that registers `reos/propose` and `reos/vitals`).

---

## Integration with Existing ReOS Code

### `shell_propose.py` — Reused As-Is

`propose_command_with_trace()` is already the correct interface. It takes a `natural_language` string, returns a `ProposalTrace` with `message`, `command`, `model_name`, `latency_ms`. The conversational shell calls this function after the atomic ops classification determines a command should be proposed.

The only gap: `propose_command_with_trace()` has no awareness of conversation history. The multi-turn context is injected at the prompt level. The `CONVERSATIONAL_PROMPT` in `shell_propose.py` should be extended with an optional `conversation_context` parameter (injected as a prefix to the `user_prompt`). This is a backward-compatible addition.

### `shell_context.py` — Reused With Extension

`get_context_for_proposal()` is called for every turn where a command is proposed. The `ShellContext` it returns is useful for command generation accuracy (is nginx installed? is the service running?).

The `system_context` dict passed from the frontend (`{distro, package_manager, active_service_count}`) supplements this. For turns where we do not need full package/service lookup (e.g., "explain what this error means"), context gathering can be skipped.

### `linux_tools.py` — Execution Layer

`OperationExecutor._execute_process()` from `atomic_ops/executor.py` calls `subprocess.Popen` with the command. This is the right execution layer — it has timeout handling, output size limits, safety re-checking via `is_command_safe()`, and state capture.

The conversational shell does NOT use the PTY for execution. Commands run in a subprocess with captured output, not in a terminal emulator. This is correct: the conversational shell is about reviewing what commands do; the PTY is about interactive programs that need a terminal.

### Atomic Ops Pipeline — Source Agent Tag

All `AtomicOperation` records created during conversational shell sessions use `source_agent="reos"`. This distinguishes them from Cairn operations (`source_agent="cairn"`) in the audit log. The `OperationStatus` lifecycle works identically.

---

## Safety Model

### Auto-Approved (no user interaction)

- `stream / human / read` AND `classification.confident = True` — pure informational responses
- `stream / human / interpret` — conversational turns, greetings, clarifications
- READ operations on `destination=process` that match safe diagnostic patterns (ps, df, ls, cat, grep, top, free, uname, uptime, systemctl status, journalctl, lsof)

The safety verifier's existing `BLOCKED_PATTERNS` and `DANGEROUS_PATTERNS` lists (in `verifiers/safety.py`) define the boundary. READ-only commands that hit no dangerous pattern auto-execute with the output shown.

### Requires Single Confirmation (propose card with [Run])

- `process / * / execute` — any process execution
- `file / * / execute` — any file mutation
- All commands hitting `_SOFT_RISKY_PATTERNS` (sudo, rm -rf, dd, chmod 777, curl|sh, systemctl stop/disable, apt remove)
- Any command where `classification.confident = False`

A single `[Run]` click or `y` keystroke is sufficient for this tier.

### Requires Explicit Acknowledgment (danger card)

Commands hitting `DANGEROUS_PATTERNS` in `safety.py` that are not in `BLOCKED_PATTERNS`. These include: `rm -rf`, `sudo rm`, writes to `/etc/`, `crontab`, `systemctl disable/mask/stop`, `kill -9`, `killall`, `pkill`, `reboot/shutdown`, `iptables`, `useradd/userdel`, `visudo`.

The danger card renders in red, shows the specific risk reason, and requires an explicit `[I understand, run anyway]` button (not a `y` keystroke — must be a deliberate click).

### Hard Refused (no execution path)

Commands matching `BLOCKED_PATTERNS` in `safety.py`: `rm -rf /`, fork bombs, writes to block devices, `mkfs`, `fdisk`, `curl|sh`, eval with variable expansion.

The `turn_type="refuse"` renders a red block explaining what was blocked and why. No execution path exists.

### Graceful Conversation for Dangerous Intent

When a user expresses dangerous intent ("delete everything on my home directory") but hasn't formed it into a specific command yet, the classifier returns semantics=`execute` with low confidence. The system proposes a clarifying question rather than immediately generating a dangerous command. The atomic ops decomposer's `needs_clarification` flag handles this path — it surfaces before a command is ever generated.

---

## Graceful Degradation for Smaller Models

The system must degrade gracefully when running on smaller models (7B vs 13B vs 34B). Several mechanisms already exist; this plan extends them.

### Classification Fallback

`AtomicClassifier._fallback_classify()` provides keyword-based classification when the LLM is unavailable or fails. It always returns `confident=False`, which routes to the `propose` tier (requires confirmation) rather than auto-execution. This is correct: smaller models get more gates, not fewer.

### Command Generation Degradation

`propose_command_with_trace()` already has a two-attempt strategy:
1. `CONVERSATIONAL_PROMPT` at temperature 0.3 — natural language response + optional `COMMAND:` sentinel
2. `CONSTRAINED_FALLBACK_PROMPT` at temperature 0.1 — forces a single command output

On small models, Attempt 1 often produces garbage. Attempt 2 recovers. The conversational shell benefits from this automatically.

### Clarification Loop for Ambiguous Input

When a small model cannot confidently classify input, `needs_clarification=True` is returned and the system asks a clarifying question. On large models, many requests are classified confidently. On small models, more questions are asked. This is a natural degradation — the conversation gets longer but remains correct.

### Verification Mode Adjustment

On small models, the intent verification layer (FULL mode) is less reliable. The system should default to `STANDARD` verification mode (no LLM intent layer) for small models, upgrading to `FULL` only when the model is known to be capable. The model name from `model_name = getattr(llm, "current_model", None)` can be used to make this determination.

A simple heuristic: if the model name contains "7b", "8b", or "3b" (case-insensitive), use `STANDARD`. Otherwise use `FULL`. This is configurable and can be overridden.

---

## Implementation Phases

### Phase 1: Backend Foundation (no UI change)

**Goal:** New RPC endpoints working and testable via curl/Python.

**Steps:**
1. Create `/home/kellogg/dev/ReOS/src/reos/rpc_handlers/converse.py` with `handle_reos_converse`, `handle_reos_execute`, `handle_reos_converse_abort`
2. Register the three handlers in Cairn's RPC dispatch table (same mechanism as `reos/propose`)
3. Extend `CONVERSATIONAL_PROMPT` in `shell_propose.py` to accept an optional `conversation_context` string injected before the user prompt (backward-compatible — empty string leaves behavior unchanged)
4. Add a `conversation_context` parameter to `propose_command_with_trace()` (pass-through to prompt)
5. Write unit tests: `tests/test_converse_handler.py` covering each `turn_type` return value
6. Write integration test that runs a two-turn conversation: initial vague request → clarify turn → specific request → propose turn

**Files affected:**
- CREATE: `src/reos/rpc_handlers/converse.py`
- MODIFY: `src/reos/shell_propose.py` (add `conversation_context` param)
- MODIFY: Cairn's RPC dispatch registration (location TBD from `ui_rpc_server.py` inspection)
- CREATE: `tests/test_converse_handler.py`

**Confidence check:** This phase requires no frontend work and no changes to the atomic ops pipeline itself. All components already exist. Risk is low.

### Phase 2: Frontend Shell Renderer

**Goal:** Conversational shell renders and sends/receives turns. No command execution yet.

**Steps:**
1. Create `/home/kellogg/dev/Cairn/apps/cairn-tauri/src/reosConversationalView.ts`
   - Scroll buffer DOM structure
   - Input row with `<input>` element
   - Turn renderers for each `turn_type` (clarify, inform, propose, danger, refuse)
   - Command card with [Run] / [Edit] / [Skip] buttons (Run calls `reos/execute`, not yet wired)
   - Pending/loading state while awaiting RPC response
2. Modify `reosView.ts`:
   - Add a tab bar above the xterm.js container
   - Instantiate `createConversationalShell`
   - Wire tab switching (PTY continues running when Conversational is active)
3. Add TypeScript types to `types.ts`:
   - `ReosConverseResult`
   - `ReosExecuteResult`
   - `ConversationTurn`

**Files affected:**
- CREATE: `apps/cairn-tauri/src/reosConversationalView.ts`
- MODIFY: `apps/cairn-tauri/src/reosView.ts` (tab bar, instantiation)
- MODIFY: `apps/cairn-tauri/src/types.ts` (new types)

### Phase 3: Command Execution and Output Display

**Goal:** Full loop: turn → propose → approve → execute → output.

**Steps:**
1. Wire `[Run]` button to `reos/execute` RPC call
2. Render `ExecutionResult` as an output block below the command card
3. Wire `[Edit]` to in-place command editing before submit
4. Wire `[Skip]` to `reos/converse/abort`
5. Keyboard shortcuts: `y` for approve, `n` for skip, when a proposal card is the latest rendered element
6. Exit code indicator (green/red dot)
7. Output truncation notice when `truncated=true`

**Files affected:**
- MODIFY: `apps/cairn-tauri/src/reosConversationalView.ts`

### Phase 4: Multi-Turn Context and Polish

**Goal:** Conversation feels coherent across multiple turns; system context is used.

**Steps:**
1. Pass `turn_history` (last 8 turns, capped) to `reos/converse` on each call
2. Pass `system_context` from the vitals dashboard to `reos/converse`
3. Implement session-local turn history navigation (`[↑]` / `[↓]` in input)
4. "New conversation" button: clears the scroll buffer, generates new `conversation_id`
5. Scroll-to-bottom behavior on new turns
6. Copy affordances: "copy command" (copies command text) and "copy output" (copies stdout)
7. Classification debug display: small dimmed text showing `{destination}/{consumer}/{semantics}` per turn (toggled off by default, enabled via a debug flag in localStorage)

**Files affected:**
- MODIFY: `apps/cairn-tauri/src/reosConversationalView.ts`
- MODIFY: `src/reos/rpc_handlers/converse.py` (consume `system_context`, `turn_history`)

### Phase 5: RLHF Feedback and Telemetry

**Goal:** Capture user corrections and approval/rejection data for classifier improvement.

**Steps:**
1. Add thumbs up/down to non-command turns (feedback on conversational quality)
2. Record command approvals/rejections via `trcore.atomic_ops.feedback.FeedbackCollector`
3. Add telemetry events to conversational shell (turn_submitted, turn_rendered, command_approved, command_rejected, command_executed) using the existing `reos/telemetry/event` endpoint
4. Wire `record_user_correction()` on the CairnAtomicBridge if the user edits a command before running it (the edit represents a correction to the proposed command)

**Files affected:**
- MODIFY: `apps/cairn-tauri/src/reosConversationalView.ts`
- MODIFY: `src/reos/rpc_handlers/converse.py`

---

## Files Affected

### New Files

| File | Purpose |
|------|---------|
| `/home/kellogg/dev/ReOS/src/reos/rpc_handlers/converse.py` | Three RPC handlers: converse, execute, abort |
| `/home/kellogg/dev/Cairn/apps/cairn-tauri/src/reosConversationalView.ts` | Frontend renderer for conversational shell |
| `/home/kellogg/dev/ReOS/tests/test_converse_handler.py` | Unit + integration tests for converse handlers |

### Modified Files

| File | Change |
|------|--------|
| `/home/kellogg/dev/ReOS/src/reos/shell_propose.py` | Add `conversation_context` param to `propose_command_with_trace()`, extend `CONVERSATIONAL_PROMPT` |
| `/home/kellogg/dev/Cairn/apps/cairn-tauri/src/reosView.ts` | Add tab bar, instantiate `createConversationalShell`, wire tab switching |
| `/home/kellogg/dev/Cairn/apps/cairn-tauri/src/types.ts` | Add `ReosConverseResult`, `ReosExecuteResult`, `ConversationTurn` |
| Cairn RPC dispatch (location: `src/cairn/ui_rpc_server.py` or equivalent) | Register `reos/converse`, `reos/execute`, `reos/converse/abort` |

### Unmodified (Intentionally)

| File | Reason |
|------|--------|
| `src/cairn/atomic_ops/processor.py` | Used as-is; `process_request()` already does what we need |
| `src/cairn/atomic_ops/verifiers/safety.py` | Existing `BLOCKED_PATTERNS` / `DANGEROUS_PATTERNS` used directly |
| `src/cairn/atomic_ops/executor.py` | `OperationExecutor._execute_process()` handles subprocess execution |
| `src/reos/shell_context.py` | `get_context_for_proposal()` called without modification |
| `src/reos/rpc_handlers/propose.py` | Existing reactive PTY pipeline untouched |
| Rust `pty.rs` | PTY unchanged; conversational shell does not use it |

---

## Risks and Mitigations

### Risk 1: Atomic Ops Processor Not Thread-Safe in Concurrent Sessions

The `AtomicOpsProcessor` uses a SQLite connection passed in at construction. If multiple Tauri sessions (future feature) call `reos/converse` concurrently, shared connections could conflict.

**Mitigation:** Cairn's existing RPC server is single-threaded (stdio JSON-RPC). One request at a time. This is not an issue in practice today. Note it as a constraint for future multi-session work.

### Risk 2: Safety Verifier Pattern Matching on NL Input vs Shell Command

The `SafetyVerifier` checks `operation.user_request` — the natural language input, not the generated command. If the user says "delete everything in /tmp" (benign intent phrased ambiguously), the verifier might pattern-match on `delete` + `/tmp` and flag it. If the user says something innocuous that happens to contain `rm` in a different context, it might miss it.

**Mitigation:** The safety verifier's purpose at the NL stage is to catch social engineering (someone trying to trick ReOS into generating dangerous commands). The _generated command_ goes through a second safety check in `OperationExecutor._execute_process()` via `is_command_safe()` before execution. Defense in depth: two independent checks on two different inputs (NL + generated command). Document this explicitly in code comments.

### Risk 3: Conversation History Grows the Context Window

Passing all turn history to the backend on each call risks exceeding the LLM context window on long sessions. With a 7B model at 4K context (common), a 20-turn conversation with substantial output blocks could truncate.

**Mitigation:** Cap `turn_history` at 8 turns (4 user + 4 assistant). Summarize older turns into a single "prior context" string if history exceeds 8 turns. Phase 1 uses a hard cap of 8; summarization is Phase 4.

### Risk 4: subprocess Execution Without a Terminal

Some commands assume a TTY (interactive prompts, ncurses UIs). Running them in a captured subprocess fails silently or produces garbage output.

**Mitigation:** The conversational shell is not a PTY. Commands that need a TTY (vim, htop, less, sudo with interactive prompts) will fail. The system should detect this class of command and inform the user: "This command requires an interactive terminal. Switch to the Terminal tab and run it there." A heuristic list of TTY-requiring commands is maintained in `converse.py` and returned as `turn_type="inform"` with a redirect message rather than `turn_type="propose"`.

### Risk 5: xterm.js Tab vs Conversational Tab Visual Consistency

The existing PTY terminal uses xterm.js with GitHub-dark theme and specific font settings. The new conversational shell is DOM-rendered. Visual inconsistency between the two tabs could feel jarring.

**Mitigation:** Use the same font (`JetBrains Mono, monospace`), same background color scheme (`rgba(0,0,0,0.9)`), and same color palette (`rgba(255,255,255,*)` opacity ladder) that `reosView.ts` already establishes. The tab bar matches the existing `reosView.ts` panel header style. Code review for visual consistency before Phase 2 ships.

### Risk 6: Atomic Ops Store Growing Without Bound

Every conversational turn that generates an `AtomicOperation` writes a record. Long conversational sessions generate many operations.

**Mitigation:** Operations tagged `source_agent="reos"` can be pruned on a TTL (e.g., 7 days). This is existing infrastructure — add the prune call on conversational shell session start. In Phase 1, no pruning; add it in Phase 4.

### Risk 7: `_SOFT_RISKY_PATTERNS` Duplication

`_SOFT_RISKY_PATTERNS` is defined inside `rpc_handlers/propose.py` as a module-level list. The new `converse.py` needs the same list. Copying it creates a maintenance hazard (one gets updated, the other doesn't).

**Mitigation:** Move `_SOFT_RISKY_PATTERNS` to `reos/shell_propose.py` as a public export (`SOFT_RISKY_PATTERNS`). Both `propose.py` and `converse.py` import from there. This is a two-line refactor.

---

## Testing Strategy

### Unit Tests (`tests/test_converse_handler.py`)

Each function is tested with a mock LLM provider that returns deterministic JSON responses.

**Test cases required:**

| Test | Input | Expected turn_type |
|------|-------|-------------------|
| Greeting | "hello" | `inform` |
| Safe diagnostic | "show disk usage" | `propose` (safe command) |
| Ambiguous vague input | "fix my computer" | `clarify` |
| Blocked command | "delete root filesystem" | `refuse` |
| Dangerous command | "force-kill all processes" | `danger` |
| File mutation | "remove all log files" | `propose` or `danger` |
| Multi-turn clarification | Turn 1 vague → Turn 2 specific | first=`clarify`, second=`propose` |
| LLM failure | LLM raises exception | graceful fallback (inform with error) |
| Execution happy path | valid command + `reos/execute` call | success=True, stdout captured |
| Execution timeout | slow command (30s cap) | success=False, stderr="timed out" |

### Integration Tests

A slow test (`@pytest.mark.slow`) that requires a running Ollama instance:

```python
def test_conversational_turn_end_to_end():
    # Send "show memory usage" through the full pipeline
    # Verify: turn_type="propose", command contains "free" or "cat /proc/meminfo"
    # Approve: call handle_reos_execute with the proposed command
    # Verify: success=True, stdout is non-empty
```

### Manual Verification Checklist (for Phase 2 sign-off)

- [ ] Tab switching does not kill the PTY session
- [ ] PTY terminal continues to work while Conversational tab is active
- [ ] "hello" returns an informational response, no command card
- [ ] "show disk usage" returns a propose card with a safe diagnostic command
- [ ] Running the command shows output block with exit code indicator
- [ ] Editing a command before running: the edited command runs, not the original
- [ ] Skipping a proposal: conversation continues, not frozen
- [ ] Danger-tier command (e.g., "stop nginx") renders red card
- [ ] Hard-blocked command (e.g., "delete root") renders refuse block with no Run button
- [ ] New conversation button clears the buffer and resets history

---

## Definition of Done

- [ ] `reos/converse`, `reos/execute`, `reos/converse/abort` RPC endpoints exist and are registered
- [ ] All three handlers have unit tests covering happy path and failure paths
- [ ] End-to-end integration test passes against a running Ollama instance
- [ ] Conversational shell tab appears in the ReOS view without visual regression to the PTY tab
- [ ] PTY terminal works normally when the Conversational tab is active
- [ ] All five `turn_type` variants render correctly in the frontend
- [ ] Dangerous commands hit the danger card; blocked commands hit the refuse block
- [ ] Command execution via subprocess runs correctly and captures output
- [ ] `SOFT_RISKY_PATTERNS` moved to `shell_propose.py` and imported in both handlers
- [ ] No existing ReOS tests broken (test suite passes: 316+ tests, same ignore list)
- [ ] `conversation_context` parameter in `propose_command_with_trace()` is backward-compatible (empty string = original behavior)
- [ ] Plan document updated in `reos.md` memory file after implementation

---

## Confidence Assessment

**High confidence (85%+):**
- Backend architecture is sound. All components exist; the plumbing is known.
- The tab-based coexistence model is low-risk; PTY is strictly isolated.
- `propose_command_with_trace()` reuse path is clean.
- Atomic ops classification correctly drives turn type routing.

**Medium confidence (60-75%):**
- The xterm.js vs custom DOM renderer boundary: there may be visual consistency work not anticipated.
- Small-model degradation behavior in practice may require more prompt engineering than anticipated (only testable with real hardware).

**Lower confidence / unknowns:**
- Exact registration path for new RPC endpoints in Cairn's `ui_rpc_server.py` — requires inspection during Phase 1 implementation.
- Whether `AtomicOpsProcessor` and `VerificationPipeline` can be cheaply instantiated per-request or need to be singletons (relevant for latency).
- TTY-requiring command detection heuristic completeness — this list will need iteration based on real user sessions.

## Assumptions Requiring Validation Before Phase 1 Implementation

1. Cairn's `ui_rpc_server.py` registers ReOS handlers by a discoverable mechanism that can be extended without patching core Cairn code.
2. The `AtomicOpsProcessor` is cheap to instantiate (or is already a singleton accessible from the RPC handler).
3. The trcore package exports `AtomicOpsProcessor`, `VerificationPipeline`, and `OperationExecutor` from the same import paths as Cairn uses (`trcore.atomic_ops.*`).
4. `portable-pty` Rust crate stays active in the background during tab switches (it does — there is no `pty_stop()` call in the tab-switch logic in `main.ts`).
