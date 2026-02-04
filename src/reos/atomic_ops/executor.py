"""Execution engine for atomic operations.

This module handles the safe execution of atomic operations with:
- State capture before/after execution
- Automatic backup of affected files
- Undo capability via backups or inverse commands
- Process management for spawned processes

The executor ensures all operations are reversible when possible.
"""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional
from uuid import uuid4

from reos.security import is_command_safe

logger = logging.getLogger(__name__)

from .models import (
    AtomicOperation,
    ConsumerType,
    DestinationType,
    ExecutionResult,
    ExecutionSemantics,
    OperationStatus,
    ReversibilityInfo,
    StateSnapshot,
)
from .schema import AtomicOpsStore


@dataclass
class ExecutionConfig:
    """Configuration for the execution engine."""
    # Timeouts
    default_timeout_seconds: int = 30
    max_timeout_seconds: int = 120

    # Backup settings
    backup_dir: str = "/tmp/reos_backups"
    max_backup_size_mb: int = 100
    backup_retention_hours: int = 24

    # Process limits
    max_concurrent_processes: int = 5
    max_output_size_bytes: int = 1024 * 1024  # 1MB

    # Safety
    dry_run: bool = False
    require_approval: bool = True


@dataclass
class ExecutionContext:
    """Context for operation execution."""
    user_id: str
    working_directory: str = ""
    environment: dict[str, str] = field(default_factory=dict)
    approved: bool = False
    approval_time: Optional[datetime] = None


