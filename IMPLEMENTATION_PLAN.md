# Plan: ReOS Standalone Project with Textual TUI

## Context

ReOS is a Linux system operations AI agent extracted from the Cairn (Talking Rock) project in
February 2026. The extraction is preserved in `/home/kellogg/dev/ReOS/` as an archive with no
standalone packaging — no `pyproject.toml`, no entry points, no `reos` Python package namespace.

**Current state of the archive:**

- `src/` — 11,580 lines across ~25 source files, organized as a flat directory (not a proper
  Python package). Files use relative imports (`.config`, `.security`, `.db`) where those
  modules exist in the source tree, and absolute `reos.*` imports where they expect to be
  installed as the `reos` package.
- `tests/` — 7,089 lines across 26 test files. Tests import from `reos.*` (the old installed
  package), `agents.*`, `classification.*`, `routing.*` (flat namespace from `src/`). The
  `cairn.*` namespace is absent from the archive — all shared infrastructure was already in the
  `reos.*` namespace before extraction.
- `src/security.py` does **not** exist in the archive; the actual security module lives in Cairn
  at `src/cairn/security.py` and imports `from cairn.config import SECURITY`. The ReOS
  `linux_tools.py` uses `from .security import ...`, meaning it expects a `security.py` sibling.
  This module was not copied into the archive.
- The `atomic_ops/`, `providers/`, `memory/`, `db_crypto.py`, `auth.py`, `config.py`,
  `errors.py`, `settings.py`, `db.py`, and `models.py` modules are **in Cairn** at
  `src/cairn/`. The ReOS archive imports these as `from reos.atomic_ops.*`,
  `from reos.providers.*`, etc. — these were the original `reos.*` namespaces before the rename.
- `src/agents/__init__.py` imports `from reos.cairn.intent_engine import CairnIntentEngine` and
  `from reos.agent import ChatAgent`, both of which are Cairn-specific. Dead code from the
  multi-agent era.
- There is a `search/` directory in `src/` containing only an `__init__.py` that imports
  `from reos.memory.embeddings import EmbeddingService` — another Cairn-only dependency.

**What ReOS actually does (its standalone purpose):**

- `linux_tools.py` (2,724 lines) — the heart: shell execution, system monitoring, package
  management, service management, process control, Docker, log analysis
- `system_index.py` (1,447 lines) — daily system state snapshots with FTS5 package search
- `system_state.py` (595 lines) — structured system state (disk, network, users)
- `shell_propose.py` (359 lines) — LLM-driven command proposal with safety validation
- `shell_context.py` (534 lines) — context gathering for informed command proposals
- `shell_cli.py` (503 lines) — terminal integration CLI
- `streaming_executor.py` (327 lines) — real-time command output streaming
- `classification/llm_classifier.py` (207 lines) — 3x2x3 taxonomy classification
- `routing/router.py` (123 lines) — request routing to agents
- `verification/intent_verifier.py` (129 lines) — LLM-as-judge intent verification
- `reos_agent.py` (130 lines) — the ReOS agent (natural language to command proposals)
- `alignment.py` (401 lines) — git alignment analysis
- `autostart.py` (186 lines) — XDG autostart management
- `handoff/` — agent handoff models and router (multi-agent infrastructure)
- `codebase_index.py`, `architecture/`, `repo_discovery.py` — code indexing (RIVA-adjacent)

**Why standalone packaging is needed:** ReOS cannot be installed, tested, or run without the
full Cairn venv. Making it standalone unlocks independent development, clean entry points, and
the Textual TUI.

---

## Approach (Recommended): Extract Shared Core as `talkingrock-core`, Package ReOS Cleanly

### Architecture

```
/home/kellogg/dev/
├── talkingrock-core/          # NEW: shared infrastructure package
│   └── src/trcore/            # package name: trcore
│       ├── providers/         # Ollama LLMProvider (from cairn)
│       ├── atomic_ops/        # 3x2x3 models, classifier, verifiers
│       ├── db.py, db_crypto.py
│       ├── errors.py, config.py, settings.py
│       ├── security.py, models.py, types.py
│       └── ...
│
└── ReOS/                      # THIS PROJECT
    ├── pyproject.toml         # NEW
    ├── src/reos/              # NEW: proper package directory
    │   ├── __init__.py
    │   ├── agent.py           # ReOS agent (rename from reos_agent.py)
    │   ├── linux_tools.py
    │   ├── system_index.py
    │   ├── system_state.py
    │   ├── shell_propose.py
    │   ├── shell_context.py
    │   ├── shell_cli.py
    │   ├── streaming_executor.py
    │   ├── autostart.py
    │   ├── classification/
    │   ├── routing/
    │   ├── verification/
    │   ├── tui/               # NEW: Textual TUI
    │   │   ├── __init__.py
    │   │   ├── app.py
    │   │   ├── screens/
    │   │   │   ├── dashboard.py
    │   │   │   ├── chat.py
    │   │   │   ├── settings.py
    │   │   │   ├── ops_log.py
    │   │   │   └── system_index_screen.py
    │   │   └── widgets/
    │   │       ├── resource_bar.py
    │   │       ├── chat_view.py
    │   │       ├── command_proposal.py
    │   │       └── live_metrics.py
    │   └── db/                # ReOS-specific schema
    │       ├── __init__.py
    │       └── schema.py
    └── tests/                 # existing 26 files, import paths updated
```

### Import Migration Map

Every `reos.*` import in the archive maps to either `trcore.*` (shared infrastructure) or stays
in `reos.*` (ReOS-specific code):

| Old import | New import | Location |
|---|---|---|
| `reos.providers.base` | `trcore.providers.base` | talkingrock-core |
| `reos.providers.ollama` | `trcore.providers.ollama` | talkingrock-core |
| `reos.providers.factory` | `trcore.providers.factory` | talkingrock-core |
| `reos.atomic_ops.models` | `trcore.atomic_ops.models` | talkingrock-core |
| `reos.atomic_ops.classifier` | `trcore.atomic_ops.classifier` | talkingrock-core |
| `reos.atomic_ops.verifiers` | `trcore.atomic_ops.verifiers` | talkingrock-core |
| `reos.atomic_ops.schema` | `trcore.atomic_ops.schema` | talkingrock-core |
| `reos.atomic_ops.classification_context` | `trcore.atomic_ops.classification_context` | talkingrock-core |
| `reos.db` | `trcore.db` | talkingrock-core |
| `reos.errors` | `trcore.errors` | talkingrock-core |
| `reos.config` | `trcore.config` | talkingrock-core |
| `reos.security` | `trcore.security` | talkingrock-core |
| `reos.settings` | `trcore.settings` | talkingrock-core |
| `reos.models` | `trcore.models` | talkingrock-core |
| `reos.memory.embeddings` | `trcore.memory.embeddings` | talkingrock-core |
| `reos.storage` | `trcore.storage` | talkingrock-core |
| `reos.certainty` | drop or move | evaluate per test |
| `reos.linux_tools` | `reos.linux_tools` | ReOS package |
| `reos.shell_propose` | `reos.shell_propose` | ReOS package |
| `reos.shell_context` | `reos.shell_context` | ReOS package |
| `reos.shell_cli` | `reos.shell_cli` | ReOS package |
| `reos.agent` | `reos.agent` | ReOS package |
| `reos.system_state` | `reos.system_state` | ReOS package |
| `reos.handoff.*` | `reos.handoff.*` | ReOS package |
| `reos.repo_discovery` | `reos.repo_discovery` | ReOS package |
| `reos.alignment` | `reos.alignment` | ReOS package |

