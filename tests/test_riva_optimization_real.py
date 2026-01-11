"""Real integration tests for RIVA optimization.

Unlike test_optimization_integration.py which tests components in isolation,
these tests verify the optimization system behavior with realistic scenarios.

Note: Full work() loop testing requires complete mock implementations of
sandbox, LLM, and checkpoint. These tests focus on the optimization
subsystem integration that we can verify independently.
"""

from __future__ import annotations

import pytest
from dataclasses import dataclass, field
from typing import Any, Callable

import uuid

from reos.code_mode.intention import (
    Action,
    ActionType,
    Intention,
    IntentionStatus,
    Judgment,
    Cycle,
)
from reos.code_mode.optimization import (
    create_optimized_context,
    create_minimal_context,
    create_paranoid_context,
    assess_risk,
    analyze_complexity,
    RiskLevel,
    TrustBudget,
)
from reos.code_mode.optimization.trust import create_trust_budget
from reos.code_mode.optimization.verification import VerificationBatcher


def create_test_intention(what: str, acceptance: str) -> Intention:
    """Helper to create Intention with auto-generated ID."""
    return Intention(
        id=str(uuid.uuid4())[:8],
        what=what,
        acceptance=acceptance,
    )


# =============================================================================
# Empty stubs for context creation (not used for behavior)
# =============================================================================

class StubSandbox:
    pass

class StubLLM:
    pass

class StubCheckpoint:
    pass


# =============================================================================
# Test Cases: Trust Budget + Risk Integration (Real Behavior)
# =============================================================================


class TestTrustRiskIntegration:
    """Test that trust budget correctly interacts with risk assessment."""

    def test_high_risk_never_skips_verification(self) -> None:
        """HIGH risk actions must ALWAYS be verified, regardless of trust."""
        trust = create_trust_budget(initial=100)

        # Create HIGH risk action (command type)
        action = Action(type=ActionType.COMMAND, content="rm -rf /tmp/test")
        risk = assess_risk(action)

        assert risk.level == RiskLevel.HIGH

        # Even at max trust, should verify
        should_verify = trust.should_verify(risk)
        assert should_verify is True

        # Trust should NOT be depleted for verification (only for skipping)
        # But verification count should increase
        assert trust.verifications_performed == 1

    def test_low_risk_can_skip_at_high_trust(self) -> None:
        """LOW risk actions can skip verification when trust > 70."""
        trust = create_trust_budget(initial=100)

        action = Action(type=ActionType.EDIT, content="import json")
        risk = assess_risk(action)

        assert risk.level == RiskLevel.LOW

        # With high trust, should skip
        should_verify = trust.should_verify(risk)
        assert should_verify is False

        # Should have recorded skip and depleted trust slightly
        assert trust.verifications_skipped == 1
        assert trust.remaining < 100  # Trust spent on skip

    def test_low_risk_must_verify_at_low_trust(self) -> None:
        """LOW risk actions must verify when trust <= floor."""
        trust = create_trust_budget(initial=100, floor=20)
        trust.remaining = 20  # At floor

        action = Action(type=ActionType.EDIT, content="import json")
        risk = assess_risk(action)

        # Even LOW risk must verify at floor
        should_verify = trust.should_verify(risk)
        assert should_verify is True

        assert trust.verifications_performed == 1
        assert trust.verifications_skipped == 0

    def test_trust_depletion_progression(self) -> None:
        """Trust should deplete on skips and recover on verification success."""
        trust = create_trust_budget(initial=100)
        action = Action(type=ActionType.EDIT, content="x = 1")
        risk = assess_risk(action)

        # Skip multiple LOW risk actions
        initial_trust = trust.remaining
        skips = 0

        while trust.remaining > 70:  # Keep skipping until threshold
            if not trust.should_verify(risk):
                skips += 1
            else:
                break

        # Should have skipped some and depleted trust
        assert skips > 0
        assert trust.remaining < initial_trust

        # Now replenish
        trust.replenish(30)

        # Trust should be restored (up to initial)
        assert trust.remaining >= 70

    def test_medium_risk_threshold_boundary(self) -> None:
        """MEDIUM risk can only skip at very high trust (> 85)."""
        trust = create_trust_budget(initial=100)

        # MEDIUM risk action (e.g., creating a file)
        action = Action(type=ActionType.CREATE, content="new_file.py")
        risk = assess_risk(action)

        # At 100 trust, should be able to skip MEDIUM
        trust.remaining = 90
        should_verify = trust.should_verify(risk)
        # MEDIUM can skip above 85
        assert should_verify is False or trust.remaining <= 85

        # At 80 trust, should NOT be able to skip MEDIUM
        trust = create_trust_budget(initial=100)
        trust.remaining = 80
        action = Action(type=ActionType.CREATE, content="new_file.py")
        risk = assess_risk(action)
        should_verify = trust.should_verify(risk)
        assert should_verify is True


