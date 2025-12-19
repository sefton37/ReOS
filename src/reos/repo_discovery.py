"""Local git repository discovery.

ReOS is Git-first. This module discovers git repositories on disk by looking for
`.git` directories within a bounded set of roots.

Discovery is metadata-only and stays local.

Design goals:
- Avoid "full disk" scanning by default (consent + transparency matter).
- Be fast enough to run on a timer in the GUI without freezing.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .settings import settings


@dataclass(frozen=True)
class RepoDiscoveryConfig:
    roots: list[Path]
    max_depth: int = 5
    max_repos: int = 200


def default_repo_scan_roots() -> list[Path]:
    """Return default roots for repo discovery.

    Conservative defaults: common dev directories + the ReOS workspace root.
    """

    home = Path.home()
    candidates = [
        home / "dev",
        home / "projects",
        settings.root_dir,
    ]

    roots: list[Path] = []
    for path in candidates:
        try:
            if path.exists() and path.is_dir():
                roots.append(path)
        except OSError:
            continue

    # Deduplicate while preserving order.
    unique: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        resolved = root.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        unique.append(resolved)

    return unique


def _should_skip_dir(name: str) -> bool:
    if not name:
        return True

    # Do not skip `.git` here; we need to detect it to identify repo roots.
    # We still avoid traversing into it in `discover_git_repos`.
    if name in {".venv", "__pycache__", "node_modules"}:
        return True

    # Skip hidden directories (keeps scanning bounded + avoids surprises).
    if name.startswith(".") and name != ".git":
        return True

    return False


def discover_git_repos(config: RepoDiscoveryConfig | None = None) -> list[Path]:
    """Discover git repositories by scanning for `.git` directories.

    Returns repo root paths.
    """

    cfg = config or RepoDiscoveryConfig(roots=default_repo_scan_roots())

    repos: list[Path] = []
    seen: set[Path] = set()

    for root in cfg.roots:
        try:
            root = root.resolve()
        except OSError:
            continue

        if not root.exists() or not root.is_dir():
            continue

        for dirpath, dirnames, _filenames in os.walk(root, topdown=True):
            try:
                current = Path(dirpath)
            except OSError:
                continue

            try:
                rel = current.relative_to(root)
                depth = len(rel.parts)
            except ValueError:
                depth = cfg.max_depth + 1

            if depth > cfg.max_depth:
                dirnames[:] = []
                continue

            # Prune directories we don't want to traverse.
            dirnames[:] = [d for d in dirnames if not _should_skip_dir(d)]

            if ".git" in dirnames:
                repo_root = current
                if repo_root not in seen:
                    repos.append(repo_root)
                    seen.add(repo_root)
                    if len(repos) >= cfg.max_repos:
                        return repos

                # Don't walk into git internals.
                dirnames[:] = [d for d in dirnames if d != ".git"]

    return repos
