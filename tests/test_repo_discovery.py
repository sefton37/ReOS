from __future__ import annotations

from pathlib import Path

from reos.repo_discovery import RepoDiscoveryConfig, discover_git_repos


def test_discover_git_repos_finds_repo(tmp_path: Path) -> None:
    repo = tmp_path / "myrepo"
    (repo / ".git").mkdir(parents=True)

    found = discover_git_repos(RepoDiscoveryConfig(roots=[tmp_path], max_depth=3))
    assert repo in found


def test_discover_git_repos_respects_depth(tmp_path: Path) -> None:
    deep = tmp_path / "a" / "b" / "c" / "d" / "e"
    (deep / ".git").mkdir(parents=True)

    found = discover_git_repos(RepoDiscoveryConfig(roots=[tmp_path], max_depth=3))
    assert deep not in found

    found2 = discover_git_repos(RepoDiscoveryConfig(roots=[tmp_path], max_depth=6))
    assert deep in found2