# =============================================================================
# Test Cases: Verification Batcher Real Behavior
# =============================================================================


class TestVerificationBatcherBehavior:
    """Test verification batcher's actual batch verification logic."""

    def test_empty_batch_returns_success(self) -> None:
        """Empty batch should return success."""
        batcher = VerificationBatcher()

        result = batcher.flush()

        assert result.success is True
        assert result.passed_count == 0
        assert result.failed_count == 0

    def test_heuristic_verification_success_indicators(self) -> None:
        """Heuristic verification should recognize success indicators."""
        batcher = VerificationBatcher()  # No LLM, uses heuristics

        action = Action(type=ActionType.CREATE, content="test.py")

        # Result with success indicator
        batcher.defer(action, "File created successfully", "file exists")
        result = batcher.flush()

        assert result.success is True
        assert result.passed_count == 1

    def test_heuristic_verification_failure_indicators(self) -> None:
        """Heuristic verification should recognize failure indicators."""
        batcher = VerificationBatcher()

        action = Action(type=ActionType.CREATE, content="test.py")

        # Result with error indicator
        batcher.defer(action, "Error: permission denied", "file exists")
        result = batcher.flush()

        assert result.success is False
        assert result.failed_count == 1
        assert len(result.failures) == 1

    def test_batch_multiple_items(self) -> None:
        """Batch should handle multiple items."""
        batcher = VerificationBatcher()

        # Add multiple items with mixed results
        action1 = Action(type=ActionType.CREATE, content="a.py")
        action2 = Action(type=ActionType.EDIT, content="b.py")
        action3 = Action(type=ActionType.CREATE, content="c.py")

        batcher.defer(action1, "File created successfully", "file exists")
        batcher.defer(action2, "Edit complete", "line added")
        batcher.defer(action3, "Error: disk full", "file exists")

        assert batcher.pending_count == 3

        result = batcher.flush()

        assert result.passed_count == 2
        assert result.failed_count == 1
        assert batcher.pending_count == 0  # Cleared after flush

    def test_heuristic_keyword_matching(self) -> None:
        """Heuristic should match expected keywords in result."""
        batcher = VerificationBatcher()

        action = Action(type=ActionType.EDIT, content="add import")

        # Result mentions expected outcome
        batcher.defer(action, "Added import statement to file", "import added")
        result = batcher.flush()

        # Should match because result contains expected words
        assert result.success is True

    def test_heuristic_defaults_to_failure(self) -> None:
        """Heuristic should default to failure when unclear."""
        batcher = VerificationBatcher()

        action = Action(type=ActionType.EDIT, content="do something")

        # Ambiguous result - no success/failure indicators
        batcher.defer(action, "xyz123", "something done")
        result = batcher.flush()

        # Should default to failure when unclear
        assert result.success is False


# =============================================================================
# Test Cases: Risk Assessment Detailed Behavior
# =============================================================================