**Cairn simultaneous update:** Cairn's `src/cairn/` will also need its `from cairn.providers.*`,
`from cairn.atomic_ops.*` etc. updated to `from trcore.*` once talkingrock-core exists. This is
a parallel workstream — do NOT do it in the same PR as ReOS packaging.

**Modules to exclude from ReOS (dead code):**

- `src/agents/cairn_agent.py` — imports `reos.cairn.store`, `reos.cairn.intent_engine`;
  Cairn-only, not needed in standalone ReOS
- `src/search/__init__.py` — imports `reos.memory.embeddings`; drop or defer
- `src/agents/__init__.py` — rewrite to expose only `ReOSAgent`
- Codebase indexing (`codebase_index.py`, `architecture/`, `repo_discovery.py`,
  `repo_sandbox.py`) — RIVA-adjacent; include in ReOS package but do not wire into TUI for
  Phase 1-3; mark as internal

---

## Alternatives Considered

### Alternative A: Vendor Cairn's shared modules directly into ReOS

Copy `providers/`, `atomic_ops/`, `errors.py`, etc. directly into the ReOS `src/reos/` tree
and rename all imports to `reos.*`.

**Pros:** Zero coordination overhead. ReOS is completely self-contained. No third package to
maintain.

**Cons:** Creates two canonical copies of `LLMProvider`, `Classification`, `errors.py`, and the
verifier pipeline. When Cairn fixes a bug in `OllamaProvider` or tightens a safety verifier,
ReOS diverges silently. The user has already indicated these should be shared
("shares common libs with Cairn and RIVA"). Over time this becomes a maintenance trap.

**Verdict:** Set aside. User intent is explicit about sharing.

### Alternative B: Make Cairn a dependency of ReOS (pip install from local path)

Install Cairn as `pip install -e /home/kellogg/dev/Cairn` into the ReOS venv, then import
`from cairn.providers.*` etc. directly.

**Pros:** Simplest import resolution; no new package to create.

**Cons:** ReOS depends on ALL of Cairn, including FastAPI, uvicorn, Tauri RPC machinery,
Play/Act/Scene models, memory compression pipeline, and all other Cairn-specific code. This
couples ReOS to Cairn's full dependency graph (including `pysqlcipher3`, `mistletoe`,
`python-pam`, etc.) and makes ReOS fragile to Cairn changes. Cairn would become a hard runtime
dependency of an independent agent.

**Verdict:** Set aside. Violates the standalone goal and creates tight coupling in the wrong
direction.

### Recommended: `talkingrock-core` extraction (chosen)

A thin shared package containing only genuinely shared primitives: providers, atomic_ops
models/classifiers/verifiers, db layer, errors, config, security, settings. No Cairn-specific
business logic (no Play, no memory, no compression, no health pulse). Both Cairn and ReOS depend
on `trcore`. RIVA will too when it is activated.

**Coordination cost:** Cairn must also be updated to `from trcore.*`. This can be done as a
separate PR immediately after talkingrock-core is created.

---

## Implementation Steps

### Phase 1: Package Scaffolding + Shared Core Extraction

**Goal:** ReOS tests pass with `pip install -e .` from `ReOS/`. No TUI yet.

**Step 1.1 — Create talkingrock-core**

Create `/home/kellogg/dev/talkingrock-core/` with the following structure. Every file is copied
from `src/cairn/` (the canonical versions) with `from cairn.` rewritten to `from trcore.`:

```
talkingrock-core/
├── pyproject.toml
└── src/trcore/
    ├── __init__.py
    ├── providers/
    │   ├── __init__.py
    │   ├── base.py
    │   ├── ollama.py
    │   ├── factory.py
    │   └── secrets.py
    ├── atomic_ops/
    │   ├── __init__.py
    │   ├── models.py
    │   ├── classifier.py
    │   ├── classification_context.py
    │   ├── schema.py
    │   ├── processor.py
    │   ├── executor.py
    │   ├── decomposer.py
    │   ├── entity_resolver.py
    │   ├── feedback.py
    │   └── verifiers/
    │       ├── __init__.py
    │       ├── base.py
    │       ├── behavioral.py
    │       ├── intent.py
    │       ├── pipeline.py
    │       ├── safety.py
    │       ├── semantic.py
    │       └── syntax.py
    ├── db.py
    ├── db_crypto.py
    ├── errors.py
    ├── config.py
    ├── security.py
    ├── settings.py
    ├── models.py
    ├── types.py
    ├── storage.py
    ├── logging_setup.py
    ├── context_budget.py
    └── memory/
        ├── __init__.py
        └── embeddings.py
```

`pyproject.toml` for talkingrock-core:

```toml
[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "talkingrock-core"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
  "httpx>=0.27.0,<1.0.0",
  "tenacity>=8.2.0,<10.0.0",
  "keyring>=24.0.0,<26.0.0",
  "secretstorage>=3.3.0,<4.0.0",
  "cryptography>=42.0.0,<44.0.0",
  "pysqlcipher3>=1.2.0,<2.0.0",
]

[project.optional-dependencies]
semantic = ["sentence-transformers>=3.0.0,<6.0.0"]

[tool.setuptools.packages.find]
where = ["src"]
```

**Step 1.2 — Scaffold the ReOS package**

Create `src/reos/` directory. Move source files from the flat `src/` into `src/reos/`.
File-by-file mapping:

```
src/alignment.py          -> src/reos/alignment.py
src/autostart.py          -> src/reos/autostart.py
src/codebase_index.py     -> src/reos/codebase_index.py
src/linux_tools.py        -> src/reos/linux_tools.py
src/reos_agent.py         -> src/reos/agent.py        (rename; primary agent)
src/repo_discovery.py     -> src/reos/repo_discovery.py
src/repo_sandbox.py       -> src/reos/repo_sandbox.py
src/shell_cli.py          -> src/reos/shell_cli.py
src/shell_context.py      -> src/reos/shell_context.py
src/shell_propose.py      -> src/reos/shell_propose.py
src/streaming_executor.py -> src/reos/streaming_executor.py
src/system_index.py       -> src/reos/system_index.py
src/system_state.py       -> src/reos/system_state.py
src/classification/       -> src/reos/classification/
src/handoff/              -> src/reos/handoff/
src/llm/                  -> src/reos/llm/
src/routing/              -> src/reos/routing/
src/verification/         -> src/reos/verification/
src/architecture/         -> src/reos/architecture/    (include, but do not wire)
src/agents/base_agent.py  -> src/reos/agents/base_agent.py
```

Files to delete (dead code / Cairn-only):

