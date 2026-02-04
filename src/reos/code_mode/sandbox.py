"""Sandboxed file operations within an Act's assigned repository.

All file operations are restricted to the assigned repo path, preventing
directory traversal attacks and ensuring Code Mode stays within its bounds.
"""

from __future__ import annotations

import fnmatch
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from reos.security import is_command_safe


class CodeSandboxError(RuntimeError):
    """Error raised when a sandboxed operation fails or is disallowed."""

    pass


@dataclass
class WriteResult:
    """Result of a write or create operation."""

    path: str
    backup_path: str | None = None
    created: bool = False
    bytes_written: int = 0


@dataclass
class EditResult:
    """Result of an edit operation."""

    path: str
    backup_path: str | None = None
    replacements: int = 0
    original_content: str = ""
    new_content: str = ""


@dataclass
class DeleteResult:
    """Result of a delete operation."""

    path: str
    backup_path: str | None = None
    was_directory: bool = False


@dataclass
class GrepMatch:
    """A single grep match."""

    path: str
    line_number: int
    line_content: str
    match_start: int = 0
    match_end: int = 0


@dataclass
class GitStatus:
    """Git repository status."""

    clean: bool
    branch: str
    staged: list[str] = field(default_factory=list)
    modified: list[str] = field(default_factory=list)
    untracked: list[str] = field(default_factory=list)
    ahead: int = 0
    behind: int = 0


@dataclass
class Commit:
    """A git commit."""

    sha: str
    message: str
    author: str
    timestamp: datetime
    files_changed: int = 0


