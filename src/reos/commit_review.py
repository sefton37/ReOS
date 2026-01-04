"""Commit review using local LLM (OPTIONAL - M5 Roadmap Feature).

⚠️  GIT INTEGRATION FEATURE - DISABLED BY DEFAULT ⚠️

REQUIRES: settings.git_integration_enabled = True
Enable via: REOS_GIT_INTEGRATION_ENABLED=true

Provides Ollama-powered code review for git commits.
Reads commit patches and provides analysis/suggestions.

Core ReOS functionality (natural language Linux control) does NOT require this.
This is an optional developer workflow feature for M5 roadmap.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .alignment import get_commit_patch, get_commit_subject
from .ollama import OllamaClient


@dataclass(frozen=True)
class CommitReviewInput:
    repo_path: Path
    commit_sha: str


class CommitReviewer:
    def __init__(self, *, client: OllamaClient | None = None) -> None:
        self._client = client or OllamaClient()

    def review(self, inp: CommitReviewInput) -> str:
        subject = get_commit_subject(inp.repo_path, commit_sha=inp.commit_sha)
        patch = get_commit_patch(inp.repo_path, commit_sha=inp.commit_sha)

        system = (
            "You are ReOS, a local-first code reviewer.\n"
            "You review a single git commit patch.\n\n"
            "Rules:\n"
            "- Be specific and technical; reference file paths and lines from the diff when possible.\n"
            "- Identify correctness bugs, edge cases, security issues, and maintainability risks.\n"
            "- Suggest concrete improvements and tests.\n"
            "- If a change is fine, say so briefly and move on.\n"
            "- Do not moralize; keep the tone neutral and helpful.\n"
        )

        user = (
            f"Repo: {inp.repo_path}\n"
            f"Commit: {inp.commit_sha}\n"
            f"Subject: {subject}\n\n"
            "Review this commit patch:\n"
            "---\n"
            f"{patch}\n"
        )

        return self._client.chat_text(system=system, user=user, timeout_seconds=120.0)
