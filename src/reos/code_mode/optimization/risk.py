"""Action risk classification for confidence-based verification.

This module classifies actions by risk level to determine
verification requirements. High-risk actions always get verified.
Low-risk actions may skip individual verification.

Risk Levels:
- HIGH: Security, destructive, external APIs - always verify
- MEDIUM: Normal code changes - default verification
- LOW: Read-only, boilerplate - can defer/skip verification
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from reos.code_mode.intention import Action, ActionType

logger = logging.getLogger(__name__)


class RiskLevel(Enum):
    """Risk level for an action."""

    LOW = "low"  # Read-only, boilerplate, well-tested patterns
    MEDIUM = "medium"  # Normal code changes
    HIGH = "high"  # Security, destructive, external dependencies


@dataclass
class ActionRisk:
    """Risk assessment for an action.

    Attributes:
        level: Risk level (LOW, MEDIUM, HIGH)
        factors: List of factors that contributed to the assessment
        requires_verification: Whether this action requires individual verification
        can_batch: Whether verification can be batched with others
    """

    level: RiskLevel
    factors: list[str]
    requires_verification: bool
    can_batch: bool

    def to_dict(self) -> dict:
        """Serialize for logging."""
        return {
            "level": self.level.value,
            "factors": self.factors,
            "requires_verification": self.requires_verification,
            "can_batch": self.can_batch,
        }


# Patterns that indicate HIGH risk
HIGH_RISK_PATTERNS = [
    # Destructive operations
    (r"\brm\s+-rf?\b", "destructive_rm"),
    (r"\bdelete\b.*\bfile", "destructive_delete"),
    (r"\bdrop\b.*\btable", "destructive_drop"),
    (r"\btruncate\b", "destructive_truncate"),
    # Security sensitive
    (r"\bpassword\b", "security_password"),
    (r"\bsecret\b", "security_secret"),
    (r"\btoken\b", "security_token"),
    (r"\bapi[_-]?key\b", "security_api_key"),
    (r"\bcredential", "security_credential"),
    (r"\bprivate[_-]?key\b", "security_private_key"),
    # System modification
    (r"\bsudo\b", "system_sudo"),
    (r"\bchmod\b", "system_chmod"),
    (r"\bchown\b", "system_chown"),
    (r"\bsystemctl\b", "system_service"),
    # External dependencies
    (r"\bhttps?://", "external_http"),
    (r"\bfetch\b.*\bapi", "external_api"),
    (r"\bpost\b.*\brequest", "external_request"),
]

# Patterns that indicate LOW risk
LOW_RISK_PATTERNS = [
    # Read-only operations
    (r"\bls\b|\bfind\b|\bgrep\b", "read_only_search"),
    (r"\bcat\b|\bhead\b|\btail\b", "read_only_view"),
    (r"\bprint\b|\blog\b|\bdebug\b", "read_only_output"),
    # Boilerplate
    (r"\bimport\b", "boilerplate_import"),
    (r"\bdef\s+__init__", "boilerplate_init"),
    (r"@dataclass", "boilerplate_dataclass"),
    (r"@property", "boilerplate_property"),
    # Documentation
    (r'""".*"""', "documentation_docstring"),
    (r"#\s*TODO", "documentation_todo"),
    (r"#\s*type:", "documentation_type_hint"),
]


def assess_risk(
    action: "Action",
    context: str | None = None,
) -> ActionRisk:
    """Assess the risk level of an action.

    Args:
        action: The action to assess
        context: Optional context about what the action is doing

    Returns:
        ActionRisk with level and factors
    """
    from reos.code_mode.intention import ActionType

    factors: list[str] = []
    content_lower = action.content.lower()

    # Check action type first
    if action.type == ActionType.DELETE:
        factors.append("action_type_delete")
    elif action.type == ActionType.QUERY:
        factors.append("action_type_query")
    elif action.type == ActionType.CREATE:
        factors.append("action_type_create")

    # Check for HIGH risk patterns
    for pattern, factor in HIGH_RISK_PATTERNS:
        if re.search(pattern, content_lower, re.IGNORECASE):
            factors.append(factor)

    # Check for LOW risk patterns
    for pattern, factor in LOW_RISK_PATTERNS:
        if re.search(pattern, content_lower, re.IGNORECASE):
            factors.append(factor)

    # Determine level based on factors
    high_risk_factors = [f for f in factors if f.startswith(("destructive", "security", "system", "external"))]
    low_risk_factors = [f for f in factors if f.startswith(("read_only", "boilerplate", "documentation"))]

    if high_risk_factors:
        level = RiskLevel.HIGH
        requires_verification = True
        can_batch = False
    elif action.type == ActionType.QUERY:
        level = RiskLevel.LOW
        requires_verification = False
        can_batch = True
    elif low_risk_factors and not high_risk_factors:
        level = RiskLevel.LOW
        requires_verification = False
        can_batch = True
    else:
        level = RiskLevel.MEDIUM
        requires_verification = True
        can_batch = True

    return ActionRisk(
        level=level,
        factors=factors,
        requires_verification=requires_verification,
        can_batch=can_batch,
    )


def is_boilerplate(content: str) -> bool:
    """Check if content is boilerplate code.

    Boilerplate is code that follows well-known patterns
    and doesn't require careful verification.
    """
    boilerplate_patterns = [
        r"^from\s+\w+\s+import\s+",  # Import statement
        r"^import\s+\w+",  # Import statement
        r"^class\s+\w+\s*:",  # Class definition
        r"^def\s+__\w+__\s*\(",  # Dunder method
        r"^@\w+",  # Decorator
        r'^""".*"""$',  # Docstring
        r"^#.*$",  # Comment
        r"^\s*pass\s*$",  # Pass statement
        r"^\s*\.\.\.\s*$",  # Ellipsis
    ]

    for pattern in boilerplate_patterns:
        if re.match(pattern, content.strip(), re.MULTILINE):
            return True

    return False
