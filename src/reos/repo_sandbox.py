"""Repository path sandboxing (OPTIONAL - M5 Roadmap Feature).

⚠️  GIT INTEGRATION FEATURE - DISABLED BY DEFAULT ⚠️

REQUIRES: settings.git_integration_enabled = True

Provides path validation to prevent directory traversal attacks when
accessing files within git repositories.

Core ReOS functionality does NOT require this module.
"""

from __future__ import annotations

from pathlib import Path


class RepoSandboxError(RuntimeError):
    pass


def safe_repo_path(repo_root: Path, rel_path: str) -> Path:
    """Resolve a relative path safely inside a repo root.

    Prevents `..` escapes and absolute paths.
    """

    rel_path = rel_path.strip().lstrip("/")
    if not rel_path:
        raise RepoSandboxError("path is required")

    candidate = (repo_root / rel_path).resolve()

    try:
        candidate.relative_to(repo_root)
    except ValueError as exc:
        raise RepoSandboxError(f"Path escapes repo root: {rel_path}") from exc

    return candidate