class TestRiskAssessmentBehavior:
    """Test risk assessment with various patterns."""

    def test_read_only_commands_are_low_risk(self) -> None:
        """Read-only patterns like ls, cat should be LOW risk."""
        read_only = [
            "ls -la",
            "cat file.txt",
            "grep pattern file",
        ]

        for cmd in read_only:
            action = Action(type=ActionType.COMMAND, content=cmd)
            risk = assess_risk(action)
            assert risk.level == RiskLevel.LOW, f"Read-only '{cmd}' should be LOW risk"

    def test_destructive_commands_are_high_risk(self) -> None:
        """Destructive commands like rm -rf should be HIGH risk."""
        action = Action(type=ActionType.COMMAND, content="rm -rf /tmp/test")
        risk = assess_risk(action)
        assert risk.level == RiskLevel.HIGH

    def test_delete_type_is_medium_risk(self) -> None:
        """DELETE action type is MEDIUM risk (unless content escalates)."""
        action = Action(type=ActionType.DELETE, content="important_file.py")
        risk = assess_risk(action)
        assert risk.level == RiskLevel.MEDIUM
        assert "action_type_delete" in risk.factors

    def test_create_type_is_medium_risk(self) -> None:
        """CREATE action should be MEDIUM risk."""
        action = Action(type=ActionType.CREATE, content="new_file.py")
        risk = assess_risk(action)
        assert risk.level == RiskLevel.MEDIUM

    def test_edit_with_boilerplate_is_low_risk(self) -> None:
        """EDIT with boilerplate patterns is LOW risk."""
        action = Action(type=ActionType.EDIT, content="import json")
        risk = assess_risk(action)
        assert risk.level == RiskLevel.LOW
        assert "boilerplate_import" in risk.factors

    def test_edit_plain_is_medium_risk(self) -> None:
        """EDIT without special patterns is MEDIUM risk."""
        action = Action(type=ActionType.EDIT, content="x = 1")
        risk = assess_risk(action)
        assert risk.level == RiskLevel.MEDIUM

    def test_query_type_is_low_risk(self) -> None:
        """QUERY action should be LOW risk."""
        action = Action(type=ActionType.QUERY, content="search for files")
        risk = assess_risk(action)
        assert risk.level == RiskLevel.LOW

    def test_dangerous_content_escalates_risk(self) -> None:
        """Dangerous patterns in content should escalate to HIGH risk."""
        dangerous_patterns = [
            ("rm -rf /", "destructive_rm"),
            ("password = 'secret'", "security_password"),
            ("sudo apt install", "system_sudo"),
            ("fetch(api_url)", "external_http"),
        ]

        for pattern, expected_factor in dangerous_patterns:
            action = Action(type=ActionType.EDIT, content=pattern)
            risk = assess_risk(action)
            assert risk.level == RiskLevel.HIGH, \
                f"Pattern '{pattern[:30]}' should be HIGH risk"


# =============================================================================
# Test Cases: Complexity Analysis
# =============================================================================


class TestComplexityAnalysis:
    """Test complexity analysis behavior."""

    def test_simple_task_low_complexity(self) -> None:
        """Simple, well-scoped tasks should have low score."""
        complexity = analyze_complexity(
            what="Add json import to data_parser.py",
            acceptance="json module is imported at top of file",
        )

        # Score should be relatively low for a simple task
        # The exact value depends on implementation
        assert complexity.score <= 0.5

    def test_external_deps_flagged(self) -> None:
        """Tasks mentioning APIs or databases should flag external deps."""
        complexity = analyze_complexity(
            what="Fetch data from REST API and store in database",
            acceptance="Data stored in database",
        )

        # Should detect external dependencies
        assert complexity.has_external_deps is True

    def test_ambiguous_scope_flagged(self) -> None:
        """Ambiguous tasks should be flagged."""
        complexity = analyze_complexity(
            what="Improve the code",
            acceptance="Code is better",
        )

        assert complexity.scope_ambiguous is True


# =============================================================================
# Test Cases: Context Factory Behavior
# =============================================================================


class TestContextFactoryBehavior:
    """Test that factory functions produce correct context configurations."""

    def test_optimized_context_has_all_components(self) -> None:
        """Optimized context should have metrics, trust, and batcher."""
        ctx = create_optimized_context(
            sandbox=StubSandbox(),
            llm=StubLLM(),
            checkpoint=StubCheckpoint(),
        )

        assert ctx.metrics is not None
        assert ctx.trust_budget is not None
        assert ctx.verification_batcher is not None

    def test_minimal_context_has_no_optimization(self) -> None:
        """Minimal context should have no optimization components."""
        ctx = create_minimal_context(
            sandbox=StubSandbox(),
            llm=StubLLM(),
            checkpoint=StubCheckpoint(),
        )

        assert ctx.metrics is None
        assert ctx.trust_budget is None
        assert ctx.verification_batcher is None

    def test_paranoid_context_starts_at_floor(self) -> None:
        """Paranoid context should start at trust floor."""
        ctx = create_paranoid_context(
            sandbox=StubSandbox(),
            llm=StubLLM(),
            checkpoint=StubCheckpoint(),
        )

        assert ctx.trust_budget is not None
        assert ctx.trust_budget.remaining == ctx.trust_budget.floor

    def test_custom_trust_settings(self) -> None:
        """Factory should respect custom trust settings."""
        ctx = create_optimized_context(
            sandbox=StubSandbox(),
            llm=StubLLM(),
            checkpoint=StubCheckpoint(),
            initial_trust=50,
            trust_floor=10,
        )

        assert ctx.trust_budget.remaining == 50
        assert ctx.trust_budget.floor == 10