```
src/agents/cairn_agent.py   (Cairn-only)
src/agents/reos_agent.py    (merged into src/reos/agent.py above)
src/search/__init__.py      (embeddings dependency, deferred)
```

Files to rewrite:

```
src/agents/__init__.py      -> src/reos/agents/__init__.py (export ReOSAgent only)
```

New files to create:

```
src/reos/__init__.py          (version, __all__)
src/reos/__main__.py          (CLI entry point)
src/reos/db/__init__.py       (schema init helper)
src/reos/db/schema.py         (ReOS-specific tables)
src/reos/tui/                 (empty placeholder, Phase 3)
```

**Step 1.3 — Rewrite all imports**

For every file in `src/reos/`, apply the following substitutions:

```
from reos.providers.*              -> from trcore.providers.*
from reos.atomic_ops.*             -> from trcore.atomic_ops.*
from reos.db import                -> from trcore.db import
from reos.errors import            -> from trcore.errors import
from reos.config import            -> from trcore.config import
from reos.security import          -> from trcore.security import
from reos.settings import          -> from trcore.settings import
from reos.models import            -> from trcore.models import
from reos.storage import           -> from trcore.storage import
from reos.memory.embeddings import -> from trcore.memory.embeddings import
from reos.certainty import         -> evaluate (see Risks section)
from reos.agent import ChatAgent   -> drop (Cairn-only)
from reos.cairn.*                  -> drop (Cairn-only)
```

Relative imports (`.config`, `.security`, `.db`, `.providers`) already resolve correctly within
the new `reos` package; verify each one resolves to `reos.*` or `trcore.*` as intended.

For test files, also apply:

```
from agents.*         -> from reos.agents.*
from classification.* -> from reos.classification.*
from routing.*        -> from reos.routing.*
```

**Step 1.4 — Write `pyproject.toml` for ReOS**

```toml
[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "reos"
version = "0.1.0"
description = "ReOS by Talking Rock — natural language Linux system control"
authors = [{ name = "Talking Rock" }]
requires-python = ">=3.12"
dependencies = [
  "talkingrock-core>=0.1.0",
  "textual>=0.80.0,<1.0.0",
  "psutil>=5.9.0,<7.0.0",
]

[project.optional-dependencies]
dev = [
  "ruff>=0.6.0,<0.8.0",
  "mypy>=1.11.0,<1.13.0",
  "pytest>=8.3.0,<9.0.0",
  "pytest-cov>=4.1.0,<6.0.0",
]

[project.scripts]
reos = "reos.__main__:main"
reos-tui = "reos.tui.app:main"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "--cov=reos --cov-report=term-missing -m 'not slow'"
markers = [
  "slow: tests that require running Ollama",
]

[tool.ruff]
line-length = 100
target-version = "py312"
src = ["src"]

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B"]
```

**Step 1.5 — Create venvs and install**

```bash
# talkingrock-core first
cd /home/kellogg/dev/talkingrock-core
python3.12 -m venv .venv
.venv/bin/pip install -e .

# Then ReOS, pointing at the local core
cd /home/kellogg/dev/ReOS
python3.12 -m venv .venv
.venv/bin/pip install -e /home/kellogg/dev/talkingrock-core
.venv/bin/pip install -e ".[dev]"
```

**Step 1.6 — Run existing tests, fix import errors**

```bash
cd /home/kellogg/dev/ReOS
PYTHONPATH="src" .venv/bin/pytest tests/ -x --tb=short -q --no-cov
```

Fix import errors one file at a time. The majority will be `reos.*` to `trcore.*` redirects
handled in Step 1.3. Expect 10-20 import-level failures to debug.

**Phase 1 exit criterion:** All 26 existing test files import cleanly and the test suite passes
at the same pass/fail ratio as before. Do not fix pre-existing test logic failures — only fix
import breakage.

---

### Phase 2: ReOS-Specific Database Schema + Settings + CLI Entry Point

**Goal:** `reos` CLI works from the venv. Settings are configurable. Ops log schema exists.

**Step 2.1 — ReOS database schema**

Create `src/reos/db/schema.py` with the ReOS-specific tables. This is separate from
`trcore.db.Database` (which provides the connection class) and from the existing
`system_snapshots` / `packages_fts` tables in `system_index.py`.

New tables:

```sql
-- Proposed commands and their approval outcomes
CREATE TABLE IF NOT EXISTS operations_log (
    id TEXT PRIMARY KEY,
    ts TEXT NOT NULL,
    request TEXT NOT NULL,
    command TEXT NOT NULL,
    explanation TEXT,
    classification_json TEXT,
    approved INTEGER NOT NULL DEFAULT 0,  -- 0=pending, 1=approved, 2=rejected
    executed INTEGER NOT NULL DEFAULT 0,
    exit_code INTEGER,
    stdout_preview TEXT,
    stderr_preview TEXT,
    execution_duration_ms INTEGER,
    sudo_used INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

-- Safety decisions audit trail
CREATE TABLE IF NOT EXISTS safety_decisions (
    id TEXT PRIMARY KEY,
    ts TEXT NOT NULL,
    operation_id TEXT REFERENCES operations_log(id),
    command TEXT NOT NULL,
    blocked INTEGER NOT NULL,
    reason TEXT,
    check_type TEXT,   -- 'pattern', 'llm_judge', 'sudo_limit', 'rate_limit'
    created_at TEXT NOT NULL
);

-- User settings (key/value)
CREATE TABLE IF NOT EXISTS reos_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- FTS over operations log
CREATE VIRTUAL TABLE IF NOT EXISTS operations_fts USING fts5(
    request,
    command,
    explanation,
    content='operations_log',
    content_rowid='rowid',
    tokenize='porter unicode61'
);
```

**Step 2.2 — Settings service**

Create `src/reos/settings_service.py`. Wraps the `reos_settings` table with typed accessors:

- `ollama_model` — model to use (default: `llama3.2:3b`)
- `ollama_url` — Ollama endpoint (default: `http://127.0.0.1:11434`)
- `max_sudo_escalations` — per-session limit (default: 3)
- `rate_limit_window_seconds` — rate limit window (default: 60)
- `rate_limit_max_requests` — max commands per window (default: 20)
- `autostart_enabled` — XDG autostart state (boolean)
- `default_working_directory` — cwd for execution (default: `~`)
- `blocked_commands` — JSON list of regex patterns to always block
- `allowed_commands` — JSON list of patterns always allowed without LLM check

Environment variables override DB values at runtime, following the same pattern as `trcore.config`.

**Step 2.3 — CLI entry point**

Rewrite `src/reos/__main__.py`:

```python
"""ReOS CLI entry point.

Usage:
    reos                    # launch TUI
    reos ask "query"        # single query, print result, exit
    reos propose "query"    # propose command only, no execute
    reos run "query"        # propose + approval prompt + execute
"""
```

The `main()` function dispatches:

- No args -> launch TUI (`reos.tui.app:main`)
- `ask <query>` -> `shell_cli` single-query mode
- `propose <query>` -> `shell_propose.propose_command()`, print, exit
- `run <query>` -> propose + y/n approval prompt + execute if approved

