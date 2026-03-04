from __future__ import annotations

from pathlib import Path

import pytest

from reos.mcp_server import _safe_repo_path


def test_safe_repo_path_allows_in_repo(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    p = _safe_repo_path(repo.resolve(), "src/app.py")
    assert str(p).endswith("/repo/src/app.py")


def test_safe_repo_path_blocks_escape(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

    with pytest.raises(Exception):
        _safe_repo_path(repo.resolve(), "../secrets.txt")