# =============================================================================
# Test Cases: Trust Budget Cost Model Validation
# =============================================================================


class TestTrustCostModel:
    """Validate the trust budget cost model calculations."""

    def test_skip_cost_matches_risk_level(self) -> None:
        """Verify skip costs match risk levels."""
        trust = create_trust_budget(initial=100)

        # LOW risk skip should cost 2 (5 // 2)
        low_action = Action(type=ActionType.EDIT, content="import json")  # Boilerplate = LOW
        low_risk = assess_risk(low_action)
        assert low_risk.level == RiskLevel.LOW

        initial = trust.remaining
        trust.should_verify(low_risk)  # Will skip at high trust

        assert trust.remaining == initial - 2  # 5 // 2 = 2

    def test_medium_risk_skip_cost(self) -> None:
        """MEDIUM risk skip should cost 7 (15 // 2)."""
        trust = create_trust_budget(initial=100)

        # MEDIUM risk (plain edit, no special patterns)
        med_action = Action(type=ActionType.EDIT, content="x = calculate_value()")
        med_risk = assess_risk(med_action)
        assert med_risk.level == RiskLevel.MEDIUM

        initial = trust.remaining
        # MEDIUM can only skip above 85 trust
        trust.should_verify(med_risk)  # Will skip at 100 trust

        assert trust.remaining == initial - 7  # 15 // 2 = 7

    def test_replenish_caps_at_initial(self) -> None:
        """Replenish should not exceed initial trust."""
        trust = create_trust_budget(initial=100)

        trust.replenish(50)

        assert trust.remaining == 100  # Capped at initial

    def test_deplete_floors_at_minimum(self) -> None:
        """Deplete should not go below floor."""
        trust = create_trust_budget(initial=100, floor=20)

        trust.remaining = 30
        trust.deplete(50)  # Would go to -20

        assert trust.remaining == 20  # Floors at minimum

    def test_failure_caught_replenishes(self) -> None:
        """Catching a failure should replenish trust."""
        trust = create_trust_budget(initial=100)
        trust.remaining = 80

        trust.record_failure_caught()

        assert trust.remaining == 85  # +5 for catching failure
        assert trust.failures_caught == 1


# =============================================================================
# Test Cases: Fast Path ADD_IMPORT Handler
# =============================================================================


