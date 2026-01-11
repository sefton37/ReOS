"""Tests for risk assessment integration with RIVA.

Tests that the risk assessment module properly classifies actions
and integrates with metrics tracking.
"""

from __future__ import annotations

import pytest

from reos.code_mode.intention import Action, ActionType
from reos.code_mode.optimization.risk import (
    ActionRisk,
    RiskLevel,
    assess_risk,
    is_boilerplate,
)


class TestRiskAssessment:
    """Test the risk assessment module."""

    def test_high_risk_destructive_rm(self) -> None:
        """Destructive rm commands should be HIGH risk."""
        action = Action(
            type=ActionType.COMMAND,
            content="rm -rf /tmp/test",
        )
        risk = assess_risk(action)

        assert risk.level == RiskLevel.HIGH
        assert "destructive_rm" in risk.factors
        assert risk.requires_verification is True
        assert risk.can_batch is False

    def test_high_risk_security_password(self) -> None:
        """Actions involving passwords should be HIGH risk."""
        action = Action(
            type=ActionType.EDIT,
            content="password = os.environ['DB_PASSWORD']",
        )
        risk = assess_risk(action)

        assert risk.level == RiskLevel.HIGH
        assert "security_password" in risk.factors
        assert risk.requires_verification is True

    def test_high_risk_api_key(self) -> None:
        """Actions involving API keys should be HIGH risk."""
        action = Action(
            type=ActionType.EDIT,
            content="API_KEY = 'sk-xxx'",
        )
        risk = assess_risk(action)

        assert risk.level == RiskLevel.HIGH
        assert "security_api_key" in risk.factors

    def test_high_risk_external_http(self) -> None:
        """External HTTP calls should be HIGH risk."""
        action = Action(
            type=ActionType.EDIT,
            content="requests.get('https://api.example.com/data')",
        )
        risk = assess_risk(action)

        assert risk.level == RiskLevel.HIGH
        assert "external_http" in risk.factors

    def test_high_risk_sudo(self) -> None:
        """Sudo commands should be HIGH risk."""
        action = Action(
            type=ActionType.COMMAND,
            content="sudo apt-get install package",
        )
        risk = assess_risk(action)

        assert risk.level == RiskLevel.HIGH
        assert "system_sudo" in risk.factors

    def test_low_risk_query(self) -> None:
        """Query actions should be LOW risk."""
        action = Action(
            type=ActionType.QUERY,
            content="What is the current working directory?",
        )
        risk = assess_risk(action)

        assert risk.level == RiskLevel.LOW
        assert risk.requires_verification is False
        assert risk.can_batch is True

    def test_low_risk_import(self) -> None:
        """Import statements should be LOW risk."""
        action = Action(
            type=ActionType.EDIT,
            content="import os",
        )
        risk = assess_risk(action)

        # Import is boilerplate, should be LOW
        assert risk.level == RiskLevel.LOW
        assert "boilerplate_import" in risk.factors
        assert risk.can_batch is True

    def test_low_risk_read_only(self) -> None:
        """Read-only commands should be LOW risk."""
        action = Action(
            type=ActionType.COMMAND,
            content="ls -la /tmp",
        )
        risk = assess_risk(action)

        assert risk.level == RiskLevel.LOW
        assert "read_only_search" in risk.factors

    def test_medium_risk_normal_edit(self) -> None:
        """Normal code edits should be MEDIUM risk."""
        action = Action(
            type=ActionType.EDIT,
            content="def calculate_total(items): return sum(items)",
        )
        risk = assess_risk(action)

        assert risk.level == RiskLevel.MEDIUM
        assert risk.requires_verification is True
        assert risk.can_batch is True

    def test_medium_risk_create(self) -> None:
        """Create actions should default to MEDIUM risk."""
        action = Action(
            type=ActionType.CREATE,
            content="class UserService:\n    pass",
        )
        risk = assess_risk(action)

        # Create is tracked in factors
        assert "action_type_create" in risk.factors
        # Normal class creation is MEDIUM unless risky patterns
        assert risk.level == RiskLevel.MEDIUM

    def test_delete_action_type(self) -> None:
        """DELETE action type should be tracked in factors."""
        action = Action(
            type=ActionType.DELETE,
            content="remove old_file.py",
        )
        risk = assess_risk(action)

        assert "action_type_delete" in risk.factors

    def test_risk_to_dict(self) -> None:
        """ActionRisk should serialize properly."""
        action = Action(
            type=ActionType.EDIT,
            content="import json",
        )
        risk = assess_risk(action)
        data = risk.to_dict()

        assert "level" in data
        assert "factors" in data
        assert "requires_verification" in data
        assert "can_batch" in data
        assert data["level"] == risk.level.value