**Step 2.4 — Ops log service**

Create `src/reos/ops_log.py`:

```python
class OpsLogService:
    def record_proposal(self, request, command, explanation, classification) -> str
    def record_approval(self, op_id, approved: bool) -> None
    def record_execution(self, op_id, exit_code, stdout, stderr, duration_ms) -> None
    def list_recent(self, limit: int = 200) -> list[OperationRecord]
    def search(self, query: str) -> list[OperationRecord]
```

This service is called from the Chat screen and from the `reos run` CLI path.

**Phase 2 exit criterion:** `reos ask "show disk usage"` runs without error in the venv.
`reos propose "install gimp"` prints a proposed command and exits. The ops log schema creates
correctly on first run.

---

### Phase 3: TUI Dashboard + Chat

**Goal:** `reos` (no args) launches a Textual TUI with working Dashboard and Chat screens.

**Step 3.1 — Textual app skeleton**

Create `src/reos/tui/app.py`:

```python
from textual.app import App, ComposeResult
from textual.binding import Binding

class ReOSApp(App):
    BINDINGS = [
        Binding("d", "switch_screen('dashboard')", "Dashboard"),
        Binding("c", "switch_screen('chat')", "Chat"),
        Binding("s", "switch_screen('settings')", "Settings"),
        Binding("l", "switch_screen('ops_log')", "Ops Log"),
        Binding("i", "switch_screen('system_index')", "Index"),
        Binding("q", "quit", "Quit"),
    ]
    CSS_PATH = "reos.tcss"

    def on_mount(self) -> None:
        db = Database()
        init_reos_schema(db)
        llm = OllamaProvider(
            url=settings_svc.ollama_url,
            model=settings_svc.ollama_model,
        )
        self.agent = ReOSAgent(llm=llm)
        self.executor = StreamingExecutor(llm_provider=llm)
        self.ops_log = OpsLogService(db)
```

**Step 3.2 — Dashboard screen**

File: `src/reos/tui/screens/dashboard.py`

ASCII layout:

```
┌─────────────────────────────────────────────────────────────────────┐
│  ReOS  [D]ashboard  [C]hat  [S]ettings  [L]og  [I]ndex       [Q]uit │
├─────────────────────────────────────────────────────────────────────┤
│ SYSTEM OVERVIEW                              hostname  kernel 6.17.0 │
├──────────────────────────┬──────────────────────────────────────────┤
│ CPU  [████████░░░░] 67%  │ RAM  [██████████░░] 84%  11.2 / 15.6 GB  │
│ Cores: 8  Load: 1.4      │ Swap: [█░░░░░░░░░░░]  5%                 │
├──────────────────────────┴──────────────────────────────────────────┤
│ DISK                                                                 │
│ /      [████████░░] 78%  89.3 GB / 115 GB  ext4                     │
│ /home  [█████░░░░░] 52%  234 GB / 450 GB   ext4                     │
├─────────────────────────────────────────────────────────────────────┤
│ SERVICES  (12 active / 3 failed)                                     │
│ ● nginx      active  3d 2h    ● docker      active  3d 2h           │
│ ● postgresql active  3d 2h    ✗ bluetooth   failed                  │
├─────────────────────────────────────────────────────────────────────┤
│ CONTAINERS  (3 running)                                              │
│  my-app    Up 2 hours    80/tcp  nginx:latest                        │
│  postgres  Up 3 days     5432/tcp  postgres:16                       │
├─────────────────────────────────────────────────────────────────────┤
│ > Ask ReOS anything...                              [C to open Chat] │
└─────────────────────────────────────────────────────────────────────┘
```

**Widgets:**

- `ResourceBar` — CPU percentage + load average via `psutil.cpu_percent()` and
  `psutil.getloadavg()`
- `MemoryBar` — RAM used/total, swap via `psutil.virtual_memory()` and `psutil.swap_memory()`
- `DiskPanel` — mounted partitions from `linux_tools.get_disk_usage()`, sorted by usage
- `ServicesPanel` — systemd services from `linux_tools.list_services()`, filtered to
  active/failed
- `ContainersPanel` — Docker containers from `linux_tools.list_containers()`, fails silently if
  Docker is not installed
- `QuickInputBar` — single-line input; Enter sends to Chat screen

**Update intervals:** Use Textual's `set_interval(5.0, refresh_metrics)` for live updates.
CPU, RAM, and disk update every 5 seconds. Services and containers update every 30 seconds (more
expensive syscalls).

**Data sources:** All from `reos.linux_tools`. No new I/O layer needed; `linux_tools.py` already
wraps `psutil`, `subprocess`, and `systemctl` calls.

**Step 3.3 — Chat screen**

File: `src/reos/tui/screens/chat.py`

ASCII layout:

```
┌─────────────────────────────────────────────────────────────────────┐
│  ReOS  [D]ashboard  [C]hat  [S]ettings  [L]og  [I]ndex       [Q]uit │
├─────────────────────────────────────────────────────────────────────┤
│ CHAT                                                          [clear] │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  You: what's using all my RAM?                           12:04:32    │
│                                                                      │
│  ReOS: Here are the top memory consumers on your system:            │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │ PROPOSED COMMAND                                            │    │
│  │  ps aux --sort=-%mem | head -20                             │    │
│  │  Lists top 20 processes sorted by memory usage             │    │
│  │                                                             │    │
│  │  [Y] Approve and run    [N] Skip    [E] Edit command        │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                                                                      │
│  [OUTPUT - ps aux]                                  exit: 0  0.3s   │
│  USER       PID %CPU %MEM    VSZ   RSS TTY      STAT                │
│  kellogg  12345  0.0 12.4 892048 51200 ?        Sl                  │
│  ...                                                                 │
│                                                                      │
├─────────────────────────────────────────────────────────────────────┤
│ > Type a request...                                                  │
└─────────────────────────────────────────────────────────────────────┘
```

**Key interaction flow:**

1. User types request and presses Enter
2. Chat screen dispatches `ReOSAgent.respond(request)` in a Textual worker thread
3. LLM response renders in chat history
4. If `AgentResponse.needs_approval == True`, render `CommandProposal` widget inline
5. `CommandProposal` shows command + explanation + `[Y]`/`[N]`/`[E]` bindings
6. On `[Y]`: call `StreamingExecutor.start(command)`, render output live via message passing
7. On `[N]`: mark as rejected in ops log, continue conversation
8. On `[E]`: open an editable Input pre-filled with the command; user edits then re-approves

**Widgets:**

- `ChatHistory` — scrollable `RichLog` of messages
- `CommandProposal` — bordered panel with command, explanation, action bindings; visible only
  when a proposal is pending
- `StreamingOutput` — live-updating `RichLog` for execution output; folds into chat history when
  complete
- `ChatInput` — `Input` widget at the bottom; auto-focused

**LLM calls must be non-blocking.** Use Textual workers:

```python
@work(thread=True)
async def process_request(self, request: str) -> None:
    response = self.app.agent.respond(request)
    self.post_message(AgentResponseReady(response))
```