class StateCapture:
    """Captures system state before/after operations."""

    def __init__(self, backup_dir: str = "/tmp/reos_backups"):
        self.backup_dir = Path(backup_dir)
        self.backup_dir.mkdir(parents=True, exist_ok=True)

    def capture_file_state(self, paths: list[str]) -> dict[str, dict]:
        """Capture state of specified files.

        Returns dict mapping path -> {exists, hash, size, mtime, backup_path}
        """
        state = {}
        for path in paths:
            p = Path(path)
            if p.exists():
                state[path] = {
                    "exists": True,
                    "hash": self._hash_file(p),
                    "size": p.stat().st_size,
                    "mtime": p.stat().st_mtime,
                    "backup_path": None,  # Set during backup
                }
            else:
                state[path] = {
                    "exists": False,
                    "hash": None,
                    "size": 0,
                    "mtime": None,
                    "backup_path": None,
                }
        return state

    def capture_process_state(self, pids: Optional[list[int]] = None) -> list[dict]:
        """Capture state of running processes.

        If pids is None, captures a summary of all processes.
        """
        processes = []

        try:
            if pids:
                for pid in pids:
                    try:
                        proc_path = Path(f"/proc/{pid}")
                        if proc_path.exists():
                            cmdline = (proc_path / "cmdline").read_text().replace('\x00', ' ')
                            processes.append({
                                "pid": pid,
                                "cmdline": cmdline.strip(),
                                "running": True,
                            })
                    except Exception as e:
                        logger.debug(
                            "Failed to read process info for PID %d: %s", pid, e
                        )
                        processes.append({"pid": pid, "running": False})
            else:
                # Get summary of user processes
                result = subprocess.run(
                    ["ps", "-u", os.getlogin(), "-o", "pid,comm"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if result.returncode == 0:
                    for line in result.stdout.strip().split('\n')[1:]:  # Skip header
                        parts = line.split(None, 1)
                        if len(parts) == 2:
                            processes.append({
                                "pid": int(parts[0]),
                                "cmdline": parts[1],
                                "running": True,
                            })
        except Exception as e:
            logger.warning(
                "Failed to capture process state: %s (pids=%s)", e, pids
            )

        return processes

    def capture_system_metrics(self) -> dict[str, Any]:
        """Capture current system metrics."""
        metrics = {}

        try:
            # Memory info
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith(("MemTotal:", "MemFree:", "MemAvailable:")):
                        parts = line.split()
                        metrics[parts[0].rstrip(":")] = int(parts[1])

            # Load average
            with open("/proc/loadavg") as f:
                parts = f.read().split()
                metrics["load_1m"] = float(parts[0])
                metrics["load_5m"] = float(parts[1])
                metrics["load_15m"] = float(parts[2])

        except FileNotFoundError:
            # Not on Linux, /proc doesn't exist
            logger.debug("System metrics unavailable (not Linux)")
        except Exception as e:
            logger.warning("Failed to capture system metrics: %s", e)

        return metrics

    def create_snapshot(
        self,
        file_paths: Optional[list[str]] = None,
        process_pids: Optional[list[int]] = None,
    ) -> StateSnapshot:
        """Create a complete state snapshot."""
        return StateSnapshot(
            timestamp=datetime.now(),
            files=self.capture_file_state(file_paths or []),
            processes=self.capture_process_state(process_pids),
            system_metrics=self.capture_system_metrics(),
        )

    def backup_file(self, path: str, max_size_mb: int = 100) -> Optional[str]:
        """Create backup of a file.

        Returns backup path or None if backup failed or skipped.
        """
        source = Path(path)
        if not source.exists():
            logger.debug("Backup skipped: file does not exist: %s", path)
            return None

        # Check size limit
        size_mb = source.stat().st_size / (1024 * 1024)
        if size_mb > max_size_mb:
            logger.warning(
                "Backup skipped: file too large (%.1f MB > %d MB limit): %s",
                size_mb,
                max_size_mb,
                path,
            )
            return None

        # Create backup
        backup_name = f"{source.name}.{uuid4().hex[:8]}.bak"
        backup_path = self.backup_dir / backup_name

        try:
            shutil.copy2(source, backup_path)
            return str(backup_path)
        except Exception as e:
            logger.warning("Failed to backup file %s to %s: %s", path, backup_path, e)
            return None

    def restore_file(self, backup_path: str, original_path: str) -> bool:
        """Restore a file from backup."""
        try:
            shutil.copy2(backup_path, original_path)
            return True
        except Exception as e:
            logger.warning(
                "Failed to restore file from %s to %s: %s",
                backup_path,
                original_path,
                e,
            )
            return False

    def _hash_file(self, path: Path) -> str:
        """Compute SHA256 hash of file."""
        h = hashlib.sha256()
        with open(path, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                h.update(chunk)
        return h.hexdigest()


class OperationExecutor:
    """Executes atomic operations with state management.

    The executor handles:
    - Pre-execution state capture
    - File backups
    - Operation execution
    - Post-execution state capture
    - Undo capability
    """

    def __init__(
        self,
        store: Optional[AtomicOpsStore] = None,
        config: Optional[ExecutionConfig] = None,
    ):
        """Initialize executor.

        Args:
            store: Optional store for persisting execution records.
            config: Execution configuration.
        """
        self.store = store
        self.config = config or ExecutionConfig()
        self.state_capture = StateCapture(self.config.backup_dir)
        self._spawned_processes: dict[str, subprocess.Popen] = {}

    def execute(
        self,
        operation: AtomicOperation,
        context: ExecutionContext,
        command_generator: Optional[Callable[[AtomicOperation], str]] = None,
    ) -> ExecutionResult:
        """Execute an atomic operation.

        Args:
            operation: The operation to execute.
            context: Execution context.
            command_generator: Optional function to generate command from operation.

        Returns:
            ExecutionResult with success status and output.
        """
        if not operation.classification:
            return ExecutionResult(
                success=False,
                stderr="Operation has no classification",
            )

        # Check approval if required
        if self.config.require_approval and not context.approved:
            return ExecutionResult(
                success=False,
                stderr="Operation requires approval",
            )

        # Extract affected paths from operation
        affected_paths = self._extract_paths(operation.user_request)

        # Capture state before execution
        state_before = self.state_capture.create_snapshot(
            file_paths=affected_paths,
        )

        # Backup affected files
        backup_files = {}
        for path in affected_paths:
            if Path(path).exists():
                backup_path = self.state_capture.backup_file(
                    path, self.config.max_backup_size_mb
                )
                if backup_path:
                    backup_files[path] = backup_path

        # Execute based on operation type
        start_time = time.time()

        try:
            if operation.classification.destination == DestinationType.PROCESS:
                result = self._execute_process(operation, context, command_generator)
            elif operation.classification.destination == DestinationType.FILE:
                result = self._execute_file_operation(operation, context)
            else:  # STREAM
                result = self._execute_stream(operation, context)
        except Exception as e:
            result = ExecutionResult(
                success=False,
                stderr=str(e),
            )

        duration_ms = int((time.time() - start_time) * 1000)
        result.duration_ms = duration_ms

        # Capture state after execution
        state_after = self.state_capture.create_snapshot(
            file_paths=affected_paths,
            process_pids=result.processes_spawned,
        )

        # Determine reversibility
        reversibility = self._determine_reversibility(
            operation, state_before, state_after, backup_files
        )

        # Store execution record if store available
        if self.store:
            self.store.store_execution(
                operation.id,
                result,
                state_before,
                state_after,
                reversibility,
            )

        # Update operation status
        operation.execution_result = result
        operation.state_before = state_before
        operation.state_after = state_after
        operation.reversibility = reversibility

        if result.success:
            operation.status = OperationStatus.COMPLETE
        else:
            operation.status = OperationStatus.FAILED

        if self.store:
            self.store.update_operation_status(operation.id, operation.status)

        return result

    def undo(
        self,
        operation: AtomicOperation,
        context: ExecutionContext,
    ) -> ExecutionResult:
        """Undo a previously executed operation.

        Args:
            operation: The operation to undo.
            context: Execution context.

        Returns:
            ExecutionResult of the undo operation.
        """
        if not operation.reversibility:
            return ExecutionResult(
                success=False,
                stderr="Operation has no reversibility information",
            )

        if not operation.reversibility.reversible:
            return ExecutionResult(
                success=False,
                stderr=f"Operation is not reversible: {operation.reversibility.reason}",
            )

        # Execute undo based on method
        method = operation.reversibility.method

        if method == "restore_backup":
            return self._undo_restore_backup(operation)
        elif method == "inverse_command":
            return self._undo_inverse_command(operation, context)
        elif method == "delete_created":
            return self._undo_delete_created(operation)
        else:
            return ExecutionResult(
                success=False,
                stderr=f"Unknown undo method: {method}",
            )

    def _execute_process(
        self,
        operation: AtomicOperation,
        context: ExecutionContext,
        command_generator: Optional[Callable],
    ) -> ExecutionResult:
        """Execute a process operation."""
        # Generate or extract command
        if command_generator:
            command = command_generator(operation)
        else:
            # Use request directly as command (simplified)
            command = operation.user_request

        if self.config.dry_run:
            return ExecutionResult(
                success=True,
                stdout=f"[DRY RUN] Would execute: {command}",
            )

        # Validate command safety before execution
        is_safe, warning = is_command_safe(command)
        if not is_safe:
            return ExecutionResult(
                success=False,
                stderr=warning or "Command blocked for safety",
            )

        try:
            # Run process
            proc = subprocess.Popen(
                command,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=context.working_directory or None,
                env={**os.environ, **context.environment},
            )

            # Track spawned process
            self._spawned_processes[operation.id] = proc

            # Wait with timeout
            stdout, stderr = proc.communicate(
                timeout=self.config.default_timeout_seconds
            )

            # Truncate output if needed
            max_size = self.config.max_output_size_bytes
            stdout_str = stdout.decode('utf-8', errors='replace')[:max_size]
            stderr_str = stderr.decode('utf-8', errors='replace')[:max_size]

            return ExecutionResult(
                success=proc.returncode == 0,
                exit_code=proc.returncode,
                stdout=stdout_str,
                stderr=stderr_str,
                processes_spawned=[proc.pid],
            )

        except subprocess.TimeoutExpired:
            proc.kill()
            return ExecutionResult(
                success=False,
                stderr=f"Process timed out after {self.config.default_timeout_seconds}s",
            )
        except Exception as e:
            return ExecutionResult(
                success=False,
                stderr=str(e),
            )

    def _execute_file_operation(
        self,
        operation: AtomicOperation,
        context: ExecutionContext,
    ) -> ExecutionResult:
        """Execute a file operation (create, modify, delete)."""
        # This is a simplified implementation
        # In practice, this would integrate with the MCP tools

        if self.config.dry_run:
            return ExecutionResult(
                success=True,
                stdout=f"[DRY RUN] Would perform file operation: {operation.user_request}",
            )

        # File operations are handled by specific handlers
        # This returns a placeholder indicating the operation type
        return ExecutionResult(
            success=True,
            stdout="File operation delegated to handler",
        )

    def _execute_stream(
        self,
        operation: AtomicOperation,
        context: ExecutionContext,
    ) -> ExecutionResult:
        """Execute a stream operation (display information)."""
        # Stream operations typically read and display data
        # This is handled by the response generation layer
        return ExecutionResult(
            success=True,
            stdout="Stream operation - output generated",
        )

    def _extract_paths(self, request: str) -> list[str]:
        """Extract file paths from request, filtering out traversal attempts."""
        import re
        # Match Unix-style paths
        paths = re.findall(r'(?:^|[\s"\'])([/~][\w./-]+)', request)
        # Expand ~ and validate
        expanded = []
        for p in paths:
            if p.startswith('~'):
                p = os.path.expanduser(p)
            # Reject path traversal attempts
            resolved = os.path.realpath(p)
            if '..' in p or resolved.startswith(('/proc/', '/sys/', '/dev/')):
                logger.warning("Rejected suspicious path: %s (resolved: %s)", p, resolved)
                continue
            expanded.append(p)
        return expanded

    def _determine_reversibility(
        self,
        operation: AtomicOperation,
        state_before: StateSnapshot,
        state_after: StateSnapshot,
        backup_files: dict[str, str],
    ) -> ReversibilityInfo:
        """Determine if and how an operation can be undone."""
        # Check if we have backups
        if backup_files:
            return ReversibilityInfo(
                reversible=True,
                method="restore_backup",
                backup_files=backup_files,
                reason="Files backed up before modification",
            )

        # Check for file creation (can delete)
        created_files = []
        for path, after_state in state_after.files.items():
            before_state = state_before.files.get(path, {})
            if after_state.get("exists") and not before_state.get("exists"):
                created_files.append(path)

        if created_files:
            return ReversibilityInfo(
                reversible=True,
                method="delete_created",
                undo_commands=[f"rm '{f}'" for f in created_files],
                reason="Can delete newly created files",
            )

        # Process operations may have inverse commands
        if operation.classification and operation.classification.destination == DestinationType.PROCESS:
            inverse = self._get_inverse_command(operation.user_request)
            if inverse:
                return ReversibilityInfo(
                    reversible=True,
                    method="inverse_command",
                    undo_commands=[inverse],
                    reason="Inverse command available",
                )

        # Default: not reversible
        return ReversibilityInfo(
            reversible=False,
            reason="No undo method available",
        )

    def _get_inverse_command(self, command: str) -> Optional[str]:
        """Get inverse command if one exists."""
        # Simple inverse mappings
        inverses = {
            "start": "stop",
            "stop": "start",
            "enable": "disable",
            "disable": "enable",
            "mount": "umount",
            "mkdir": "rmdir",
        }

        for action, inverse in inverses.items():
            if action in command.lower():
                return command.lower().replace(action, inverse)

        return None

    def _undo_restore_backup(self, operation: AtomicOperation) -> ExecutionResult:
        """Undo by restoring backups."""
        if not operation.reversibility:
            return ExecutionResult(success=False, stderr="No reversibility info")

        restored = []
        failed = []

        for original, backup in operation.reversibility.backup_files.items():
            if self.state_capture.restore_file(backup, original):
                restored.append(original)
            else:
                failed.append(original)

        if failed:
            return ExecutionResult(
                success=False,
                stdout=f"Restored: {', '.join(restored)}",
                stderr=f"Failed to restore: {', '.join(failed)}",
                files_affected=restored,
            )

        return ExecutionResult(
            success=True,
            stdout=f"Restored {len(restored)} files from backup",
            files_affected=restored,
        )

    def _undo_inverse_command(
        self,
        operation: AtomicOperation,
        context: ExecutionContext,
    ) -> ExecutionResult:
        """Undo by running inverse command."""
        if not operation.reversibility or not operation.reversibility.undo_commands:
            return ExecutionResult(success=False, stderr="No undo commands")

        results = []
        for cmd in operation.reversibility.undo_commands:
            # Validate undo command safety
            is_safe, warning = is_command_safe(cmd)
            if not is_safe:
                logger.warning("Undo command blocked for safety: %s", cmd)
                results.append((cmd, False))
                continue

            try:
                proc = subprocess.run(
                    cmd,
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                results.append((cmd, proc.returncode == 0))
                if proc.returncode != 0:
                    logger.warning(
                        "Undo command failed (exit %d): %s, stderr: %s",
                        proc.returncode,
                        cmd,
                        proc.stderr[:200] if proc.stderr else "(no stderr)",
                    )
            except Exception as e:
                logger.warning("Undo command raised exception: %s, error: %s", cmd, e)
                results.append((cmd, False))

        all_success = all(success for _, success in results)
        return ExecutionResult(
            success=all_success,
            stdout="\n".join(f"{cmd}: {'OK' if ok else 'FAILED'}" for cmd, ok in results),
        )

    def _undo_delete_created(self, operation: AtomicOperation) -> ExecutionResult:
        """Undo by deleting created files."""
        if not operation.reversibility or not operation.reversibility.undo_commands:
            return ExecutionResult(success=False, stderr="No undo commands")

        deleted = []
        failed = []

        for cmd in operation.reversibility.undo_commands:
            # Extract path from rm command
            path = cmd.replace("rm '", "").rstrip("'")
            try:
                os.remove(path)
                deleted.append(path)
            except Exception as e:
                logger.warning("Failed to delete created file %s: %s", path, e)
                failed.append(path)

        if failed:
            return ExecutionResult(
                success=False,
                stdout=f"Deleted: {', '.join(deleted)}",
                stderr=f"Failed to delete: {', '.join(failed)}",
            )

        return ExecutionResult(
            success=True,
            stdout=f"Deleted {len(deleted)} files",
            files_affected=deleted,
        )


def create_executor(
    store: Optional[AtomicOpsStore] = None,
    config: Optional[ExecutionConfig] = None,
) -> OperationExecutor:
    """Create an executor with default configuration."""
    return OperationExecutor(store=store, config=config)
