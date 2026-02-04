"""Streaming command executor for real-time output.

Uses subprocess.Popen with threading to capture output line-by-line
for streaming to the UI via polling.
"""

from __future__ import annotations

import subprocess
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

from reos.security import is_command_safe


@dataclass
class StreamingExecution:
    """Represents a streaming command execution."""

    execution_id: str
    command: str
    cwd: str | None = None
    started_at: datetime = field(default_factory=datetime.now)
    completed_at: datetime | None = None

    # Output buffers
    stdout_lines: list[str] = field(default_factory=list)
    stderr_lines: list[str] = field(default_factory=list)

    # Process state
    process: subprocess.Popen | None = None
    return_code: int | None = None
    is_complete: bool = False
    error: str | None = None

    # Threading
    _stdout_thread: threading.Thread | None = None
    _stderr_thread: threading.Thread | None = None


class StreamingExecutor:
    """Execute commands with real-time output streaming.

    Example:
        executor = StreamingExecutor()
        exec_id = executor.start("apt update", cwd="/tmp")

        while True:
            lines, complete = executor.get_output(exec_id)
            for line in lines:
                print(line)
            if complete:
                break
            time.sleep(0.1)

        result = executor.get_result(exec_id)
    """

    def __init__(self) -> None:
        self._executions: dict[str, StreamingExecution] = {}
        self._lock = threading.Lock()

    def start(
        self,
        command: str,
        *,
        execution_id: str,
        cwd: str | None = None,
        timeout: int = 300,
        on_line: Callable[[str], None] | None = None,
    ) -> str:
        """Start a streaming command execution.

        Args:
            command: Shell command to execute
            execution_id: Unique ID for this execution
            cwd: Working directory
            timeout: Timeout in seconds (default 5 min)
            on_line: Optional callback for each output line

        Returns:
            execution_id for tracking
        """
        execution = StreamingExecution(
            execution_id=execution_id,
            command=command,
            cwd=cwd,
        )

        try:
            # Validate command safety before execution
            is_safe, warning = is_command_safe(command)
            if not is_safe:
                execution.is_complete = True
                execution.error = warning or "Command blocked for safety"
                execution.completed_at = datetime.now()
                # Store the blocked execution before returning
                with self._lock:
                    self._executions[execution_id] = execution
                return execution_id

            process = subprocess.Popen(
                command,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,  # Line buffered
                cwd=cwd,
            )
            execution.process = process

            # Start reader threads
            execution._stdout_thread = threading.Thread(
                target=self._read_stream,
                args=(execution, process.stdout, execution.stdout_lines, on_line),
                daemon=True,
            )
            execution._stderr_thread = threading.Thread(
                target=self._read_stream,
                args=(execution, process.stderr, execution.stderr_lines, None),
                daemon=True,
            )

            execution._stdout_thread.start()
            execution._stderr_thread.start()

            # Start completion watcher
            threading.Thread(
                target=self._wait_for_completion,
                args=(execution, timeout),
                daemon=True,
            ).start()

        except Exception as e:
            execution.is_complete = True
            execution.error = str(e)
            execution.completed_at = datetime.now()

        with self._lock:
            self._executions[execution_id] = execution

        return execution_id

    def _read_stream(
        self,
        execution: StreamingExecution,
        stream,
        buffer: list[str],
        on_line: Callable[[str], None] | None,
    ) -> None:
        """Read from a stream line by line."""
        try:
            for line in stream:
                line = line.rstrip('\n\r')
                with self._lock:
                    buffer.append(line)
                if on_line:
                    on_line(line)
        except Exception:
            pass  # Stream closed
        finally:
            try:
                stream.close()
            except Exception:
                pass

    def _wait_for_completion(
        self,
        execution: StreamingExecution,
        timeout: int,
    ) -> None:
        """Wait for process completion."""
        try:
            if execution.process:
                execution.process.wait(timeout=timeout)
                execution.return_code = execution.process.returncode
        except subprocess.TimeoutExpired:
            if execution.process:
                execution.process.kill()
                execution.process.wait()
            execution.error = f"Command timed out after {timeout} seconds"
            execution.return_code = -1
        except Exception as e:
            execution.error = str(e)
            execution.return_code = -1
        finally:
            # Wait for reader threads
            if execution._stdout_thread:
                execution._stdout_thread.join(timeout=1)
            if execution._stderr_thread:
                execution._stderr_thread.join(timeout=1)

            execution.is_complete = True
            execution.completed_at = datetime.now()

    def get_output(
        self,
        execution_id: str,
        since_line: int = 0,
    ) -> tuple[list[str], bool]:
        """Get new output lines since last check.

        Args:
            execution_id: The execution to check
            since_line: Line index to start from (0-based)

        Returns:
            Tuple of (new_lines, is_complete)
        """
        with self._lock:
            execution = self._executions.get(execution_id)
            if not execution:
                return [], True

            # Combine stdout and stderr (interleaved based on order received)
            all_lines = execution.stdout_lines + execution.stderr_lines
            new_lines = all_lines[since_line:]

            return new_lines, execution.is_complete

    def get_stdout(
        self,
        execution_id: str,
        since_line: int = 0,
    ) -> tuple[list[str], bool]:
        """Get stdout lines only."""
        with self._lock:
            execution = self._executions.get(execution_id)
            if not execution:
                return [], True

            new_lines = execution.stdout_lines[since_line:]
            return new_lines, execution.is_complete

    def get_result(self, execution_id: str) -> dict | None:
        """Get the final result of an execution.

        Returns None if execution not found, otherwise dict with:
        - success: bool
        - return_code: int
        - stdout: str (joined lines)
        - stderr: str (joined lines)
        - error: str | None
        - duration_seconds: float
        """
        with self._lock:
            execution = self._executions.get(execution_id)
            if not execution:
                return None

            if not execution.is_complete:
                return None

            duration = 0.0
            if execution.completed_at:
                duration = (execution.completed_at - execution.started_at).total_seconds()

            return {
                "success": execution.return_code == 0,
                "return_code": execution.return_code,
                "stdout": "\n".join(execution.stdout_lines),
                "stderr": "\n".join(execution.stderr_lines),
                "error": execution.error,
                "duration_seconds": duration,
            }

    def is_complete(self, execution_id: str) -> bool:
        """Check if an execution is complete."""
        with self._lock:
            execution = self._executions.get(execution_id)
            return execution.is_complete if execution else True

    def kill(self, execution_id: str) -> bool:
        """Kill a running execution."""
        with self._lock:
            execution = self._executions.get(execution_id)
            if not execution or not execution.process:
                return False

            try:
                execution.process.kill()
                return True
            except Exception:
                return False

    def cleanup(self, execution_id: str) -> None:
        """Remove an execution from tracking."""
        with self._lock:
            if execution_id in self._executions:
                del self._executions[execution_id]

    def get_active_count(self) -> int:
        """Get count of active (incomplete) executions."""
        with self._lock:
            return sum(1 for e in self._executions.values() if not e.is_complete)


# Global executor instance
_executor: StreamingExecutor | None = None


def get_streaming_executor() -> StreamingExecutor:
    """Get the global streaming executor instance."""
    global _executor
    if _executor is None:
        _executor = StreamingExecutor()
    return _executor