**Dangerous command escalation UX:** Commands that pass Layer 1+2 safety checks but contain
`sudo`, `rm`, `dd`, `mkfs`, or explicit root paths render the `CommandProposal` with a red
border and a `[DANGEROUS]` header. The `[Y]` button is replaced with a text field requiring the
user to type `yes` explicitly before execution proceeds.

**Phase 3 exit criterion:** `reos` launches the TUI. Dashboard shows real system metrics. Chat
accepts input, calls the LLM, and renders the response. Command proposals appear inline with
`[Y]`/`[N]`. Approved commands execute and stream output.

---

### Phase 4: Settings Screen + Operations Log + System Index Screen

**Goal:** All five TUI screens are functional.

**Step 4.1 — Settings screen**

File: `src/reos/tui/screens/settings.py`

ASCII layout:

```
┌─────────────────────────────────────────────────────────────────────┐
│  ReOS  [D]ashboard  [C]hat  [S]ettings  [L]og  [I]ndex       [Q]uit │
├─────────────────────────────────────────────────────────────────────┤
│ SETTINGS                                            [Save]  [Reset]  │
├──────────────────────────────────┬──────────────────────────────────┤
│ LLM                              │ SAFETY                           │
│  Model:  [llama3.2:3b        ▼]  │  Max sudo/session: [3      ]     │
│  URL:    [http://localhost:11434] │  Rate limit (req/min): [20  ]    │
│  Health: ● Connected (4 models)  │  LLM safety check: [● Enabled]  │
├──────────────────────────────────┤  Require approval for: [All ▼]  │
│ EXECUTION                        ├──────────────────────────────────┤
│  Working dir: [~             ]   │ AUTOSTART                        │
│  Timeout (s): [300           ]   │  Start on login: [○ Disabled]   │
│  Blocked cmds: [Edit list... ]   │  Desktop file: ~/.config/auto.. │
└──────────────────────────────────┴──────────────────────────────────┘
│ MODEL SELECTION                                                      │
│  Available: llama3.2:1b  llama3.2:3b  llama3.2:11b  mistral:7b     │
│  Recommended for ReOS: llama3.2:3b (fast, safe, good at commands)  │
└─────────────────────────────────────────────────────────────────────┘
```

**Widgets:**

- Model selector: `Select` populated by `provider.list_models()`
- Health indicator: `Label` with color reactive to `provider.check_health()`
- All other fields: `Input` widgets bound to `SettingsService` keys
- Save: persists all fields to the `reos_settings` table
- Autostart toggle: calls `autostart.enable_autostart()` / `autostart.disable_autostart()`
- Blocked commands editor: opens a modal with a `TextArea` for editing the JSON list

**Step 4.2 — Operations Log screen**

File: `src/reos/tui/screens/ops_log.py`

ASCII layout:

```
┌─────────────────────────────────────────────────────────────────────┐
│  ReOS  [D]ashboard  [C]hat  [S]ettings  [L]og  [I]ndex       [Q]uit │
├─────────────────────────────────────────────────────────────────────┤
│ OPERATIONS LOG                          [Filter: all ▼]  [> Search] │
├────────┬──────────────────────────────┬────────┬────────────────────┤
│ Time   │ Command                      │ Status │ Request            │
├────────┼──────────────────────────────┼────────┼────────────────────┤
│ 12:04  │ ps aux --sort=-%mem | head   │ ✓ ran  │ what's using RAM?  │
│ 12:01  │ df -h                        │ ✓ ran  │ show disk usage    │
│ 11:58  │ sudo systemctl restart nginx │ ✗ skip │ restart nginx      │
│ 11:45  │ rm -rf /tmp/build            │ ✗ safe │ clean tmp build    │
├────────┴──────────────────────────────┴────────┴────────────────────┤
│ DETAIL (selected row)                                                │
│  Request: what's using all my RAM?                    2026-03-01    │
│  Command: ps aux --sort=-%mem | head -20                            │
│  Status:  Approved + Executed  (exit 0, 0.34s)                     │
│  Output preview: USER PID %CPU %MEM ... (22 lines)                 │
└─────────────────────────────────────────────────────────────────────┘
```

**Widgets:**

- `DataTable` of operations (newest-first) from `OpsLogService.list_recent(limit=200)`
- Filter dropdown: all / approved / rejected / blocked-by-safety
- Search input: FTS5 query via `OpsLogService.search(query)`
- Detail panel: full command, explanation, exit code, stdout/stderr preview for selected row

**Step 4.3 — System Index screen**

File: `src/reos/tui/screens/system_index_screen.py`

ASCII layout:

```
┌─────────────────────────────────────────────────────────────────────┐
│  ReOS  [D]ashboard  [C]hat  [S]ettings  [L]og  [I]ndex       [Q]uit │
├─────────────────────────────────────────────────────────────────────┤
│ SYSTEM INDEX                      Last snapshot: today 06:12  [↻]   │
├──────────────────────┬──────────────────────────────────────────────┤
│ SNAPSHOTS            │ SEARCH                                        │
│ > 2026-03-01  06:12  │ [> Search packages and services...         ] │
│   2026-02-29  06:10  │                                               │
│   2026-02-28  06:09  │ Results:                                      │
│   2026-02-27  06:11  │  nginx    1.26.0  (installed)  web server    │
│                      │  nginx-common  1.26.0  (installed)           │
├──────────────────────┤ SELECTED SNAPSHOT SUMMARY                    │
│ [Take Snapshot Now]  │  OS: Ubuntu 24.04 LTS  Kernel: 6.17.0-14    │
│                      │  RAM: 16GB  CPU: Intel i7 8-core             │
│                      │  Packages: 1,847 installed                   │
│                      │  Services: 15 active / 2 failed              │
└──────────────────────┴──────────────────────────────────────────────┘
```

**Widgets:**

- Snapshot list: `ListView` from `SystemIndexer.list_snapshots()`
- Search input: FTS5 query via `SystemIndexer.search_packages(query)`
- Search results: `DataTable` with name, version, installed status, description
- Snapshot summary: rendered from `SystemSnapshot` dataclass
- "Take Snapshot Now" button: calls `SystemIndexer.capture_snapshot()` in a worker thread,
  button disabled while running

**Phase 4 exit criterion:** All five screens navigate correctly via keybindings. Settings persist
across restarts. Ops log shows real command history. System Index shows snapshot data and FTS
search returns results.

---

### Phase 5: Polish, Testing, Documentation

**Goal:** Production-ready. Clean startup error handling. Documented.

**Step 5.1 — Startup error handling**

The TUI must handle gracefully:

- Ollama not running -> Settings screen shows a warning banner; Chat shows "Ollama is not
  reachable. Start it with: `ollama serve`"
- No model pulled -> Banner suggests `ollama pull llama3.2:3b`
- DB schema failure -> Show error modal, exit cleanly
- `pysqlcipher3` not installed -> Warn on startup, continue with unencrypted DB (existing
  fallback in `trcore.db_crypto` already handles this)

**Step 5.2 — TUI tests**

Use `textual.testing.App` (built into Textual). Mock `LLMProvider` and `StreamingExecutor`
so tests do not require Ollama or real command execution:

