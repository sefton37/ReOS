"""Safety verification layer.

The critical verification layer that blocks dangerous operations.
This layer MUST pass for an operation to proceed.

Checks:
- No destructive operations without safeguards
- No security-sensitive operations
- No unbounded resource consumption
- Respects user safety configuration
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


# Absolutely blocked patterns - never allow
BLOCKED_PATTERNS = [
    (r'rm\s+(-rf?|--recursive)\s+[/~]$', "Recursive delete of root or home"),
    (r'rm\s+(-rf?|--recursive)\s+/\s*$', "Recursive delete of root"),
    (r'rm\s+(-rf?|--recursive)\s+~\s*$', "Recursive delete of home"),
    (r'rm\s+(-rf?|--recursive)\s+/home\s*$', "Recursive delete of /home"),
    (r':\s*\(\s*\)\s*\{\s*:\s*\|\s*:\s*&', "Fork bomb pattern"),
    (r'>\s*/dev/sd[a-z]', "Direct write to block device"),
    (r'dd\s+.*of=/dev/sd[a-z]', "dd to block device"),
    (r'mkfs', "Filesystem creation"),
    (r'fdisk|parted|gdisk', "Partition manipulation"),
    (r'chmod\s+(-R\s+)?777\s+/', "Recursive chmod 777 on root paths"),
    (r'chown\s+-R\s+.*\s+/', "Recursive chown on root paths"),
    (r'/etc/passwd|/etc/shadow', "Accessing password files"),
    (r'curl\s+.*\|\s*(ba)?sh', "Pipe curl to shell"),
    (r'wget\s+.*\|\s*(ba)?sh', "Pipe wget to shell"),
    (r'eval\s+.*\$', "Eval with variable expansion"),
]

# Dangerous patterns - require explicit approval
DANGEROUS_PATTERNS = [
    (r'rm\s+-rf?\s', "Recursive delete"),
    (r'rm\s+--force', "Force delete"),
    (r'rm\s+-r\s', "Recursive delete"),
    (r'sudo\s+rm', "Root delete"),
    (r'sudo\s+dd', "Root direct disk"),
    (r'>\s*/etc/', "Write to /etc"),
    (r'>>\s*/etc/', "Append to /etc"),
    (r'crontab', "Cron manipulation"),
    (r'systemctl\s+(disable|mask|stop)', "Disable/stop services"),
    (r'kill\s+-9', "Force kill"),
    (r'killall', "Kill all processes"),
    (r'pkill', "Pattern kill"),
    (r'reboot|shutdown|poweroff', "System power control"),
    (r'iptables|ufw|firewalld', "Firewall manipulation"),
    (r'useradd|userdel|usermod', "User manipulation"),
    (r'groupadd|groupdel|groupmod', "Group manipulation"),
    (r'visudo|sudoers', "Sudo configuration"),
    (r'ssh-keygen.*-f', "SSH key generation"),
]

# Sensitive data patterns
SENSITIVE_PATTERNS = [
    (r'password|passwd|secret|token|api.?key|credential', "Sensitive data reference"),
    (r'\.env\b', "Environment file"),
    (r'\.ssh/', "SSH directory"),
    (r'\.gnupg/', "GPG directory"),
    (r'\.aws/', "AWS credentials"),
    (r'\.kube/', "Kubernetes config"),
]

# Rate limiting thresholds
MAX_OPERATIONS_PER_MINUTE = 60
MAX_SUDO_PER_SESSION = 10


class SafetyVerifier(BaseVerifier):
    """Verify operation safety.

    This is the most critical verification layer. It must pass
    for any operation to proceed. Blocked operations CANNOT be
    overridden.
    """

    def __init__(self):
        self._sudo_count = 0
        self._operation_count = 0

    @property
    def layer(self) -> VerificationLayer:
        return VerificationLayer.SAFETY

    def verify(
        self,
        operation: AtomicOperation,
        context: VerificationContext,
    ) -> VerificationResult:
        """Verify operation safety."""
        request = operation.user_request
        issues = []

        # Check for absolutely blocked patterns
        blocked = self._check_blocked_patterns(request)
        if blocked:
            return self._fail(
                [f"BLOCKED: {blocked}"],
                confidence=1.0,
                details="This operation is not allowed for safety reasons",
            )

        # Check for dangerous patterns
        dangerous = self._check_dangerous_patterns(request)
        if dangerous:
            issues.extend(dangerous)

        # Check for sensitive data access
        sensitive = self._check_sensitive_patterns(request, context)
        issues.extend(sensitive)

        # Check operation type safety
        type_issues = self._check_operation_type_safety(operation, context)
        issues.extend(type_issues)

        # Check rate limits
        rate_issues = self._check_rate_limits(operation, context)
        issues.extend(rate_issues)

        # Apply safety level rules
        level_issues = self._apply_safety_level(operation, context)
        issues.extend(level_issues)

        # Determine result
        if any("BLOCKED" in issue or "blocked" in issue.lower() for issue in issues):
            return self._fail(issues, confidence=1.0)

        if issues:
            # Safety issues reduce confidence significantly
            confidence = max(0.3, 1.0 - (len(issues) * 0.2))
            return self._warn(
                issues,
                confidence=confidence,
                details="Requires user approval due to safety concerns",
            )

        return self._pass(
            confidence=1.0,
            details="Operation passed safety checks",
        )

    def _check_blocked_patterns(self, request: str) -> Optional[str]:
        """Check for absolutely blocked patterns."""
        for pattern, description in BLOCKED_PATTERNS:
            if re.search(pattern, request, re.IGNORECASE):
                return description
        return None

    def _check_dangerous_patterns(self, request: str) -> list[str]:
        """Check for dangerous but allowable patterns."""
        issues = []
        for pattern, description in DANGEROUS_PATTERNS:
            if re.search(pattern, request, re.IGNORECASE):
                issues.append(f"Dangerous operation: {description}")
        return issues

    def _check_sensitive_patterns(
        self,
        request: str,
        context: VerificationContext,
    ) -> list[str]:
        """Check for sensitive data access."""
        issues = []

        # Only check in standard or strict mode
        if context.safety_level == "permissive":
            return issues

        for pattern, description in SENSITIVE_PATTERNS:
            if re.search(pattern, request, re.IGNORECASE):
                issues.append(f"Sensitive access: {description}")

        return issues

    def _check_operation_type_safety(
        self,
        operation: AtomicOperation,
        context: VerificationContext,
    ) -> list[str]:
        """Check safety based on operation type."""
        issues = []

        if not operation.classification:
            return issues

        # Process operations with execute semantics need scrutiny
        if (operation.classification.destination == DestinationType.PROCESS and
            operation.classification.semantics == ExecutionSemantics.EXECUTE):

            # Check if sudo is being used
            if "sudo" in operation.user_request.lower():
                self._sudo_count += 1
                if self._sudo_count > MAX_SUDO_PER_SESSION:
                    issues.append(
                        f"Too many sudo operations ({self._sudo_count} > {MAX_SUDO_PER_SESSION})"
                    )

            # Check for commands in blocklist
            request_words = set(operation.user_request.lower().split())
            blocked = request_words & context.blocked_commands
            if blocked:
                issues.append(f"Command blocked by configuration: {', '.join(blocked)}")

        return issues

    def _check_rate_limits(
        self,
        operation: AtomicOperation,
        context: VerificationContext,
    ) -> list[str]:
        """Check operation rate limits."""
        issues = []

        self._operation_count += 1

        # This is a simplified check - in production, track time windows
        if self._operation_count > MAX_OPERATIONS_PER_MINUTE:
            issues.append(
                f"Rate limit exceeded ({self._operation_count} operations)"
            )

        return issues

    def _apply_safety_level(
        self,
        operation: AtomicOperation,
        context: VerificationContext,
    ) -> list[str]:
        """Apply safety level rules."""
        issues = []

        if context.safety_level == "strict":
            # In strict mode, block all process executions by default
            if (operation.classification and
                operation.classification.destination == DestinationType.PROCESS and
                operation.classification.semantics == ExecutionSemantics.EXECUTE):
                issues.append("Process execution requires approval in strict mode")

            # Block all file modifications in strict mode
            if (operation.classification and
                operation.classification.destination == DestinationType.FILE and
                operation.classification.semantics == ExecutionSemantics.EXECUTE):
                issues.append("File modification requires approval in strict mode")

        elif context.safety_level == "standard":
            # In standard mode, flag potentially dangerous operations
            if "sudo" in operation.user_request.lower():
                issues.append("Root operation requires approval")

        # Permissive mode - minimal restrictions (already handled by blocked patterns)

        return issues

    def reset_counters(self):
        """Reset session counters."""
        self._sudo_count = 0
        self._operation_count = 0
