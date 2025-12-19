## ReOS Testing Strategy (Local-First, Git-First)

### Goals

- Protect the **local-first + metadata-first** privacy contract.
- Keep tests deterministic and fast (prefer in-process + temp resources).
- Cover the real seams: Git subprocess, SQLite persistence, trigger heuristics, FastAPI contract, MCP sandboxing, agent policy.

### Principles

- **No cloud calls in tests**. Network boundaries (Ollama/httpx) are mocked.
- **No workspace state coupling**. Tests must not read/write `.reos-data/`.
- **Metadata-first default** is enforced by tests (diffs only with explicit opt-in).

### Test Pyramid

1) Unit tests (fast)
- Pure logic (parsing, heuristics, schema/serialization).
- Allowed resources: `tmp_path`, in-memory/simple temp DB.

2) Integration tests (local-only)
- Real temp git repos (`git init` in `tmp_path`).
- Real temp SQLite DBs (file-backed in `tmp_path`).
- Validate end-to-end seams: `get_git_summary`, `analyze_alignment`, `append_event` triggers.

3) Contract tests
- FastAPI endpoints using `TestClient` with isolated DB singleton.
- MCP JSON-RPC request/response mapping + sandboxing behavior.

4) GUI smoke tests (optional)
- Instantiate key widgets headless (`QT_QPA_PLATFORM=offscreen`).
- No pixel assertions; just “does it start” and “no crash”.

### Fixtures to Standardize

- `isolated_db_singleton`: replaces `reos.db._db_instance` with a temp DB for the duration of the test.
- `temp_git_repo`: initializes a temp git repo with minimal `docs/tech-roadmap.md` + `ReOS_charter.md` committed.
- `run_git(repo, args)`: helper for git subprocess calls.

### What to Mock vs Use Real

- **Use real**: `git` CLI against temp repos; SQLite against temp files.
- **Mock**: `httpx` (Ollama), time when needed, and any UI externalities.

### Priority Backlog

1) Temp git repo integration tests for alignment + summary.
2) Storage trigger integration tests (review_trigger + cooldown).
3) Agent policy tests: enforce diff opt-in, tool call limits, fallback on invalid JSON.
4) API tests isolated from `.reos-data`.
5) MCP protocol-level tests.