```python
async def test_dashboard_mounts():
    app = ReOSApp(llm=MockLLMProvider())
    async with app.run_test() as pilot:
        assert app.screen.__class__.__name__ == "DashboardScreen"
        resource_bar = app.query_one(ResourceBar)
        assert resource_bar.cpu_pct >= 0

async def test_chat_proposal_flow():
    app = ReOSApp(llm=MockLLMProvider(response="use: df -h"))
    async with app.run_test() as pilot:
        await pilot.press("c")
        await pilot.type("show disk usage")
        await pilot.press("enter")
        await pilot.pause(delay=0.5)
        proposal = app.query_one(CommandProposal)
        assert proposal.is_displayed
```

**Step 5.3 — Update existing tests for new import paths**

The 26 existing test files import from `reos.*` (old installed package). After Phase 1 import
migration they should pass with only import path updates. Run with:

```bash
PYTHONPATH="src" .venv/bin/pytest tests/ -x --tb=short -q --no-cov
```

**Step 5.4 — Autostart update**

`autostart.py` currently looks for a `reos` shell script at the repo root. After packaging,
update `_get_reos_executable()` to call `shutil.which("reos")` first (the installed entry
point), then fall back to the venv's `bin/reos`.

**Step 5.5 — Documentation**

Create `README.md` covering:

- What ReOS is and what it does
- Installation (`pip install -e .`)
- Requirements (Ollama, Python 3.12, `libsqlcipher-dev`)
- Usage: `reos` (TUI), `reos ask`, `reos propose`, `reos run`
- Safety model: what is blocked, what requires approval, sudo limits
- Configuration: environment variables, settings screen

---

## Files Affected

### New Files (create)

| File | Purpose |
|---|---|
| `/home/kellogg/dev/talkingrock-core/pyproject.toml` | Shared core package definition |
| `talkingrock-core/src/trcore/__init__.py` | Package root |
| `talkingrock-core/src/trcore/providers/` | Copied from Cairn, imports rewritten |
| `talkingrock-core/src/trcore/atomic_ops/` | Copied from Cairn, imports rewritten |
| `talkingrock-core/src/trcore/db.py` | Copied from Cairn |
| `talkingrock-core/src/trcore/db_crypto.py` | Copied from Cairn |
| `talkingrock-core/src/trcore/errors.py` | Copied from Cairn |
| `talkingrock-core/src/trcore/config.py` | Copied from Cairn |
| `talkingrock-core/src/trcore/security.py` | Copied from Cairn |
| `talkingrock-core/src/trcore/settings.py` | Copied from Cairn |
| `talkingrock-core/src/trcore/models.py` | Copied from Cairn |
| `talkingrock-core/src/trcore/types.py` | Copied from Cairn |
| `talkingrock-core/src/trcore/storage.py` | Copied from Cairn |
| `talkingrock-core/src/trcore/logging_setup.py` | Copied from Cairn |
| `talkingrock-core/src/trcore/context_budget.py` | Copied from Cairn |
| `talkingrock-core/src/trcore/memory/embeddings.py` | Copied from Cairn |
| `/home/kellogg/dev/ReOS/pyproject.toml` | ReOS package definition |
| `ReOS/src/reos/__init__.py` | Package root (version, `__all__`) |
| `ReOS/src/reos/__main__.py` | CLI dispatcher |
| `ReOS/src/reos/db/__init__.py` | Schema init helper |
| `ReOS/src/reos/db/schema.py` | ops log, safety decisions, settings tables |
| `ReOS/src/reos/ops_log.py` | OpsLogService |
| `ReOS/src/reos/settings_service.py` | SettingsService |
| `ReOS/src/reos/tui/app.py` | ReOSApp (Textual App root) |
| `ReOS/src/reos/tui/__init__.py` | TUI package root |
| `ReOS/src/reos/tui/reos.tcss` | Textual CSS stylesheet |
| `ReOS/src/reos/tui/screens/__init__.py` | Screens package |
| `ReOS/src/reos/tui/screens/dashboard.py` | Dashboard screen |
| `ReOS/src/reos/tui/screens/chat.py` | Chat screen |
| `ReOS/src/reos/tui/screens/settings.py` | Settings screen |
| `ReOS/src/reos/tui/screens/ops_log.py` | Operations Log screen |
| `ReOS/src/reos/tui/screens/system_index_screen.py` | System Index screen |
| `ReOS/src/reos/tui/widgets/__init__.py` | Widgets package |
| `ReOS/src/reos/tui/widgets/resource_bar.py` | CPU/RAM progress bars |
| `ReOS/src/reos/tui/widgets/live_metrics.py` | Auto-updating metrics panel |
| `ReOS/src/reos/tui/widgets/command_proposal.py` | Inline approve/reject/edit widget |
| `ReOS/src/reos/tui/widgets/chat_view.py` | Chat history and input |
| `ReOS/tests/test_ops_log.py` | OpsLogService tests |
| `ReOS/tests/test_settings_service.py` | SettingsService tests |
| `ReOS/tests/test_tui_dashboard.py` | TUI dashboard screen tests |
| `ReOS/tests/test_tui_chat.py` | TUI chat + proposal flow tests |
| `ReOS/tests/test_tui_settings.py` | TUI settings screen tests |
| `ReOS/tests/test_tui_ops_log.py` | TUI ops log screen tests |
| `ReOS/tests/test_safety_flow.py` | End-to-end safety gate tests |
| `ReOS/README.md` | Project documentation |

### Files Modified (in place, import paths updated)

| File | Change |
|---|---|
| All `src/reos/**/*.py` | `reos.*` -> `trcore.*` where shared; stay `reos.*` where local |
| All `tests/test_*.py` | Import path migration + namespace prefix fixes |
| `src/reos/agents/__init__.py` | Rewrite to export only `ReOSAgent` |
| `src/reos/autostart.py` | Update `_get_reos_executable()` for installed entry point |
| `src/reos/streaming_executor.py` | `from reos.security` -> `from trcore.security` |
| `src/reos/verification/__init__.py` | `from reos.atomic_ops.*` -> `from trcore.atomic_ops.*` |
| `src/reos/llm/__init__.py` | `from reos.providers.*` -> `from trcore.providers.*` |

### Files Deleted

| File | Reason |
|---|---|
| `src/agents/cairn_agent.py` | Cairn-only; not part of standalone ReOS |
| `src/search/__init__.py` | Imports Cairn embedding service; deferred |

---

## Data Model

**Database location:** `~/.reos-data/reos.db` (existing path, preserved per backward-compatibility
decision from the February 2026 extraction — changing it would lose user data)

**Tables owned by ReOS (new in this plan):**

- `operations_log` — command proposal history with approval outcomes
- `safety_decisions` — audit trail for every safety check decision
- `reos_settings` — user-configurable settings (key/value)
- `operations_fts` — FTS5 virtual table over operations_log

**Tables owned by ReOS (existing, from archive):**

- `system_snapshots` — daily system state (created by `SystemIndexer`)
- `packages_fts` — FTS5 over package names/descriptions
- `desktop_apps` — installed GUI apps