class CodeSandbox:
    """Sandboxed file operations within an Act's assigned repository.

    All paths are validated to prevent escapes outside the repo root.
    File modifications create backups before changes.
    """

    def __init__(self, repo_path: Path | str) -> None:
        """Initialize sandbox with repository root path.

        Args:
            repo_path: Absolute path to the git repository root.

        Raises:
            CodeSandboxError: If path doesn't exist or isn't a git repo.
        """
        self.repo_path = Path(repo_path).resolve()
        self._validate_is_git_repo()
        self._backup_dir = self.repo_path / ".reos_backups"

    def _validate_is_git_repo(self) -> None:
        """Verify the path is a valid git repository."""
        if not self.repo_path.exists():
            raise CodeSandboxError(f"Path does not exist: {self.repo_path}")
        if not self.repo_path.is_dir():
            raise CodeSandboxError(f"Path is not a directory: {self.repo_path}")
        git_dir = self.repo_path / ".git"
        if not git_dir.exists():
            raise CodeSandboxError(f"Not a git repository: {self.repo_path}")

    def _safe_path(self, rel_path: str) -> Path:
        """Resolve path safely, preventing escapes outside repo root.

        Args:
            rel_path: Relative path within the repository.

        Returns:
            Resolved absolute path guaranteed to be within repo_path.

        Raises:
            CodeSandboxError: If path would escape the repo root.
        """
        # Strip leading slashes and whitespace
        rel_path = rel_path.strip().lstrip("/")

        if not rel_path:
            raise CodeSandboxError("Path is required")

        # Reject obviously dangerous patterns
        if ".." in rel_path.split(os.sep):
            raise CodeSandboxError(f"Path contains illegal '..': {rel_path}")

        candidate = (self.repo_path / rel_path).resolve()

        # Verify the resolved path is within repo_path
        try:
            candidate.relative_to(self.repo_path)
        except ValueError as exc:
            raise CodeSandboxError(f"Path escapes repo root: {rel_path}") from exc

        return candidate

    def _create_backup(self, path: Path) -> str | None:
        """Create a backup of a file before modification.

        Args:
            path: Absolute path to the file to backup.

        Returns:
            Relative path to backup file, or None if file doesn't exist.
        """
        if not path.exists():
            return None

        self._backup_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
        rel_path = path.relative_to(self.repo_path)
        backup_name = f"{rel_path.as_posix().replace('/', '_')}_{timestamp}.bak"
        backup_path = self._backup_dir / backup_name

        shutil.copy2(path, backup_path)

        return str(backup_path.relative_to(self.repo_path))

    # =========================================================================
    # File Operations
    # =========================================================================

    def read_file(
        self, path: str, start: int = 1, end: int | None = None
    ) -> str:
        """Read file contents.

        Args:
            path: Relative path to file within repo.
            start: Starting line number (1-indexed, inclusive).
            end: Ending line number (inclusive), or None for all remaining.

        Returns:
            File contents as string.

        Raises:
            CodeSandboxError: If file doesn't exist or path escapes repo.
        """
        safe = self._safe_path(path)

        if not safe.exists():
            raise CodeSandboxError(f"File not found: {path}")
        if safe.is_dir():
            raise CodeSandboxError(f"Path is a directory: {path}")

        content = safe.read_text(encoding="utf-8")

        if start > 1 or end is not None:
            lines = content.splitlines(keepends=True)
            # Convert to 0-indexed
            start_idx = max(0, start - 1)
            end_idx = end if end is not None else len(lines)
            content = "".join(lines[start_idx:end_idx])

        return content

    def write_file(
        self, path: str, content: str, backup: bool = True
    ) -> WriteResult:
        """Write content to a file (create or overwrite).

        Args:
            path: Relative path to file within repo.
            content: Content to write.
            backup: If True, create backup before overwriting existing file.

        Returns:
            WriteResult with operation details.

        Raises:
            CodeSandboxError: If path escapes repo.
        """
        safe = self._safe_path(path)
        created = not safe.exists()

        backup_path = None
        if backup and safe.exists():
            backup_path = self._create_backup(safe)

        # Create parent directories if needed
        safe.parent.mkdir(parents=True, exist_ok=True)

        safe.write_text(content, encoding="utf-8")

        return WriteResult(
            path=path,
            backup_path=backup_path,
            created=created,
            bytes_written=len(content.encode("utf-8")),
        )

    def create_file(self, path: str, content: str) -> WriteResult:
        """Create a new file (fails if exists).

        Args:
            path: Relative path to file within repo.
            content: Content to write.

        Returns:
            WriteResult with operation details.

        Raises:
            CodeSandboxError: If file already exists or path escapes repo.
        """
        safe = self._safe_path(path)

        if safe.exists():
            raise CodeSandboxError(f"File already exists: {path}")

        # Create parent directories if needed
        safe.parent.mkdir(parents=True, exist_ok=True)

        safe.write_text(content, encoding="utf-8")

        return WriteResult(
            path=path,
            backup_path=None,
            created=True,
            bytes_written=len(content.encode("utf-8")),
        )

    def edit_file(
        self,
        path: str,
        old_str: str,
        new_str: str,
        backup: bool = True,
        replace_all: bool = False,
    ) -> EditResult:
        """Edit file by replacing text.

        Args:
            path: Relative path to file within repo.
            old_str: Text to find and replace.
            new_str: Replacement text.
            backup: If True, create backup before editing.
            replace_all: If True, replace all occurrences; otherwise replace first only.

        Returns:
            EditResult with operation details.

        Raises:
            CodeSandboxError: If file doesn't exist, old_str not found, or path escapes repo.
        """
        safe = self._safe_path(path)

        if not safe.exists():
            raise CodeSandboxError(f"File not found: {path}")

        original = safe.read_text(encoding="utf-8")

        if old_str not in original:
            raise CodeSandboxError(f"Text not found in {path}: {old_str[:50]}...")

        if not replace_all:
            # Ensure unique match for safety
            count = original.count(old_str)
            if count > 1:
                raise CodeSandboxError(
                    f"Text matches {count} times in {path}. "
                    "Provide more context or use replace_all=True"
                )

        backup_path = None
        if backup:
            backup_path = self._create_backup(safe)

        if replace_all:
            new_content = original.replace(old_str, new_str)
            replacements = original.count(old_str)
        else:
            new_content = original.replace(old_str, new_str, 1)
            replacements = 1

        safe.write_text(new_content, encoding="utf-8")

        return EditResult(
            path=path,
            backup_path=backup_path,
            replacements=replacements,
            original_content=original,
            new_content=new_content,
        )

    def delete_file(self, path: str, backup: bool = True) -> DeleteResult:
        """Delete a file.

        Args:
            path: Relative path to file within repo.
            backup: If True, create backup before deleting.

        Returns:
            DeleteResult with operation details.

        Raises:
            CodeSandboxError: If file doesn't exist or path escapes repo.
        """
        safe = self._safe_path(path)

        if not safe.exists():
            raise CodeSandboxError(f"File not found: {path}")

        was_directory = safe.is_dir()

        backup_path = None
        if backup:
            backup_path = self._create_backup(safe)

        if was_directory:
            shutil.rmtree(safe)
        else:
            safe.unlink()

        return DeleteResult(
            path=path,
            backup_path=backup_path,
            was_directory=was_directory,
        )

    # =========================================================================
    # Search Operations
    # =========================================================================

    def grep(
        self,
        pattern: str,
        glob_pattern: str = "**/*",
        ignore_case: bool = False,
        max_results: int = 100,
    ) -> list[GrepMatch]:
        """Search file contents with regex pattern.

        Args:
            pattern: Regular expression pattern to search for.
            glob_pattern: Glob pattern to filter files (e.g., "*.py", "src/**/*.ts").
            ignore_case: If True, perform case-insensitive matching.
            max_results: Maximum number of matches to return.

        Returns:
            List of GrepMatch objects.
        """
        flags = re.IGNORECASE if ignore_case else 0
        regex = re.compile(pattern, flags)
        matches: list[GrepMatch] = []

        for file_path in self.find_files(glob_pattern):
            if len(matches) >= max_results:
                break

            safe = self._safe_path(file_path)
            if not safe.is_file():
                continue

            try:
                content = safe.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue  # Skip binary or unreadable files

            for line_num, line in enumerate(content.splitlines(), start=1):
                if len(matches) >= max_results:
                    break

                match = regex.search(line)
                if match:
                    matches.append(
                        GrepMatch(
                            path=file_path,
                            line_number=line_num,
                            line_content=line,
                            match_start=match.start(),
                            match_end=match.end(),
                        )
                    )

        return matches

    def find_files(
        self,
        glob_pattern: str = "**/*",
        ignore_patterns: list[str] | None = None,
    ) -> list[str]:
        """Find files matching glob pattern.

        Args:
            glob_pattern: Glob pattern to match files.
            ignore_patterns: List of patterns to exclude (e.g., ["*.pyc", "__pycache__"]).

        Returns:
            List of relative file paths.
        """
        ignore_patterns = ignore_patterns or [
            "*.pyc",
            "__pycache__",
            ".git",
            ".reos_backups",
            "node_modules",
            ".venv",
            "venv",
            "*.egg-info",
            ".pytest_cache",
            ".mypy_cache",
            ".ruff_cache",
        ]

        results: list[str] = []

        for path in self.repo_path.glob(glob_pattern):
            # Skip directories in results (only files)
            if path.is_dir():
                continue

            rel_path = str(path.relative_to(self.repo_path))

            # Check against ignore patterns
            skip = False
            for ignore in ignore_patterns:
                # Check each path component
                for part in Path(rel_path).parts:
                    if fnmatch.fnmatch(part, ignore):
                        skip = True
                        break
                if skip:
                    break

            if not skip:
                results.append(rel_path)

        return sorted(results)

    def get_structure(
        self,
        max_depth: int = 3,
        ignore_patterns: list[str] | None = None,
    ) -> dict[str, Any]:
        """Get repository directory structure.

        Args:
            max_depth: Maximum directory depth to traverse.
            ignore_patterns: Patterns to exclude.

        Returns:
            Nested dictionary representing directory structure.
        """
        ignore_patterns = ignore_patterns or [
            ".git",
            "__pycache__",
            "node_modules",
            ".venv",
            "venv",
            ".reos_backups",
        ]

        def should_ignore(name: str) -> bool:
            return any(fnmatch.fnmatch(name, p) for p in ignore_patterns)

        def build_tree(path: Path, depth: int) -> dict[str, Any]:
            if depth > max_depth:
                return {"...": None}

            result: dict[str, Any] = {}
            try:
                entries = sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name))
            except PermissionError:
                return {"(permission denied)": None}

            for entry in entries:
                if should_ignore(entry.name):
                    continue

                if entry.is_dir():
                    result[entry.name + "/"] = build_tree(entry, depth + 1)
                else:
                    result[entry.name] = None

            return result

        return {self.repo_path.name + "/": build_tree(self.repo_path, 1)}

    # =========================================================================
    # Git Context (Read-Only)
    # =========================================================================

    def _run_git(self, *args: str) -> str:
        """Run a git command and return output.

        Args:
            *args: Git command arguments.

        Returns:
            Command stdout.

        Raises:
            CodeSandboxError: If command fails.
        """
        try:
            result = subprocess.run(
                ["git", *args],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0:
                raise CodeSandboxError(f"Git command failed: {result.stderr}")
            return result.stdout
        except subprocess.TimeoutExpired as e:
            raise CodeSandboxError(f"Git command timed out: {e}") from e
        except FileNotFoundError as e:
            raise CodeSandboxError("Git not found in PATH") from e

    def git_status(self) -> GitStatus:
        """Get current git repository status.

        Returns:
            GitStatus with current state.
        """
        # Get branch name
        branch = self._run_git("rev-parse", "--abbrev-ref", "HEAD").strip()

        # Get status
        status_output = self._run_git("status", "--porcelain")

        staged: list[str] = []
        modified: list[str] = []
        untracked: list[str] = []

        for line in status_output.splitlines():
            if len(line) < 3:
                continue
            index_status = line[0]
            work_status = line[1]
            file_path = line[3:]

            if index_status == "?":
                untracked.append(file_path)
            elif index_status != " ":
                staged.append(file_path)
            elif work_status != " ":
                modified.append(file_path)

        # Get ahead/behind
        ahead = behind = 0
        try:
            upstream = self._run_git(
                "rev-list", "--left-right", "--count", f"{branch}...@{{u}}"
            ).strip()
            parts = upstream.split()
            if len(parts) == 2:
                ahead, behind = int(parts[0]), int(parts[1])
        except CodeSandboxError:
            pass  # No upstream configured

        clean = not staged and not modified and not untracked

        return GitStatus(
            clean=clean,
            branch=branch,
            staged=staged,
            modified=modified,
            untracked=untracked,
            ahead=ahead,
            behind=behind,
        )

    def git_diff(self, staged: bool = False) -> str:
        """Get git diff output.

        Args:
            staged: If True, show staged changes; otherwise show unstaged.

        Returns:
            Diff output as string.
        """
        if staged:
            return self._run_git("diff", "--cached")
        return self._run_git("diff")

    def recent_commits(self, count: int = 5) -> list[Commit]:
        """Get recent commits.

        Args:
            count: Number of commits to retrieve.

        Returns:
            List of Commit objects.
        """
        # Use a format we can parse
        output = self._run_git(
            "log",
            f"-{count}",
            "--format=%H|%s|%an|%aI|%N",
            "--numstat",
        )

        commits: list[Commit] = []
        current_sha = ""
        current_message = ""
        current_author = ""
        current_time: datetime | None = None
        files_changed = 0

        for line in output.splitlines():
            if "|" in line and len(line.split("|")) >= 4:
                # This is a commit header line
                if current_sha:
                    commits.append(
                        Commit(
                            sha=current_sha,
                            message=current_message,
                            author=current_author,
                            timestamp=current_time or datetime.now(timezone.utc),
                            files_changed=files_changed,
                        )
                    )

                parts = line.split("|")
                current_sha = parts[0]
                current_message = parts[1]
                current_author = parts[2]
                current_time = datetime.fromisoformat(parts[3])
                files_changed = 0
            elif line.strip() and "\t" in line:
                # This is a numstat line
                files_changed += 1

        # Don't forget the last commit
        if current_sha:
            commits.append(
                Commit(
                    sha=current_sha,
                    message=current_message,
                    author=current_author,
                    timestamp=current_time or datetime.now(timezone.utc),
                    files_changed=files_changed,
                )
            )

        return commits

    # =========================================================================
    # Command Execution (Sandboxed)
    # =========================================================================

    def run_command(
        self,
        command: str,
        timeout: int = 120,
    ) -> tuple[int, str, str]:
        """Run a shell command within the repository.

        Args:
            command: Shell command to execute.
            timeout: Maximum execution time in seconds.

        Returns:
            Tuple of (return_code, stdout, stderr).
        """
        # Validate command safety before execution
        is_safe, warning = is_command_safe(command)
        if not is_safe:
            return -1, "", warning or "Command blocked for safety"

        try:
            result = subprocess.run(
                command,
                shell=True,
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return result.returncode, result.stdout, result.stderr
        except subprocess.TimeoutExpired as e:
            return -1, "", f"Command timed out after {timeout}s: {e}"