class TestBoilerplateDetection:
    """Test boilerplate code detection."""

    def test_import_is_boilerplate(self) -> None:
        """Import statements are boilerplate."""
        assert is_boilerplate("from typing import List") is True
        assert is_boilerplate("import os") is True

    def test_class_definition_is_boilerplate(self) -> None:
        """Class definitions are boilerplate."""
        assert is_boilerplate("class MyClass:") is True

    def test_dunder_method_is_boilerplate(self) -> None:
        """Dunder methods are boilerplate."""
        assert is_boilerplate("def __init__(self):") is True
        assert is_boilerplate("def __str__(self):") is True

    def test_decorator_is_boilerplate(self) -> None:
        """Decorators are boilerplate."""
        assert is_boilerplate("@property") is True
        assert is_boilerplate("@staticmethod") is True

    def test_docstring_is_boilerplate(self) -> None:
        """Docstrings are boilerplate."""
        assert is_boilerplate('"""This is a docstring."""') is True

    def test_complex_logic_not_boilerplate(self) -> None:
        """Complex logic is not boilerplate."""
        assert is_boilerplate("if x > 10 and y < 5:") is False
        assert is_boilerplate("result = process_data(input)") is False


class TestRiskEdgeCases:
    """Test edge cases in risk assessment."""

    def test_mixed_risk_factors(self) -> None:
        """High risk takes precedence over low risk factors."""
        # Code with both import (low) and password (high)
        action = Action(
            type=ActionType.EDIT,
            content="import secrets; password = secrets.token_hex()",
        )
        risk = assess_risk(action)

        # High risk should take precedence
        assert risk.level == RiskLevel.HIGH
        assert "security_password" in risk.factors
        assert "boilerplate_import" in risk.factors

    def test_empty_content(self) -> None:
        """Empty content should be MEDIUM risk (default)."""
        action = Action(
            type=ActionType.EDIT,
            content="",
        )
        risk = assess_risk(action)

        assert risk.level == RiskLevel.MEDIUM

    def test_database_drop(self) -> None:
        """Database DROP should be HIGH risk."""
        action = Action(
            type=ActionType.COMMAND,
            content="DROP TABLE users;",
        )
        risk = assess_risk(action)

        assert risk.level == RiskLevel.HIGH
        assert "destructive_drop" in risk.factors

    def test_chmod_system(self) -> None:
        """chmod commands should be HIGH risk."""
        action = Action(
            type=ActionType.COMMAND,
            content="chmod 777 script.sh",
        )
        risk = assess_risk(action)

        assert risk.level == RiskLevel.HIGH
        assert "system_chmod" in risk.factors

    def test_private_key(self) -> None:
        """Private key handling should be HIGH risk."""
        action = Action(
            type=ActionType.EDIT,
            content="private_key = load_key('~/.ssh/id_rsa')",
        )
        risk = assess_risk(action)

        assert risk.level == RiskLevel.HIGH
        assert "security_private_key" in risk.factors

    def test_print_statement_low_risk(self) -> None:
        """Print statements are read-only output, LOW risk."""
        action = Action(
            type=ActionType.EDIT,
            content="print('Hello, world!')",
        )
        risk = assess_risk(action)

        assert risk.level == RiskLevel.LOW
        assert "read_only_output" in risk.factors