**Tables owned by talkingrock-core (existing in Cairn, accessed via `trcore.db.Database`):**

- All Cairn tables (acts, scenes, conversations, memories, etc.) — ReOS does not touch these;
  they share the SQLite file but ReOS only reads/writes its own tables

**Settings storage:** All settings stored in the `reos_settings` table. Environment variables
override DB values at runtime. No separate config file.

---

## LLM Integration

**Provider:** Ollama exclusively. Local-first, no cloud, per Talking Rock philosophy.

**Interface:** `trcore.providers.base.LLMProvider` protocol.
`OllamaProvider` from `trcore.providers.ollama` is the concrete implementation.

**Recommended models for ReOS:**

| Task | Model | Reasoning |
|---|---|---|
| Command proposal (`shell_propose`) | `llama3.2:3b` | Fast, precise, good at shell tasks |
| Classification (`LLMClassifier`) | `llama3.2:1b` | Minimal task, cheapest model |
| Safety check (`verify_command_safety_llm`) | `llama3.2:3b` | Needs judgment capability |
| Intent verification | `llama3.2:3b` | Needs reasoning |

The model is configured once via `SettingsService.ollama_model` and used for all tasks. The
existing `OllamaProvider` already supports per-call model selection.

**Connection:** `http://127.0.0.1:11434` (default). The `trcore.settings.Settings.__post_init__`
already enforces localhost-only for zero-trust compliance.

**TUI LLM calls:** All LLM calls from the TUI are dispatched via Textual workers (daemon
threads) to avoid blocking the event loop. No `asyncio` required — Textual workers handle
the threading.

---

## Safety Model

ReOS implements a four-layer safety model, already present in the codebase:

**Layer 1 — Static pattern matching** (`linux_tools.DANGEROUS_COMMAND_PATTERNS`)
Hard-blocked patterns: `rm -rf /`, `rm -rf /*`, `dd` targeting block devices, `mkfs`, fork
bombs, `chmod -R 777 /`. These are never proposed or executed under any circumstances.

**Layer 2 — LLM safety judge** (`trcore.security.verify_command_safety_llm`)
The LLM evaluates whether a proposed command is appropriate for the stated request. Runs before
any proposal is shown to the user. Fail-closed: if the LLM call fails, the command is rejected.

**Layer 3 — Rate limiting** (`trcore.security.RateLimiter`)
Maximum N commands per time window per session. Configurable via the Settings screen.

**Layer 4 — Sudo escalation limit** (`SECURITY.MAX_SUDO_ESCALATIONS`)
Maximum sudo invocations per session. Default 3. Configurable via the Settings screen.

**TUI approval flow:**

```
User request -> LLM proposes command
               |
          Layer 1 check (static patterns)
               |
          Layer 2 check (LLM safety judge)
               |
          Render CommandProposal widget
               |
    [Y] Approve -> Layer 3/4 checks -> Execute -> stream output
    [N] Reject  -> Log as rejected, continue conversation
    [E] Edit    -> User edits -> re-run Layer 1+2 on edited command
```

**Dangerous command escalation:** Commands that pass Layers 1+2 but contain `sudo`, `rm`, `dd`,
`mkfs`, or explicit root paths render with a red border and `[DANGEROUS]` header. The `[Y]`
button is replaced with a text field requiring the user to type `yes` explicitly.

**Audit trail:** Every command that reaches the approval flow is written to `operations_log`.
Every safety decision (blocked or allowed) is written to `safety_decisions`, regardless of
whether the user ultimately approves execution.

---

## Testing Strategy

### Existing Tests (26 files, 7,089 lines)

These were written for the Cairn-era `reos.*` namespace. After Phase 1 import migration, they
should pass with only import path changes — no logic changes.

**Run command:**

```bash
cd /home/kellogg/dev/ReOS
PYTHONPATH="src" .venv/bin/pytest tests/ -x --tb=short -q --no-cov
```

**Tests that may require logic changes** (beyond import paths):

- `test_agents.py` — imports `CAIRNAgent` (from deleted `cairn_agent.py`); rewrite to test
  `ReOSAgent` only
- `test_agent_routing_e2e.py` — may reference CAIRN routing paths; audit and narrow to ReOS
- `test_mcp_sandbox.py` — imports `reos.mcp_server._safe_repo_path`; this module is in Cairn,
  not in the archive; this test may need to be dropped from scope

### New Tests Required

| Test file | Coverage |
|---|---|
| `tests/test_ops_log.py` | OpsLogService CRUD, FTS search, pagination |
| `tests/test_settings_service.py` | Read/write/override for all setting keys |
| `tests/test_tui_dashboard.py` | Dashboard mounts, ResourceBar shows non-negative values |
| `tests/test_tui_chat.py` | Chat input, proposal widget renders, Y/N/E flow |
| `tests/test_tui_settings.py` | Settings screen reads from and writes to SettingsService |
| `tests/test_tui_ops_log.py` | Ops Log DataTable populates from OpsLogService |
| `tests/test_safety_flow.py` | Dangerous command blocked, safe command proposed end-to-end |

**TUI testing approach:** Use `textual.testing` (built into Textual). Inject a mock
`LLMProvider` into `ReOSApp` via a constructor parameter. Mock `StreamingExecutor` to return
canned output. No Ollama required for the test suite.

**Slow tests (require Ollama, marked `@pytest.mark.slow`):**

- Real command proposal round-trips
- LLM safety judge evaluation
- Intent verification round-trips

**Coverage targets:**

- `reos.linux_tools` — maintain existing 1,172-line test coverage
- `reos.ops_log` — 100% of public methods
- `reos.settings_service` — 100% of public methods
- `reos.tui.*` — happy path per screen; Ollama-down error state; empty DB state

---

## Risks and Mitigations

### Risk 1: talkingrock-core creates ongoing coordination burden

**Description:** Any change to `LLMProvider`, `Classification`, or `errors.py` in talkingrock-core
now requires updating both Cairn and ReOS. If one project upgrades and the other doesn't, import
errors appear at runtime.

**Mitigation:** Version pin conservatively in both `pyproject.toml` files
(`talkingrock-core>=0.1.0,<0.2.0`). Treat `0.x` as internal. No breaking interface changes
without incrementing the minor version. Evaluate a monorepo structure (Cairn + ReOS as workspace
members) after talkingrock-core stabilizes — it eliminates version coordination entirely at the
cost of merged git histories.

### Risk 2: `security.py` is absent from the ReOS archive

**Description:** `linux_tools.py` does `from .security import ...`. The archive has no
`security.py` sibling — that module lives in Cairn. After import rewriting, this becomes
`from trcore.security import ...`, which resolves correctly only after talkingrock-core is
installed.

**Mitigation:** Phase 1, Step 1.1 (create talkingrock-core) must complete and be installed into
the ReOS venv before Step 1.6 (run tests). Do not attempt to run tests before talkingrock-core
is installed.

### Risk 3: `reos.certainty` and `reos.code_mode` imports in tests

