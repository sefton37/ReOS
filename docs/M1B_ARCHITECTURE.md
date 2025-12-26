# M1b Architecture (Git Companion)

M1b pivots ReOS to be a companion to **Git**, not a companion to a specific editor.

## Core Loop

- ReOS polls the configured repo (local-only):
  - `git status --porcelain`
  - `git diff --stat`
  - `git diff --numstat`
- Stores `git_poll` events in SQLite.
- Uses alignment analysis on-demand (e.g., during reviews) rather than emitting automatic drift/thread checkpoint events.
- Emits throttled checkpoint events:
  - `review_trigger` (context budget pressure)

## Data Boundaries

- Default is metadata-first.
- Including diff text for the LLM is an explicit opt-in.
- All data stays local; no cloud calls.

## UI

- Left nav shows repo state (branch, changed files count, diffstat).
- Center chat shows gentle checkpoint prompts.
- Right inspection pane will show full reasoning trails (M3).
