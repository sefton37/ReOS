"""Syntax verification layer.

Verifies that the operation request is well-formed and parseable.
This is the fastest layer - pure pattern matching, no LLM calls.

Checks:
- Request is not empty or gibberish
- Request contains recognizable structure
- File paths are valid syntax
- Command patterns are well-formed
"""

from __future__ import annotations

import re
from typing import Optional

from ..models import AtomicOperation, VerificationLayer, VerificationResult
from .base import BaseVerifier, VerificationContext


# Patterns for recognizing well-formed requests
VALID_REQUEST_PATTERNS = [
    r'^\s*\w+',  # Starts with a word
    r'\b(show|list|get|find|search|create|make|add|write|save|run|execute|start|stop|kill|delete|remove|update|open|install)\b',  # Action verbs
    r'\b(what|how|why|when|where|who|which|is|are|can|do|does)\b',  # Question words
]

# Patterns that suggest gibberish or invalid input
INVALID_PATTERNS = [
    r'^[\s\W]+$',  # Only whitespace and special chars
    r'^(.)\1{10,}$',  # Same char repeated many times
    r'[\x00-\x08\x0b\x0c\x0e-\x1f]',  # Control characters
]

# Valid file path pattern (Unix-style)
FILE_PATH_PATTERN = re.compile(r'(?:^|[\s"\'])([/~][\w./-]+|\.{1,2}/[\w./-]*)')

# Command injection patterns to detect
INJECTION_PATTERNS = [
    r';\s*rm\s',  # rm after semicolon
    r'\|\s*rm\s',  # rm after pipe
    r'`[^`]*`',  # Backtick substitution
    r'\$\([^)]+\)',  # Command substitution
    r'>\s*/dev/',  # Redirect to /dev
    r'>>\s*/etc/',  # Append to /etc
]


class SyntaxVerifier(BaseVerifier):
    """Verify operation request syntax.

    Fast verification layer that checks:
    - Request is non-empty and contains recognizable words
    - No obvious gibberish or control characters
    - File paths have valid syntax
    - No obvious injection patterns
    """

    @property
    def layer(self) -> VerificationLayer:
        return VerificationLayer.SYNTAX

    def verify(
        self,
        operation: AtomicOperation,
        context: VerificationContext,
    ) -> VerificationResult:
        """Verify request syntax."""
        request = operation.user_request.strip()
        issues = []

        # Check for empty request
        if not request:
            return self._fail(["Request is empty"])

        # Check for minimum length
        if len(request) < 2:
            return self._fail(["Request too short"])

        # Check for maximum length
        if len(request) > 8192:
            return self._fail(["Request exceeds maximum length (8KB)"])

        # Check for invalid patterns
        for pattern in INVALID_PATTERNS:
            if re.search(pattern, request):
                return self._fail(["Request contains invalid characters or patterns"])

        # Check for at least one valid pattern
        has_valid_structure = False
        for pattern in VALID_REQUEST_PATTERNS:
            if re.search(pattern, request, re.IGNORECASE):
                has_valid_structure = True
                break

        if not has_valid_structure:
            issues.append("Request may not be a recognizable command or question")

        # Check for injection patterns
        injection_detected = self._check_injection(request)
        if injection_detected:
            issues.append(f"Potential command injection detected: {injection_detected}")
            return self._fail(issues, details="Injection pattern found")

        # Validate file paths if present
        path_issues = self._validate_file_paths(request)
        issues.extend(path_issues)

        # Calculate confidence
        word_count = len(request.split())
        confidence = min(1.0, 0.5 + (word_count * 0.1))

        if issues:
            return self._warn(issues, confidence=confidence * 0.8)

        return self._pass(confidence=confidence, details=f"{word_count} words, well-formed")

    def _check_injection(self, request: str) -> Optional[str]:
        """Check for potential command injection patterns."""
        for pattern in INJECTION_PATTERNS:
            match = re.search(pattern, request)
            if match:
                return match.group()
        return None

    def _validate_file_paths(self, request: str) -> list[str]:
        """Validate file paths in the request."""
        issues = []
        paths = FILE_PATH_PATTERN.findall(request)

        for path in paths:
            # Check for path traversal attempts
            if '..' in path and '/../' in path:
                # Multiple traversals in sequence
                traversal_count = path.count('/../')
                if traversal_count > 2:
                    issues.append(f"Suspicious path traversal: {path}")

            # Check for obviously invalid paths
            if '//' in path and not path.startswith('//'):  # Not a network path
                issues.append(f"Path contains double slash: {path}")

            # Check for null bytes (common injection)
            if '\x00' in path:
                issues.append(f"Path contains null byte: {path}")

        return issues
