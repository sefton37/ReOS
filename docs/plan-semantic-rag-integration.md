# Plan: Semantic Layer RAG Integration into NL→Shell Pipeline

## Executive Summary

ReOS has a 48K-line YAML semantic layer (16 domains, 267 commands, 6,142 searchable phrases)
that currently sits unused at query time. The LLM generates commands from scratch on every
request. This plan integrates the semantic layer as a retrieval-augmented generation (RAG)
grounding layer: at query time, the 3–5 most semantically similar intents are fetched and
injected into the LLM prompt so the model matches and fills a known pattern rather than
inventing from scratch. This collapses the model's effective output space from infinite to
the set of vetted, safe, structured patterns in the semantic layer.

Three design decisions are already locked. This plan builds around them without revisiting
them. See the Decision Log section for rationale.

---

## Architecture Diagram

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                         NL→SHELL PIPELINE (new flow)                         │
│                                                                              │
│  User Input                                                                  │
│      │                                                                       │
│      ▼                                                                       │
│  analyze_intent()          ← shell_context.py:ShellContextGatherer          │
│  returns (verb, target)    ← e.g. ("install", "nginx")                      │
│      │                                                                       │
│      ▼                                                                       │
│  FTS5 fast-path?           ← shell_context.py:search_fts5()                 │
│  ┌── YES ──────────────────────────────────────────────────────────────┐    │
│  │  Use FTS5 result directly as context; skip ChromaDB retrieval       │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│      │ NO                                                                    │
│      ▼                                                                       │
│  embed_intent_query()      ← semantic_rag.py (NEW)                          │
│  input: "install nginx"    ← cleaned verb+object from analyze_intent()      │
│  calls: nomic-embed-text via Ollama /api/embeddings                         │
│      │                                                                       │
│      ▼                                                                       │
│  ChromaDB.query(top_k=5)   ← semantic_rag.py (NEW)                         │
│  collection: reos_intents  ← pre-built at index time                        │
│  returns: top-K SemanticEntry objects                                        │
│      │                                                                       │
│      ▼                                                                       │
│  similarity_threshold?     ← filter at 0.65 cosine distance                 │
│  ┌── BELOW THRESHOLD ─────────────────────────────────────────────────┐    │
│  │  No grounding injected; original free-generation pipeline           │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│      │ ABOVE THRESHOLD                                                       │
│      ▼                                                                       │
│  format_rag_context()      ← semantic_rag.py (NEW)                          │
│  builds: structured prompt block (pattern + safety + undo)                  │
│      │                                                                       │
│      ▼                                                                       │
│  propose_command_with_trace()   ← shell_propose.py (MODIFIED)              │
│  CONVERSATIONAL_PROMPT now includes RAG_CONTEXT_BLOCK                       │
│  model: matches intent → fills parameters → returns COMMAND:                │
│      │                                                                       │
│      ▼                                                                       │
│  safety checks             ← is_safe_command() + blocked-patterns loader    │
│  (blocked-patterns.yaml fast-reject added pre-LLM)                         │
│      │                                                                       │
│      ▼                                                                       │
│  undo path surfaced        ← extracted from retrieved SemanticEntry         │
│  → returned in ProposalTrace                                                 │
│      │                                                                       │
│      ▼                                                                       │
│  ProposalTrace → RPC response                                                │
└──────────────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────────────┐
│                           INDEX BUILD PIPELINE (offline)                     │
│                                                                              │
│  semantic-layer/domains/*.yaml                                               │
│  semantic-layer/intent-index.yaml                                            │
│      │                                                                       │
│      ▼                                                                       │
│  SemanticLayerIndexer.build()   ← semantic_rag.py (NEW)                     │
│  - parse all intent + alternate_phrasings from each YAML                    │
│  - for each phrase: embed via nomic-embed-text (Ollama batch)                │
│  - store in ChromaDB with metadata:                                          │
│      document:  the phrase text                                              │
│      id:        "{domain}/{command}/{intent_idx}/{phrase_idx}"               │
│      metadata:  {domain, command, pattern, safety_level,                    │
│                  requires_sudo, undo_op, undo_cmd}                           │
│      │                                                                       │
│      ▼                                                                       │
│  Hash manifest written to:                                                   │
│  ~/.reos-data/semantic_index_manifest.json                                   │
│  (per-domain SHA256 of YAML file → re-index only changed domains)            │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## Section 1: Indexing Pipeline

### What Gets Embedded

Every searchable phrase in the semantic layer is embedded as a separate document. The
embedding unit is the individual phrase string — either a canonical intent string or one of
its alternate phrasings — not the full YAML block.

Source: `semantic-layer/intent-index.yaml` is the authoritative flat index (6,142 entries).
This is already normalized: each entry has `phrase`, `command`, `domain`, `pattern`, and
`is_alternate`. The domain YAML files are the canonical source for safety metadata and undo
paths; the intent-index.yaml is the retrieval source.

**ChromaDB document per phrase:**

```
document  : <phrase string>          # embedded text, e.g. "how do I bundle up a directory"
id        : "{domain}_{cmd}_{sha8}"  # stable unique ID derived from content
metadata  :
  domain         : "compression"
  command        : "tar"
  pattern        : "tar czf {archive.tar.gz} {directory}"
  safety_level   : "safe"            # looked up from domain YAML at index time
  requires_sudo  : false
  undo_op        : "extraction"      # key from undo dict in domain YAML
  undo_cmd       : "tar xf {archive.tar.gz}"  # value
  is_alternate   : true              # true for alternate_phrasings, false for canonical
```

The `id` field uses a content-based hash (SHA256 of phrase+domain+command, first 8 chars)
rather than a sequential integer so that re-indexing a single domain produces the same IDs
for unchanged phrases and only inserts new ones.

**Total documents: 6,142** (one per phrase in intent-index.yaml).

### When Indexing Happens

Indexing is NOT automatic at startup (cold-start latency would be unacceptable). Three
triggers:

1. **First-run sentinel.** On `propose_command_with_trace()` startup, `SemanticRetriever`
   checks for the ChromaDB collection `reos_intents`. If it does not exist, it logs a
   warning and falls through to free-generation mode. A separate CLI command builds the
   index.

2. **Explicit CLI command.**
   ```
   python -m reos.semantic_rag index
   ```
   This runs `SemanticLayerIndexer.build()` synchronously, embedding all 6,142 phrases
   against nomic-embed-text via Ollama. Estimated time: ~2–5 minutes on CPU (nomic is
   fast).

3. **Background thread after first use.** When `SemanticRetriever` detects missing index
   at startup, it spawns a daemon thread that builds the index in the background. Subsequent
   requests (after a few minutes) will have the index available. The background flag is
   tracked in a module-level `threading.Event` so the retriever does not spawn duplicates.

### Cache Invalidation

A manifest file at `~/.reos-data/semantic_index_manifest.json` stores:

```json
{
  "domains": {
    "file-operations": {"sha256": "abc123...", "indexed_at": "2026-03-17T..."},
    "compression": {"sha256": "def456...", "indexed_at": "2026-03-17T..."},
    ...
  },
  "intent_index": {"sha256": "xyz789...", "indexed_at": "2026-03-17T..."}
}
```

On `SemanticLayerIndexer.build()`, each domain YAML and `intent-index.yaml` is hashed. If a
domain's hash matches the manifest, its phrases are skipped. If it differs, the existing
documents for that domain are deleted from ChromaDB and re-indexed. This makes re-indexing
after a YAML edit fast (typically re-embeds 300–400 phrases for one domain rather than
6,142).

### ChromaDB Storage Path

ChromaDB's persistent storage: `~/.reos-data/chromadb/` (alongside the existing SQLite DB
at `~/.reos-data/reos.db`).

Collection name: `reos_intents`

Embedding function: `chromadb.utils.embedding_functions.OllamaEmbeddingFunction` pointing
at `http://localhost:11434` with model `nomic-embed-text`.

---

## Section 2: Retrieval Flow — Exact Integration Points

### Key Functions in the Current Pipeline

**`shell_context.py`:**
- Line 165: `analyze_intent(natural_language) -> (intent_verb, intent_target)` — extracts
  verb and target. This is the cleaned query for embedding. E.g. "install nginx" from "can
  you install nginx for me".
- Line 464: `search_fts5(query, limit=5)` — the existing FTS5 keyword search over system
  packages/apps. The FTS5 fast-path logic gates on exact/near-exact package name matches
  (lines 267–285 of `gather_context()`). The FTS5 path sets `can_verify = True` when it
  finds results.

**`shell_propose.py`:**
- Line 475: `propose_command_with_trace(natural_language, conversation_context="")` — the
  main entry point. Context gathering happens here at lines 502–513. The `user_prompt` is
  assembled at lines 517–521.
- Lines 538–590: Attempt 1 (CONVERSATIONAL_PROMPT + `user_prompt`). This is where the RAG
  context block is injected into `user_prompt`.

### New Call: Where embed_query Goes

The embedding call is added inside `propose_command_with_trace()`, immediately after
`get_context_for_proposal()` returns (after line 513, before line 517 where `user_prompt`
is built).

```python
# After line 513 in shell_propose.py:
rag_context_string = ""
rag_safety_level: str | None = None
rag_undo: dict[str, str] | None = None

if context.can_verify and context.fts_matches:
    # FTS5 found something — use it, skip ChromaDB retrieval
    pass
else:
    # FTS5 found nothing — try semantic layer retrieval
    try:
        from .semantic_rag import get_retriever
        retriever = get_retriever()
        query = _build_embed_query(natural_language, context)
        entries = retriever.retrieve(query, top_k=5)
        if entries:
            rag_context_string = retriever.format_for_prompt(entries)
            rag_safety_level = entries[0].safety_level  # top match
            rag_undo = entries[0].undo
    except Exception:
        pass  # RAG is always fail-open
```

`_build_embed_query()` is a two-line helper that prefers the cleaned `intent_verb +
intent_target` string from the ShellContext, falling back to the raw `natural_language`
string if no intent was extracted. This produces cleaner embeddings.

### FTS5-First / ChromaDB-Fallback Routing

The routing rule is simple:

| Condition | Action |
|-----------|--------|
| `context.fts_matches` is non-empty | Skip ChromaDB. FTS5 already has system context (package names, service names). |
| `context.executable_path` or `context.package_installed` | Skip ChromaDB. System context is the better grounding signal. |
| None of the above | Run ChromaDB retrieval. |

This is not a fallback in the "ChromaDB is worse" sense. The two systems answer different
questions: FTS5 knows what is on this machine. ChromaDB knows what patterns exist in the
semantic layer. For queries like "install nginx" where FTS5 confirms nginx exists in apt,
system context is more useful than a generic "install package" pattern. For queries like
"compress this folder" where FTS5 finds nothing (no package named "compress" to look up),
ChromaDB retrieves the relevant `tar czf` pattern.

### Top-K Selection and Similarity Threshold

- **top_k = 5** for retrieval from ChromaDB. Of these, only entries with cosine distance
  `<= 0.35` (i.e. similarity >= 0.65) are injected into the prompt. Entries above the
  distance threshold are discarded.

- The ChromaDB query uses the `where` filter to optionally restrict to a domain if
  `analyze_intent()` has identified a domain-compatible verb (e.g. "start" or "stop" maps
  to `service-management`). This is a performance optimization for high-volume domains, not
  required for correctness.

- If zero entries pass the threshold, `rag_context_string` remains empty and the pipeline
  proceeds identically to the current free-generation mode.

### How Retrieved Entries Are Formatted for Prompt Injection

`SemanticRetriever.format_for_prompt(entries: list[SemanticEntry]) -> str` produces:

```
Relevant patterns from the semantic layer (use these if they match):

Pattern 1 (compression / tar):
  User intent: "create a gzip-compressed tar archive of a directory"
  Command pattern: tar czf {archive.tar.gz} {directory}
  Safety: safe (no sudo required)
  Undo: tar xf {archive.tar.gz}

Pattern 2 (compression / tar):
  User intent: "pack up this folder into a tarball"
  Command pattern: tar czf {archive.tar.gz} {directory}
  Safety: safe (no sudo required)
  Undo: tar xf {archive.tar.gz}

Pattern 3 (compression / zip):
  User intent: "create a zip archive of a directory"
  Command pattern: zip -r {archive.zip} {directory}
  Safety: safe (no sudo required)
  Undo: unzip {archive.zip}
```

Duplicate patterns (same `pattern` string, different phrasing) are collapsed. The
formatter deduplicates on the `pattern` field so the model sees at most 3 unique patterns
even if 5 phrases from the same intent cluster are retrieved.

---

## Section 3: Modified LLM Prompt Design

### Current CONVERSATIONAL_PROMPT Structure

The existing prompt (shell_propose.py lines 365–404) has:
- A role declaration
- A FORMAT instruction (two-part: explanation + COMMAND: sentinel)
- RULES section
- EXAMPLES section

### New CONVERSATIONAL_PROMPT with RAG Block

The RAG context is injected into the `user_prompt` (not the system prompt). This keeps the
system prompt stable across requests, which is important for models that cache the system
KV prefix. The user prompt gains a new optional preamble:

**Before (lines 517–521 of shell_propose.py):**
```python
user_prompt = f"Input: {natural_language}"
if context_string:
    user_prompt = f"{context_string}\n{user_prompt}"
if conversation_context:
    user_prompt = f"{conversation_context}\n\n{user_prompt}"
```

**After:**
```python
user_prompt = f"Input: {natural_language}"
if rag_context_string:
    user_prompt = f"{rag_context_string}\n{user_prompt}"
if context_string:
    user_prompt = f"{context_string}\n{user_prompt}"
if conversation_context:
    user_prompt = f"{conversation_context}\n\n{user_prompt}"
```

The RAG block is prepended before the system context string so the model sees: prior
conversation → system state → relevant patterns → the request. This ordering follows
"most general to most specific" — conversation history, then what is installed, then what
pattern to use, then the question.

### Updated CONVERSATIONAL_PROMPT System Instructions

The system prompt gains one additional RULE and an extended EXAMPLES section. The RULE
addition (inserted before the closing example block):

```
- If "Relevant patterns from the semantic layer" appears in the user prompt, prefer those
  patterns over generating a command from scratch. Fill the {parameter} placeholders with
  values from the user's request. Do not invent flags or subcommands not shown in the
  pattern.
```

No other change to the system prompt.

### Updated CONSTRAINED_FALLBACK_PROMPT

The fallback prompt (shell_propose.py lines 407–410) is used only when Attempt 1 completely
fails (exception or empty response). It changes to include the first retrieved pattern if
one exists:

```python
CONSTRAINED_FALLBACK_PROMPT = """Output exactly one line: COMMAND: <shell command>
If no command applies, output: COMMAND: NONE
{pattern_hint}
Task: {intent}"""
```

`{pattern_hint}` is populated with "Hint: the most likely pattern is: {pattern}" if a
high-confidence match exists (distance < 0.20), otherwise omitted. This helps the most
terse models (1–3B) still produce a correct command when the fallback triggers.

### Before/After Prompt Example

**BEFORE (current):**
```
Input: compress this directory before copying it
```

**AFTER (with RAG injection):**
```
Relevant patterns from the semantic layer (use these if they match):

Pattern 1 (compression / tar):
  User intent: "create a gzip-compressed tar archive of a directory"
  Command pattern: tar czf {archive.tar.gz} {directory}
  Safety: safe (no sudo required)
  Undo: tar xf {archive.tar.gz}

Pattern 2 (compression / zip):
  User intent: "create a zip archive of a directory"
  Command pattern: zip -r {archive.zip} {directory}
  Safety: safe (no sudo required)
  Undo: unzip {archive.zip}

Input: compress this directory before copying it
```

The model now has a bounded choice set (tar vs zip) and a concrete pattern to fill rather
than needing to recall flag syntax from weights.

### Safety Metadata Injection

The `safety_level` and `requires_sudo` fields from the top-matched entry are also passed
back through the `ProposalTrace`. Two new fields are added to `ProposalTrace`:

```python
rag_safety_level: str | None = None   # "safe" | "moderate" | "dangerous" | "blocked"
rag_undo: dict[str, str] | None = None  # undo paths from semantic entry
```

These are surfaced to the RPC response layer so the frontend can display the undo path
alongside the proposed command.

---

## Section 4: Safety Integration

### Pre-LLM: Blocked Pattern Fast-Reject

`blocked-patterns.yaml` contains 90+ patterns organized in categories
(filesystem-destruction, storage-destruction, etc.). Currently, `is_safe_command()` in
`shell_propose.py` (lines 332–358) hardcodes ~12 dangerous regex patterns inline and does
not reference `blocked-patterns.yaml`.

The new `SemanticBlockedPatternLoader` loads `blocked-patterns.yaml` at module import time
and compiles all patterns to a single list of `(regex, reason, category)` tuples. This
replaces the hardcoded patterns in `is_safe_command()`.

**New `is_safe_command()` implementation:**

```python
def is_safe_command(command: str) -> tuple[bool, str]:
    loader = _get_blocked_pattern_loader()  # cached singleton
    for pattern_re, reason, _category in loader.compiled_patterns:
        if re.search(pattern_re, command, re.IGNORECASE):
            return False, reason
    return True, ""
```

The `_get_blocked_pattern_loader()` is a module-level singleton cached after first load.
`blocked-patterns.yaml` is read once per process. Loading from YAML adds ~10ms of startup
time (acceptable — it is a 100-line file).

**This is a pure behavior-preserving refactor for the existing `is_safe_command()`.** The
hardcoded patterns in the current function are a subset of `blocked-patterns.yaml`. After
replacement, coverage increases from 12 hardcoded patterns to the full 90+ in the YAML.

### Post-LLM: Safety Level from Retrieved Entry

When a SemanticEntry is retrieved and its `safety_level` is `blocked`, the pipeline
short-circuits before the LLM call and returns a refuse response immediately. The logic is:

```python
if entries and entries[0].safety_level == "blocked":
    return ProposalTrace(
        message="That operation is blocked regardless of how it is phrased.",
        command=None,
        ...
    )
```

For `safety_level == "dangerous"`, the retrieved entry's `safety_level` is stored in the
trace and surfaced in the RPC response. The `converse.py` handler already maps dangerous
commands to `turn_type="danger"` via `SOFT_RISKY_PATTERNS`. The retrieved safety level
augments this: if the retrieved entry says `dangerous`, `is_risky` is forced to `True` in
the RPC response even if the generated command does not match a SOFT_RISKY_PATTERNS regex.

### Undo Path Surfacing

The `undo` dict from the retrieved semantic entry (e.g. `{"copy": "rm {destination}"}`) is
included in `ProposalTrace.rag_undo` and surfaced in the RPC response under a new
`undo_hint` field. The frontend displays this as a secondary action: "Undo: tar xf
{archive}" below the command card. This is display-only in Phase 4; it becomes actionable
("Undo" button calls `reos/execute` with the undo command) in a future phase.

---

## Section 5: Integration with Conversational Mode

The conversational shell (`rpc_handlers/converse.py`) calls
`propose_command_with_trace(natural_language, conversation_context=...)` at line 348. The
RAG integration is entirely inside `propose_command_with_trace()`, so the conversational
mode gets it automatically with no changes to `converse.py`.

One addition: the `ConverseTurn` dataclass in `benchmarks/runner.py` and the `converse.py`
response dict both gain a `rag_retrieved` boolean field (True if a semantic entry was
retrieved and injected). This is a diagnostic field for benchmarking the RAG contribution
specifically in the conversational pipeline.

Multi-turn context interacts with RAG as follows: the conversation context prefix is the
prior turn history; RAG context is the current-turn intent pattern. They are independent
injections into `user_prompt`. The ordering (conversation first, RAG second) ensures the
model can use prior turns to resolve pronouns ("it", "that service") before applying the
retrieved pattern.

---

## Section 6: Benchmark Integration

### New Benchmark Columns

The benchmark results table gains four new columns (added via a migration in
`benchmarks/db.py`):

| Column | Type | Description |
|--------|------|-------------|
| `rag_retrieved` | INTEGER (bool) | 1 if a semantic entry was retrieved |
| `rag_top_distance` | REAL | Cosine distance of the top-retrieved entry |
| `rag_pattern_used` | TEXT | The pattern string of the top entry |
| `rag_safety_level` | TEXT | Safety level from the retrieved entry |

### Extended ProposalTrace

`ProposalTrace` in `shell_propose.py` gains matching fields:

```python
rag_retrieved: bool = False
rag_top_distance: float | None = None
rag_pattern_used: str | None = None
rag_safety_level: str | None = None
rag_undo: dict[str, str] | None = None
```

`BenchmarkRunner._run_case()` in `benchmarks/runner.py` reads these from the trace and
populates the new DB columns.

### A/B Framework

The `BenchmarkRunner` gains a `--no-rag` flag (mirrors the existing `--no-context` flag).
When `--no-rag` is set, the `get_retriever()` call inside `propose_command_with_trace()`
is bypassed via an environment variable `REOS_RAG_DISABLED=1`. This allows running the
same corpus against the same model with and without RAG to isolate its contribution.

```bash
# Baseline (current behavior):
python -m benchmarks run --model qwen2.5:7b --no-rag

# RAG-augmented:
python -m benchmarks run --model qwen2.5:7b
```

Results from both runs share the same `model_name` but differ in `pipeline_mode`
(`"reactive"` vs `"reactive_rag"`). The `analysis.py` module gains an `--ab-compare` flag
that queries both modes for the same model and prints a delta table:

```
Model: qwen2.5:7b   Corpus: all 200 cases
                       Baseline     RAG    Delta
match_exact             64.5%      71.0%   +6.5%
match_fuzzy             73.0%      79.5%   +6.5%
safety_correct          91.0%      94.5%   +3.5%
latency_ms_p50            850       920     +70
latency_ms_p95           2100      2800    +700
tokens_prompt_1 (p50)     350       520    +170
attempt2_rate            18.0%     12.0%   -6.0%
```

### Metrics of Interest

1. **Accuracy improvement:** `match_exact` and `match_fuzzy` before/after RAG. The
   hypothesis is +5–15% on queries that map cleanly to semantic layer intents.

2. **Latency overhead:** ChromaDB query latency (target: <50ms on CPU), embedding latency
   via nomic-embed-text (target: <100ms), total overhead (target: <150ms). Both are
   measured separately in `ProposalTrace`.

3. **Token count change:** RAG injects ~200–400 tokens into the prompt. Models with 4K
   context windows may be affected. Benchmark measures `tokens_prompt_1` before/after.

4. **Attempt-2 rate reduction:** The hypothesis is that better first-attempt prompts reduce
   the rate at which the model falls through to `CONSTRAINED_FALLBACK_PROMPT`. This is
   tracked as `attempt2_rate` in analysis.

5. **Safety improvement:** `safety_correct` rate — specifically, dangerous commands that are
   correctly refused because the retrieved entry's `safety_level` is `blocked` or
   `dangerous`.

---

## Section 7: Implementation Phases

### Phase 1: ChromaDB Indexing Pipeline (offline, no pipeline changes)

**Goal:** Build a populated ChromaDB collection from `intent-index.yaml` and domain YAMLs.
The pipeline is untouched. This phase produces the infrastructure other phases use.

**Steps:**
1. Add `chromadb>=0.4.0` to `pyproject.toml` optional-dependencies under a new `[rag]`
   group (alongside the existing `semantic` group for `sentence-transformers`).
2. Create `src/reos/semantic_rag.py` with:
   - `SemanticEntry` dataclass
   - `SemanticLayerIndexer` class with `build()` method
   - `SemanticBlockedPatternLoader` class with lazy singleton
   - `SemanticRetriever` class with `retrieve()` and `format_for_prompt()` methods
   - `get_retriever()` module-level singleton factory
   - CLI entry point: `python -m reos.semantic_rag index`
3. Implement `SemanticLayerIndexer.build()`:
   - Parse `intent-index.yaml` (29,541 lines) to extract all 6,142 phrase entries
   - For each phrase, look up safety and undo from the corresponding domain YAML (build a
     per-domain cache keyed by command name)
   - Embed all phrases in batches of 64 via Ollama `/api/embeddings` with model
     `nomic-embed-text`
   - Upsert into ChromaDB collection `reos_intents`
   - Write manifest JSON
4. Write tests in `tests/test_semantic_rag.py`:
   - Test `SemanticLayerIndexer` against a small fixture YAML (no Ollama needed — mock the
     embedding call)
   - Test `SemanticBlockedPatternLoader` loads and compiles `blocked-patterns.yaml`
   - Test `format_for_prompt()` output format

**Files affected:**
- CREATE: `src/reos/semantic_rag.py`
- MODIFY: `pyproject.toml` (add `chromadb` to optional deps)
- CREATE: `tests/test_semantic_rag.py`

**Definition of Done:**
- [ ] `python -m reos.semantic_rag index` runs to completion with Ollama available
- [ ] ChromaDB collection `reos_intents` exists at `~/.reos-data/chromadb/`
- [ ] Collection contains >= 6,000 documents
- [ ] Manifest JSON written correctly
- [ ] Re-running index on unchanged YAMLs skips all domains (hash match)
- [ ] Re-running after editing one domain YAML re-indexes only that domain
- [ ] Unit tests pass without Ollama

---

### Phase 2: Retrieval Integration into Propose Pipeline

**Goal:** `propose_command_with_trace()` calls ChromaDB at query time. RAG context injected
into user prompt. Pipeline still produces the same `ProposalTrace` type.

**Steps:**
1. Add `_build_embed_query()` helper function to `shell_propose.py`
2. Add RAG retrieval block inside `propose_command_with_trace()` after line 513 (context
   gathering), before line 517 (user_prompt assembly)
3. Extend `user_prompt` assembly to prepend `rag_context_string` if non-empty
4. Add `rag_retrieved`, `rag_top_distance`, `rag_pattern_used`, `rag_safety_level`,
   `rag_undo` fields to `ProposalTrace` dataclass
5. Add `REOS_RAG_DISABLED` env-var check to allow bypassing retrieval
6. Wire new `ProposalTrace` fields through `BenchmarkRunner._run_case()` in
   `benchmarks/runner.py`
7. Add migration for new benchmark DB columns in `benchmarks/db.py`

**Files affected:**
- MODIFY: `src/reos/shell_propose.py` (lines 475–590 area)
- MODIFY: `benchmarks/runner.py` (new fields in `_run_case()`)
- MODIFY: `benchmarks/db.py` (schema migration)

**Definition of Done:**
- [ ] `propose_command_with_trace()` calls `get_retriever().retrieve()` when FTS5 finds
      nothing and `REOS_RAG_DISABLED` is not set
- [ ] `ProposalTrace` carries `rag_retrieved`, `rag_top_distance`, `rag_pattern_used`
- [ ] Pipeline falls through gracefully if ChromaDB unavailable (collection missing,
      Ollama embedding endpoint down)
- [ ] No existing test suite failures introduced
- [ ] Benchmark runner captures new RAG columns

---

### Phase 3: Prompt Redesign with Semantic Grounding

**Goal:** The LLM prompt is updated to instruct the model to prefer retrieved patterns.
The CONSTRAINED_FALLBACK_PROMPT gains a pattern hint. The system prompt gains one rule.

**Steps:**
1. Add one instruction to `CONVERSATIONAL_PROMPT` (the "prefer retrieved patterns" rule)
2. Update `CONSTRAINED_FALLBACK_PROMPT` to accept a `{pattern_hint}` substitution
3. Update the `CONSTRAINED_FALLBACK_PROMPT.format(...)` call in `propose_command_with_trace()`
   to inject the pattern hint when a high-confidence entry exists
4. Run benchmark A/B comparison: `--no-rag` vs RAG on `qwen2.5:7b` and `llama3.2:3b`
5. Analyze attempt-2 rate reduction and match_exact improvement

**Files affected:**
- MODIFY: `src/reos/shell_propose.py` (prompt string constants and format call)
- No new files

**Definition of Done:**
- [ ] `CONVERSATIONAL_PROMPT` contains the pattern-preference rule
- [ ] Benchmark A/B shows `match_exact` improvement >= 3% on 7B model
- [ ] Benchmark A/B shows `attempt2_rate` reduction >= 2% on 3B model
- [ ] No regression on cases where no RAG entry is retrieved (fallback behavior preserved)

---

### Phase 4: Safety Layer Augmentation

**Goal:** `is_safe_command()` is refactored to load from `blocked-patterns.yaml`. Retrieved
entry safety level augments RPC response. Undo paths are surfaced.

**Steps:**
1. Implement `SemanticBlockedPatternLoader` in `semantic_rag.py` (may already exist from
   Phase 1)
2. Refactor `is_safe_command()` in `shell_propose.py` to use the loader's compiled patterns
   instead of the hardcoded list
3. Add `undo_hint` field to `handle_reos_propose()` response dict in
   `src/reos/rpc_handlers/propose.py`
4. Add `undo_hint` field to `handle_reos_converse()` response dict in
   `src/reos/rpc_handlers/converse.py`
5. Verify existing `test_is_safe_command` tests still pass (the hardcoded patterns are a
   subset of the YAML — no regression expected)
6. Add test cases for newly-covered patterns from `blocked-patterns.yaml` that were not
   in the original hardcoded list

**Files affected:**
- MODIFY: `src/reos/shell_propose.py` (is_safe_command function)
- MODIFY: `src/reos/rpc_handlers/propose.py` (undo_hint in response)
- MODIFY: `src/reos/rpc_handlers/converse.py` (undo_hint in response)
- MODIFY (as needed): `src/reos/semantic_rag.py` (if loader wasn't complete in Phase 1)

**Definition of Done:**
- [ ] `is_safe_command()` loads from `blocked-patterns.yaml`, not hardcoded list
- [ ] All patterns from the original hardcoded list are present in `blocked-patterns.yaml`
      (verify by cross-referencing before removing hardcoded list)
- [ ] `reos/propose` and `reos/converse` responses include `undo_hint` when available
- [ ] All existing safety tests pass
- [ ] Safety coverage increased: tests for at least 10 patterns from the YAML not in the
      old hardcoded list

---

### Phase 5: Benchmark Comparison

**Goal:** Run the full benchmark matrix (or a targeted subset) with and without RAG to
measure the improvement quantitatively.

**Steps:**
1. Run baseline: `python -m benchmarks run --model qwen2.5:7b --no-rag`
2. Run RAG: `python -m benchmarks run --model qwen2.5:7b`
3. Run baseline and RAG for `llama3.2:3b` (smallest practical model — most to gain)
4. Run `python -m benchmarks analysis --ab-compare --model qwen2.5:7b` and
   `--model llama3.2:3b`
5. Review delta table. If `match_exact` improvement is >= 5%, proceed to Phase 6.
6. If improvement is < 3%, investigate: run `python -m benchmarks analysis --rag-coverage`
   to measure what fraction of test cases received a RAG injection (low coverage = too few
   semantic layer intents matching the test corpus; answer is to expand the semantic layer).

**Files affected:**
- MODIFY: `benchmarks/runner.py` (add `--no-rag` flag and `pipeline_mode="reactive_rag"`)
- MODIFY: `benchmarks/analysis.py` (add `--ab-compare`, `--rag-coverage` flags)

**Definition of Done:**
- [ ] Baseline and RAG runs complete for at least qwen2.5:7b and llama3.2:3b
- [ ] A/B comparison table generated
- [ ] Results documented in a benchmark session note

---

### Phase 6: Conversational Mode Integration

**Goal:** Verify the conversational pipeline (`reos/converse`) benefits from RAG
automatically and run the `ConversationalBenchmarkRunner` A/B comparison.

**Steps:**
1. Verify `handle_reos_converse()` passes through the RAG fields (it already calls
   `propose_command_with_trace()` at line 348 of `converse.py` — if Phase 2 is complete,
   no code change is needed)
2. Extend `ConverseTurn` dataclass in `benchmarks/runner.py` with `rag_retrieved: bool`
3. Extend `ConversationalBenchmarkRunner._call_pipeline()` to capture `rag_retrieved` from
   the provider (via a new attribute on `InstrumentedOllamaProvider` or by reading it from
   the handler result)
4. Run `ConversationalBenchmarkRunner` A/B: with and without RAG on conversational corpus
5. Verify that multi-turn context + RAG injection coexist without prompt length overflow on
   7B models (count tokens; check against model context window)

**Files affected:**
- MODIFY: `benchmarks/runner.py` (`ConverseTurn` dataclass, `_call_pipeline()`)
- Likely no changes to `src/reos/rpc_handlers/converse.py` (RAG is transparent)

**Definition of Done:**
- [ ] `ConversationalBenchmarkRunner` captures `rag_retrieved` per case
- [ ] A/B comparison run for conversational pipeline
- [ ] No context-window overflow observed for 7B models with combined multi-turn + RAG
      context (max ~600 tokens combined)

---

## Section 8: Risk Analysis and Mitigations

### Risk 1: Embedding Quality for Terse Intent Strings

**Problem:** `analyze_intent("ls")` extracts `intent_verb=None, intent_target=None` because
"ls" is a bare command, not natural language. The embed query falls back to the raw string
"ls", which produces a reasonable embedding, but very short (1–2 word) inputs may retrieve
semantically distant results.

**Mitigation:** The similarity threshold (cosine distance <= 0.35) acts as the primary
gate. If the embedding of "ls" is too far from any stored intent, no RAG context is
injected and the pipeline degrades to free-generation. No incorrect grounding is injected.
An additional mitigation: if `intent_verb` is None (no verb extracted), skip ChromaDB
retrieval entirely — terse command inputs suggest the user already knows what they want and
doesn't need pattern guidance.

**Residual risk:** Low. The worst case is "no RAG injection" which is the current baseline.

---

### Risk 2: ChromaDB Cold-Start Latency

**Problem:** ChromaDB initializes its in-process SQLite + HNSW index on first query. On a
machine with a large collection (6,142 documents), this takes 200–500ms. Every process
restart incurs this cost.

**Mitigation:** `get_retriever()` is a module-level singleton. The ChromaDB client is
initialized once and cached for the process lifetime. The first query in a session pays the
cold-start cost; subsequent queries are fast (<20ms). For the benchmark runner, the
retriever is initialized in `_init_run()`, before the first case, so the cold-start is
absorbed by the model pull time (which takes seconds).

**Latency budget:** Target is <150ms total overhead per query (embedding + ChromaDB lookup).
If the cold-start penalty exceeds this for the first query in a session, log a warning but
do not block the response.

---

### Risk 3: LLM Ignoring Retrieved Patterns

**Problem:** Small 3B models may ignore the RAG context block and generate commands freely
anyway, producing the same output as before. The RULE addition to `CONVERSATIONAL_PROMPT`
helps, but does not guarantee compliance.

**Mitigation:** The benchmark A/B comparison in Phase 5 directly measures compliance — if
`match_exact` improves, the model is using the patterns. If it does not improve on 3B
models, the `CONSTRAINED_FALLBACK_PROMPT` pattern hint (Phase 3) provides a second
injection point in a simpler format that small models are more likely to follow.

A secondary mitigation: for cases where the retrieved entry has distance < 0.15 (very high
confidence match), the pattern can be pre-filled into the command field as a default
proposal. This is a Phase 3+ extension that bypasses the LLM entirely for the highest-
confidence matches. This is not planned for Phases 1–4 but is architecturally supported by
the data flow.

---

### Risk 4: Queries That Don't Match Any Semantic Entry

**Problem:** The semantic layer covers 267 commands and 16 domains. Real user queries will
include commands outside these domains (e.g., application-specific CLIs like `kubectl`,
`terraform`, `cargo`). ChromaDB will return results, but they will all be below the
similarity threshold and no RAG context will be injected.

**Mitigation:** This is the desired behavior. The threshold ensures that low-quality matches
do not inject misleading patterns. The pipeline falls through to free-generation, which
already handles these cases. No behavior regression.

**Future work:** The semantic layer can be expanded incrementally (e.g., add a
`container-orchestration` domain covering `kubectl`). Each expansion automatically improves
RAG coverage for that domain.

---

### Risk 5: Ollama Embedding Endpoint Availability

**Problem:** `nomic-embed-text` must be pulled and available in Ollama. If Ollama is not
running, the embedding call fails. If `nomic-embed-text` is not pulled, the first embed
call fails.

**Mitigation:** All retrieval calls are wrapped in `try/except Exception: pass` with
fail-open behavior (same pattern as context gathering in lines 502–513 of
`shell_propose.py`). If the embedding fails, `rag_context_string` stays empty and the
pipeline continues unchanged.

For the indexing pipeline (`python -m reos.semantic_rag index`), the CLI exits with an
error message if Ollama is unavailable — this is acceptable since indexing is an offline
step.

**Index build dependency:** The `nomic-embed-text` model must be pulled before indexing:
`ollama pull nomic-embed-text`. The CLI command will check and prompt if absent.

---

### Risk 6: ChromaDB Dependency Weight

**Problem:** `chromadb` is a non-trivial dependency (~30MB installed). Adding it to the
base `dependencies` list in `pyproject.toml` forces it on all ReOS users including those
running minimal setups.

**Mitigation:** ChromaDB goes into `[project.optional-dependencies]` under a new `rag`
group. Base ReOS install does not include it. The `get_retriever()` singleton checks for
the import at call time and falls through gracefully if `chromadb` is not installed. To
enable RAG: `pip install reos[rag]`.

**Note:** The existing `system_index.py` already uses this pattern for `sentence-
transformers` (optional `semantic` group). The same convention applies here.

---

### Risk 7: intent-index.yaml Divergence from Domain YAMLs

**Problem:** `intent-index.yaml` is described as "derived from domain files" in the README
but is checked in as a separate file. If domain files are updated without regenerating
the index, the two diverge. The indexer must resolve safety and undo metadata from the
domain YAMLs (the index only has `pattern`, not safety or undo).

**Mitigation:** `SemanticLayerIndexer.build()` loads both sources: `intent-index.yaml` for
phrase enumeration (it is the canonical phrase corpus) and the domain YAMLs for safety and
undo metadata keyed on `(domain, command)`. If a domain YAML is missing a command entry
that appears in the index, the indexer logs a warning and uses `safety_level="safe"` as a
conservative default (rather than crashing).

The hash manifest is based on both `intent-index.yaml` and each domain YAML file. If either
changes, the affected domain's phrases are re-indexed.

---

## Files Affected

### New Files

| File | Purpose |
|------|---------|
| `src/reos/semantic_rag.py` | Core RAG module: indexer, retriever, blocked-pattern loader, CLI |
| `tests/test_semantic_rag.py` | Unit tests for semantic_rag.py (no Ollama required) |

### Modified Files

| File | Change | Specific Location |
|------|--------|-------------------|
| `src/reos/shell_propose.py` | Add RAG retrieval block; extend ProposalTrace; update prompt assembly; refactor is_safe_command() | After line 513 (retrieval block); lines 59–111 (ProposalTrace); lines 517–521 (prompt assembly); lines 332–358 (is_safe_command) |
| `src/reos/rpc_handlers/propose.py` | Add `undo_hint` to response dict | After line 121 |
| `src/reos/rpc_handlers/converse.py` | Add `undo_hint` to response dict | After line 430 |
| `benchmarks/runner.py` | Add `rag_*` fields to `_run_case()`; add `--no-rag` flag; extend `ConverseTurn` | `_run_case()` around line 395; `ConverseTurn` dataclass around line 38 |
| `benchmarks/db.py` | Schema migration for new RAG columns | Migration function |
| `benchmarks/analysis.py` | Add `--ab-compare` and `--rag-coverage` flags | New analysis functions |
| `pyproject.toml` | Add `chromadb` to optional deps under `[rag]` group | `[project.optional-dependencies]` |

### Unmodified (Intentionally)

| File | Reason |
|------|--------|
| `src/reos/shell_context.py` | FTS5 routing logic already correct; `search_fts5()` stays unchanged |
| `src/reos/rpc_handlers/converse.py` (logic) | RAG is transparent via `propose_command_with_trace()` |
| `semantic-layer/` YAML files | Read-only inputs to the indexer |
| `src/reos/system_index.py` | Existing sentence-transformer/FTS5 embedding for packages untouched |

---

## Decision Log

### Decision 1: nomic-embed-text via Ollama

**Chosen because:** Already in the stack (Ollama is the existing LLM backend). Local
execution, no new infrastructure, good quality for English text. The existing `system_index.py`
uses `sentence-transformers/all-MiniLM-L6-v2` for package embeddings — nomic-embed-text
is a better model and runs through the same Ollama endpoint the inference model uses.

**Alternative considered:** `sentence-transformers/all-MiniLM-L6-v2` via the Python library
(already partially integrated in `system_index.py`). Rejected because it requires loading a
22MB model into the process; `nomic-embed-text` via Ollama offloads that to the existing
Ollama process and produces higher-quality embeddings.

### Decision 2: ChromaDB alongside SQLite FTS5

**Chosen because:** ChromaDB provides persistent vector storage with HNSW indexing, clean
Python API, and supports Ollama embedding functions natively. FTS5 stays for system package
lookup (it searches installed packages and desktop apps — a different corpus entirely). The
two systems are complementary, not competing.

**Alternative considered:** Pure SQLite BLOB storage for embeddings (already used in
`system_index.py` for package embeddings). Rejected because cosine similarity search over
6,142 BLOBs requires loading all embeddings into memory and computing distances in NumPy —
O(n) per query. ChromaDB's HNSW index is O(log n). At 6,142 documents the difference is
~5ms vs ~50ms, which matters for a 150ms latency budget.

### Decision 3: Insertion point after parse_intent(), before LLM call

**Chosen because:** Embedding the cleaned `intent_verb + intent_target` string produces a
better retrieval signal than embedding raw user input. "compress this folder before copying
it" embeds similarly to "compress folder" — the cleanup reduces noise. The insertion point
(after line 513 in `shell_propose.py`) is where system context is already gathered, so
the intent has been extracted and system state is known.

**Alternative considered:** Inserting before context gathering (embed raw input, then do
system lookup). Rejected because raw input contains more noise (articles, context words,
filler). The extracted intent is the cleaner embedding target.

---

## Confidence Assessment

**High confidence (>85%):**
- Phase 1 (indexing pipeline): all components are well-understood. ChromaDB + Ollama
  embedding is a solved integration.
- Phase 2 (retrieval integration): the insertion point in `propose_command_with_trace()` is
  clean. The fail-open pattern is already established in the codebase.
- Phase 4 (blocked-patterns refactor): purely mechanical. The YAML covers the existing
  hardcoded patterns.

**Medium confidence (60–75%):**
- Phase 3 (prompt redesign): LLM compliance with "prefer retrieved patterns" instruction
  varies by model size and temperature. The benchmark in Phase 5 will reveal whether the
  instruction is effective or whether a more forceful prompt (e.g. structured JSON output)
  is needed for smaller models.
- Phase 5 (benchmark results): the magnitude of improvement is uncertain. The hypothesis of
  +5–15% on match_exact is plausible but depends on semantic layer coverage of the test
  corpus.

**Unknowns requiring validation before Phase 2 implementation:**

1. **ChromaDB version compatibility** with the version of Python 3.12 used by the project.
   The PyPI `chromadb>=0.4.0` constraint should be tested before committing.

2. **nomic-embed-text availability** on the target machine. The CLI tool must handle the
   case where `ollama list` does not include `nomic-embed-text` and provide a clear
   pull instruction.

3. **intent-index.yaml parsing correctness.** The file is 29,541 lines of YAML. A single
   malformed entry stops the build. The indexer must implement error recovery (log and
   skip malformed entries, not crash).

4. **Context window budget** for 3B models with combined RAG block + conversation history
   + system context. Estimate: RAG block (~400 tokens) + conversation history (~300 tokens)
   + system context (~100 tokens) + user prompt (~50 tokens) = ~850 tokens. Most 3B models
   support 4K context, so this is within budget. Verify empirically in Phase 5.