**Description:** The test suite imports `from reos.certainty import ...` and references
`reos.code_mode`. Neither `certainty.py` nor `code_mode/` appear in the archive's `src/`
listing — they likely live in Cairn only.

**Mitigation:** Audit each such import during Phase 1. For each one: (a) if the module exists in
Cairn and is genuinely shared, add it to talkingrock-core; (b) if it is Cairn/RIVA-specific,
that test is out of scope for the standalone ReOS archive — mark it as skip or delete it.
The test `test_alignment.py` also imports `reos.certainty`; audit it too.

### Risk 4: Textual threading vs. StreamingExecutor threading

**Description:** `StreamingExecutor` uses `threading.Thread` + `Queue` internally. Textual
workers also use threads. If both systems attempt to update the UI directly, race conditions
can occur.

**Mitigation:** All Textual UI updates must happen via `self.call_from_thread()` or
`self.post_message()`, never via direct widget mutation from a non-main thread. The safe
pattern: run `StreamingExecutor.start()` inside a Textual worker; the worker polls
`executor.get_output()` in a tight loop and posts a `NewOutputLine` message per line; the
Textual event handler on the main thread appends to the `RichLog`. Document this contract
explicitly in `streaming_executor.py`.

### Risk 5: Cairn migration delay causes drift

**Description:** Once talkingrock-core exists, Cairn must migrate from `from cairn.*` to
`from trcore.*` for all shared modules. This is a large diff (2,000+ import statements). If
delayed, Cairn and talkingrock-core diverge independently.

**Mitigation:** Create the Cairn migration PR immediately after talkingrock-core is created,
before beginning ReOS TUI work. Run Cairn's 2,031 tests to validate. The migration is
mechanical — bulk substitution via `ruff` or `sed` handles most of it. Pin Cairn to the same
`talkingrock-core` version as ReOS initially.

### Risk 6: SQLite database sharing between Cairn and ReOS

**Description:** Both Cairn and ReOS use `~/.reos-data/reos.db`. If both run simultaneously and
both apply schema migrations, there is a risk of migration conflicts.

**Mitigation:** All migrations use `CREATE TABLE IF NOT EXISTS` (idempotent). Since Cairn is
currently a Tauri desktop app and ReOS will be a separate TUI process, simultaneous operation
is unlikely in practice. SQLite WAL mode (already enabled) handles concurrent reads safely. For
Phase 5, consider a migration lock table or a separate DB file for ReOS-specific tables
(`reos-ops.db`) to eliminate shared-file risk entirely.

### Risk 7: `psutil` not in existing `linux_tools.py`

**Description:** The Dashboard design calls for `psutil.cpu_percent()` and
`psutil.virtual_memory()` for live metrics. The existing `linux_tools.py` uses `subprocess`
for all system queries, not `psutil`.

**Mitigation:** Two options: (a) add `psutil` as a dependency and use it directly in Dashboard
widgets (simpler, more accurate, lower latency); (b) reuse the existing `linux_tools` subprocess
calls (no new dependency, but slower for 5-second polling). Option (a) is recommended — `psutil`
is a mature library with no security surface and the Dashboard is the right place to add it.
The existing `linux_tools.py` remains unchanged; `psutil` is used only in TUI widgets.

---

## Definition of Done

- [ ] `talkingrock-core` installs cleanly with `pip install -e .` at
  `/home/kellogg/dev/talkingrock-core/`
- [ ] Cairn's 2,031 tests pass after migrating to `from trcore.*` imports
- [ ] `/home/kellogg/dev/ReOS/pyproject.toml` exists with correct metadata and entry points
- [ ] `src/reos/` is a proper Python package with `__init__.py` and `__main__.py`
- [ ] All 26 original test files pass with updated import paths
- [ ] `reos ask "show disk usage"` prints a response in the terminal
- [ ] `reos propose "install gimp"` outputs a proposed shell command and exits
- [ ] `reos` (no args) launches the Textual TUI without errors
- [ ] Dashboard screen shows live CPU, RAM, and disk metrics
- [ ] Dashboard metrics update every 5 seconds without manual refresh
- [ ] Chat screen accepts natural language, calls Ollama, renders the response
- [ ] Command proposals appear inline with `[Y]`/`[N]`/`[E]` bindings
- [ ] Dangerous commands render with red border and require `yes` to confirm
- [ ] Approved commands execute and stream output inline in the Chat screen
- [ ] Settings screen persists changes to the `reos_settings` table across restarts
- [ ] Autostart toggle calls `autostart.enable_autostart()` / `disable_autostart()`
- [ ] Ops Log screen shows command history and FTS search returns results
- [ ] System Index screen shows snapshot list; package search returns results
- [ ] All new test files pass: `test_ops_log`, `test_settings_service`, `test_tui_*`,
  `test_safety_flow`
- [ ] TUI tests use a mock LLM — no Ollama required to run `pytest`
- [ ] Ollama-down state shows a helpful error in Chat and Settings screens (no crash)
- [ ] `README.md` covers installation, usage, safety model, and configuration
- [ ] No import of `cairn.*` anywhere in `src/reos/` or `tests/`

---

## Confidence Assessment

**Confidence: 8/10** on the overall approach.

The package structure and import migration are mechanical work with clear precedent in the
existing codebase — the module boundaries are well-defined and the grep output makes the
dependency graph explicit. The `talkingrock-core` extraction directly mirrors the existing
Cairn package structure. The Textual TUI design is straightforward: all data sources exist
(`linux_tools`, `system_index`, `streaming_executor`) and Textual is a well-documented
framework with a built-in testing library.

**Lower-confidence areas:**

- `reos.certainty` and `reos.code_mode` test imports are unknowns. Actual content of those
  test files needs inspection before the final pass/fail count can be committed to.
- Textual CSS complexity: the ASCII mockups define structure; exact styling (padding, borders,
  color scheme) is implementation detail left to the implementer's judgment.
- `context_budget.py` and `logging_setup.py` are listed for talkingrock-core but their full
  dependency chains in ReOS were not traced. Verify each file before assuming it belongs in
  `trcore` vs. staying in `reos`.

---

## Unknowns Requiring Validation Before Phase 1

1. **`reos.certainty` module** — visible in test imports but absent from `src/`. Locate it in
   Cairn before Phase 1 to decide: add to talkingrock-core, or drop those tests.

2. **`reos.code_mode` in `test_mcp_sandbox.py`** — confirm whether this test file is in scope
   for standalone ReOS. If it tests RIVA-era code-mode functionality, it should be dropped from
   the ReOS archive tests.

3. **`src/agents/cairn_agent.py` test coverage** — before deleting, grep all test files for
   `CAIRNAgent` and `cairn_agent`. Confirm how many test cases depend on it so the test count
   impact is known.

4. **Simultaneous Cairn + ReOS operation** — confirm this is not a current user requirement.
   If both can run at the same time against the same DB, implement a migration lock or separate
   the DB files before Phase 1.

5. **Textual minimum version** — `textual>=0.80.0` is specified. Verify that `DataTable`,
   `RichLog`, `Select`, `TextArea`, and the `@work` decorator are all available at 0.80.x.
   As of August 2025, 0.80+ includes all of these.