class TestAddImportFastPath:
    """Test the ADD_IMPORT fast path handler helper functions."""

    def test_extract_file_path_with_to(self) -> None:
        """Extract file path from 'add import X to file.py' pattern."""
        from reos.code_mode.optimization.fast_path import _extract_file_path

        result = _extract_file_path("add import json to src/utils/parser.py")
        assert result == "src/utils/parser.py"

    def test_extract_file_path_with_in(self) -> None:
        """Extract file path from 'import X in file.py' pattern."""
        from reos.code_mode.optimization.fast_path import _extract_file_path

        result = _extract_file_path("import datetime in lib/helpers.py")
        assert result == "lib/helpers.py"

    def test_extract_file_path_with_colon(self) -> None:
        """Extract file path from 'file.py: add import X' pattern."""
        from reos.code_mode.optimization.fast_path import _extract_file_path

        result = _extract_file_path("src/main.py: add import os")
        assert result == "src/main.py"

    def test_extract_file_path_fallback(self) -> None:
        """Extract file path when it's just mentioned."""
        from reos.code_mode.optimization.fast_path import _extract_file_path

        result = _extract_file_path("add import json utils.py")
        assert result == "utils.py"

    def test_extract_file_path_none(self) -> None:
        """Return None when no file path found."""
        from reos.code_mode.optimization.fast_path import _extract_file_path

        result = _extract_file_path("add import json")
        assert result is None

    def test_extract_import_statement_simple(self) -> None:
        """Extract simple import statement."""
        from reos.code_mode.optimization.fast_path import _extract_import_statement

        result = _extract_import_statement("add import json to file.py")
        assert result == "import json"

    def test_extract_import_statement_from(self) -> None:
        """Extract 'from X import Y' statement."""
        from reos.code_mode.optimization.fast_path import _extract_import_statement

        result = _extract_import_statement("add from typing import Optional to file.py")
        assert result == "from typing import Optional"

    def test_extract_import_statement_with_alias(self) -> None:
        """Extract import with alias."""
        from reos.code_mode.optimization.fast_path import _extract_import_statement

        result = _extract_import_statement("add import numpy as np to file.py")
        assert result == "import numpy as np"

    def test_extract_import_statement_none(self) -> None:
        """Return None when no import found."""
        from reos.code_mode.optimization.fast_path import _extract_import_statement

        result = _extract_import_statement("fix the function in file.py")
        assert result is None

    def test_find_import_insert_position_after_imports(self) -> None:
        """Insert after existing imports."""
        from reos.code_mode.optimization.fast_path import _find_import_insert_position

        lines = [
            "import os\n",
            "import sys\n",
            "\n",
            "def main():\n",
            "    pass\n",
        ]
        pos = _find_import_insert_position(lines, "import json")
        assert pos == 2  # After the last import

    def test_find_import_insert_position_after_docstring(self) -> None:
        """Insert after module docstring when no imports."""
        from reos.code_mode.optimization.fast_path import _find_import_insert_position

        lines = [
            '"""Module docstring."""\n',
            "\n",
            "def main():\n",
        ]
        pos = _find_import_insert_position(lines, "import json")
        assert pos == 1  # After the docstring

    def test_find_import_insert_position_at_beginning(self) -> None:
        """Insert at beginning when no docstring or imports."""
        from reos.code_mode.optimization.fast_path import _find_import_insert_position

        lines = [
            "def main():\n",
            "    pass\n",
        ]
        pos = _find_import_insert_position(lines, "import json")
        assert pos == 0  # At the beginning

    def test_verify_python_syntax_valid(self) -> None:
        """Valid Python syntax should return True."""
        from reos.code_mode.optimization.fast_path import _verify_python_syntax

        content = "import json\n\ndef main():\n    pass\n"
        assert _verify_python_syntax(content, "test.py") is True

    def test_verify_python_syntax_invalid(self) -> None:
        """Invalid Python syntax should return False."""
        from reos.code_mode.optimization.fast_path import _verify_python_syntax

        content = "import json\n\ndef main(\n    pass\n"  # Missing closing paren
        assert _verify_python_syntax(content, "test.py") is False

    def test_build_import_edit_at_beginning(self) -> None:
        """Build edit for inserting at beginning."""
        from reos.code_mode.optimization.fast_path import _build_import_edit

        lines = ["def main():\n", "    pass\n"]
        old_str, new_str = _build_import_edit(lines, 0, "import json\n", "".join(lines))
        assert old_str == "def main():\n"
        assert new_str == "import json\ndef main():\n"

    def test_build_import_edit_in_middle(self) -> None:
        """Build edit for inserting in middle."""
        from reos.code_mode.optimization.fast_path import _build_import_edit

        lines = ["import os\n", "\n", "def main():\n"]
        old_str, new_str = _build_import_edit(lines, 1, "import json\n", "".join(lines))
        assert old_str == "import os\n"
        assert new_str == "import os\nimport json\n"

    def test_pattern_detection_add_import(self) -> None:
        """Pattern detection should match ADD_IMPORT."""
        from reos.code_mode.optimization.fast_path import (
            detect_pattern,
            FastPathPattern,
        )

        match = detect_pattern("add import json to file.py")
        assert match.is_match
        assert match.pattern == FastPathPattern.ADD_IMPORT

    def test_available_patterns_includes_add_import(self) -> None:
        """ADD_IMPORT should be in available patterns."""
        from reos.code_mode.optimization.fast_path import (
            get_available_patterns,
            FastPathPattern,
        )

        available = get_available_patterns()
        assert FastPathPattern.ADD_IMPORT in available
