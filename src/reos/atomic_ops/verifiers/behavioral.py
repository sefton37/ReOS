"""Behavioral verification layer.

Predicts what the operation will do and verifies it's reasonable.
Uses pattern matching and heuristics - no LLM calls.

Checks:
- Predicted side effects are reasonable
- Resource requirements are acceptable
- Operation scope is bounded
"""

from __future__ import annotations

import re
from typing import Optional

from ..models import (
    AtomicOperation,
    DestinationType,
    ExecutionSemantics,
    VerificationLayer,
    VerificationResult,
)
from .base import BaseVerifier, VerificationContext


# Patterns that indicate broad/recursive operations
BROAD_OPERATION_PATTERNS = [
    (r'\b(all|every|each)\b.*\b(file|folder|dir)', "Affects all files/directories"),
    (r'\brecursive\b', "Recursive operation"),
    (r'\s-[rR]\b', "Recursive flag"),
    (r'\s-rf\b', "Recursive force flag"),
    (r'\*\*/', "Glob all subdirectories"),
    (r'/\*$', "Glob all in directory"),
]

# Patterns that indicate system-wide operations
SYSTEM_WIDE_PATTERNS = [
    (r'\bsudo\b', "Requires root privileges"),
    (r'\b/etc/', "Modifies system configuration"),
    (r'\b/usr/', "Modifies system files"),
    (r'\b/var/', "Modifies system data"),
    (r'\bsystemctl\b', "Controls system services"),
    (r'\bapt|dnf|pacman|zypper\b', "Package management"),
]

# Patterns that indicate resource-intensive operations
RESOURCE_INTENSIVE_PATTERNS = [
    (r'\bfind\s+/\b', "Searches from root"),
    (r'\bgrep\s+-r\s+/\b', "Recursive grep from root"),
    (r'\bdd\b', "Direct disk operation"),
    (r'\btar\b.*\bczf\b', "Creating compressed archive"),
    (r'\brsync\b', "Synchronization operation"),
]

# Maximum reasonable operation counts
MAX_CHILD_OPERATIONS = 10
MAX_FILES_AFFECTED = 100


class BehavioralVerifier(BaseVerifier):
    """Verify predicted operation behavior.

    Analyzes the operation to predict what it will do
    and verifies the predicted behavior is acceptable.
    """

    @property
    def layer(self) -> VerificationLayer:
        return VerificationLayer.BEHAVIORAL

    def verify(
        self,
        operation: AtomicOperation,
        context: VerificationContext,
    ) -> VerificationResult:
        """Verify operation behavior prediction."""
        issues = []
        request = operation.user_request

        # Check for broad operations
        broad_issues = self._check_broad_operations(request)
        issues.extend(broad_issues)

        # Check for system-wide operations
        system_issues = self._check_system_operations(request, context)
        issues.extend(system_issues)

        # Check for resource-intensive operations
        resource_issues = self._check_resource_operations(request)
        issues.extend(resource_issues)

        # Check decomposition complexity
        if operation.is_decomposed:
            if len(operation.child_ids) > MAX_CHILD_OPERATIONS:
                issues.append(
                    f"Decomposed into {len(operation.child_ids)} operations "
                    f"(max recommended: {MAX_CHILD_OPERATIONS})"
                )

        # Check operation scope based on classification
        scope_issues = self._check_operation_scope(operation, context)
        issues.extend(scope_issues)

        # Calculate confidence based on issues
        confidence = 1.0
        if issues:
            # Reduce confidence by 0.1 for each issue, minimum 0.3
            confidence = max(0.3, 1.0 - (len(issues) * 0.1))

        if any("root" in issue.lower() or "system" in issue.lower() for issue in issues):
            # System operations need explicit approval
            return self._warn(
                issues,
                confidence=confidence,
                details="System-level operation - requires approval",
            )

        if issues:
            return self._warn(issues, confidence=confidence)

        return self._pass(
            confidence=confidence,
            details=self._predict_behavior(operation),
        )

    def _check_broad_operations(self, request: str) -> list[str]:
        """Check for operations that affect many resources."""
        issues = []
        for pattern, description in BROAD_OPERATION_PATTERNS:
            if re.search(pattern, request, re.IGNORECASE):
                issues.append(f"Broad operation: {description}")
        return issues

    def _check_system_operations(
        self,
        request: str,
        context: VerificationContext,
    ) -> list[str]:
        """Check for system-wide operations."""
        issues = []
        for pattern, description in SYSTEM_WIDE_PATTERNS:
            if re.search(pattern, request, re.IGNORECASE):
                # Check if this is allowed by context
                if context.safety_level == "strict":
                    issues.append(f"System operation blocked in strict mode: {description}")
                else:
                    issues.append(f"System operation: {description}")
        return issues

    def _check_resource_operations(self, request: str) -> list[str]:
        """Check for resource-intensive operations."""
        issues = []
        for pattern, description in RESOURCE_INTENSIVE_PATTERNS:
            if re.search(pattern, request, re.IGNORECASE):
                issues.append(f"Resource-intensive: {description}")
        return issues

    def _check_operation_scope(
        self,
        operation: AtomicOperation,
        context: VerificationContext,
    ) -> list[str]:
        """Check operation scope against allowed paths."""
        issues = []

        if not operation.classification:
            return issues

        # Check file operations against allowed paths
        if operation.classification.destination == DestinationType.FILE:
            if operation.classification.semantics == ExecutionSemantics.EXECUTE:
                # File modification - check paths
                if context.allowed_paths:
                    # Extract paths from request
                    paths = re.findall(r'[/~][\w./-]+', operation.user_request)
                    for path in paths:
                        if not any(path.startswith(allowed) for allowed in context.allowed_paths):
                            issues.append(f"Path '{path}' outside allowed directories")

        # Check process operations
        if operation.classification.destination == DestinationType.PROCESS:
            if operation.classification.semantics == ExecutionSemantics.EXECUTE:
                # Check for blocked commands
                request_words = set(operation.user_request.lower().split())
                blocked = request_words & context.blocked_commands
                if blocked:
                    issues.append(f"Blocked commands detected: {', '.join(blocked)}")

        return issues

    def _predict_behavior(self, operation: AtomicOperation) -> str:
        """Generate a human-readable behavior prediction."""
        if not operation.classification:
            return "Behavior unknown (no classification)"

        dest = operation.classification.destination.value
        consumer = operation.classification.consumer.value
        sem = operation.classification.semantics.value

        predictions = {
            ("stream", "human", "read"): "Will display information to user",
            ("stream", "human", "interpret"): "Will explain/analyze and display to user",
            ("stream", "machine", "read"): "Will output structured data",
            ("file", "human", "read"): "Will read and display file contents",
            ("file", "human", "execute"): "Will create or modify a file",
            ("file", "machine", "execute"): "Will write structured data to file",
            ("process", "machine", "execute"): "Will run a system command",
            ("process", "human", "execute"): "Will launch an interactive application",
        }

        key = (dest, consumer, sem)
        return predictions.get(key, f"Will {sem} to {dest} for {consumer}")
