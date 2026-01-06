"""Tests for Test Generator."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from reos.code_mode.contract import (
    AcceptanceCriterion,
    ContractBuilder,
    CriterionType,
    TestSpecification,
)
from reos.code_mode.intent import CodebaseIntent, DiscoveredIntent, PlayIntent, PromptIntent
from reos.code_mode.test_generator import TestGenerator


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_sandbox(tmp_path: Path) -> MagicMock:
    """Create a mock sandbox."""
    sandbox = MagicMock()
    sandbox.repo_path = tmp_path
    sandbox.read_file = MagicMock(return_value="# file content")
    sandbox.write_file = MagicMock()
    sandbox.run_command = MagicMock(return_value=(0, "OK", ""))
    sandbox.grep = MagicMock(return_value=[])
    return sandbox


@pytest.fixture
def sample_intent() -> DiscoveredIntent:
    """Create a sample discovered intent."""
    return DiscoveredIntent(
        goal="Add a function to calculate fibonacci numbers",
        what="Create fibonacci(n) function in math_utils.py",
        why="Need to calculate fibonacci sequence",
        how_constraints=[],
        confidence=0.9,
        ambiguities=[],
        assumptions=[],
        prompt_intent=PromptIntent(
            raw_prompt="create fibonacci function",
            action_verb="create",
            target="function fibonacci",
            constraints=[],
            examples=[],
            summary="Create fibonacci function",
        ),
        play_intent=PlayIntent(
            act_goal="implement math utilities",
            act_artifact="math_utils.py",
            scene_context="",
            recent_work=[],
            knowledge_hints=[],
        ),
        codebase_intent=CodebaseIntent(
            language="python",
            architecture_style="modular",
            conventions=[],
            related_files=["src/math_utils.py"],
            existing_patterns=["def function_name(args)"],
            test_patterns="tests/test_math_utils.py",
        ),
    )


# =============================================================================
# TestSpecification Tests
# =============================================================================


class TestTestSpecification:
    """Tests for TestSpecification dataclass."""

    def test_create_specification(self) -> None:
        """Should create a test specification."""
        spec = TestSpecification(
            test_code="def test_foo(): pass",
            test_file="tests/test_foo.py",
            test_function="test_foo",
            imports=["pytest"],
            rationale="Tests that foo works",
        )

        assert spec.test_code == "def test_foo(): pass"
        assert spec.test_file == "tests/test_foo.py"
        assert spec.test_function == "test_foo"
        assert spec.imports == ["pytest"]
        assert spec.rationale == "Tests that foo works"

    def test_to_dict(self) -> None:
        """Should serialize to dictionary."""
        spec = TestSpecification(
            test_code="def test_bar(): pass",
            test_file="tests/test_bar.py",
            test_function="test_bar",
        )

        d = spec.to_dict()

        assert d["test_code"] == "def test_bar(): pass"
        assert d["test_file"] == "tests/test_bar.py"
        assert d["test_function"] == "test_bar"
        assert d["imports"] == []
        assert d["setup_code"] == ""
        assert d["rationale"] == ""


# =============================================================================
# TestGenerator Tests
# =============================================================================


class TestTestGeneratorInit:
    """Tests for TestGenerator initialization."""

    def test_create_generator(self, mock_sandbox: MagicMock) -> None:
        """Should create a test generator."""
        gen = TestGenerator(mock_sandbox)

        assert gen.sandbox == mock_sandbox
        assert gen._ollama is None

    def test_create_with_ollama(self, mock_sandbox: MagicMock) -> None:
        """Should create with ollama client."""
        ollama = MagicMock()
        gen = TestGenerator(mock_sandbox, ollama=ollama)

        assert gen._ollama == ollama


class TestTestGeneratorHeuristic:
    """Tests for heuristic test generation."""

    def test_generate_function_test(
        self, mock_sandbox: MagicMock, sample_intent: DiscoveredIntent
    ) -> None:
        """Should generate test for function."""
        gen = TestGenerator(mock_sandbox)

        spec = gen.generate(sample_intent)

        assert spec.test_file.endswith(".py")
        assert "def test_" in spec.test_code
        assert spec.test_function.startswith("test_")
        assert "pytest" in spec.imports

    def test_generate_class_test(self, mock_sandbox: MagicMock) -> None:
        """Should generate test for class."""
        intent = DiscoveredIntent(
            goal="Create a User class",
            what="Create User class in models.py",
            why="Need user model",
            how_constraints=[],
            confidence=0.9,
            ambiguities=[],
            assumptions=[],
            prompt_intent=PromptIntent(
                raw_prompt="create User class",
                action_verb="create",
                target="class User",
                constraints=[],
                examples=[],
                summary="Create User class",
            ),
            play_intent=PlayIntent(
                act_goal="implement models",
                act_artifact="models.py",
                scene_context="",
                recent_work=[],
                knowledge_hints=[],
            ),
            codebase_intent=CodebaseIntent(
                language="python",
                architecture_style="modular",
                conventions=[],
                related_files=["src/models.py"],
                existing_patterns=[],
                test_patterns="tests/",
            ),
        )

        gen = TestGenerator(mock_sandbox)
        spec = gen.generate(intent)

        assert "class" in spec.test_code.lower() or "instantiat" in spec.test_code.lower()
        assert spec.test_function.startswith("test_")

    def test_generate_api_test(self, mock_sandbox: MagicMock) -> None:
        """Should generate test for API endpoint."""
        intent = DiscoveredIntent(
            goal="Add /users endpoint",
            what="Create GET /users endpoint",
            why="Need to list users",
            how_constraints=[],
            confidence=0.9,
            ambiguities=[],
            assumptions=[],
            prompt_intent=PromptIntent(
                raw_prompt="add /users endpoint",
                action_verb="add",
                target="API endpoint /users",
                constraints=[],
                examples=[],
                summary="Add /users endpoint",
            ),
            play_intent=PlayIntent(
                act_goal="implement API",
                act_artifact="api.py",
                scene_context="",
                recent_work=[],
                knowledge_hints=[],
            ),
            codebase_intent=CodebaseIntent(
                language="python",
                architecture_style="modular",
                conventions=[],
                related_files=[],
                existing_patterns=[],
                test_patterns="",
            ),
        )

        gen = TestGenerator(mock_sandbox)
        spec = gen.generate(intent)

        assert "endpoint" in spec.test_code.lower() or "200" in spec.test_code
        assert spec.test_function.startswith("test_")

    def test_generate_generic_test(self, mock_sandbox: MagicMock) -> None:
        """Should generate generic test for unknown patterns."""
        intent = DiscoveredIntent(
            goal="Do something complex",
            what="Complex task",
            why="Reasons",
            how_constraints=[],
            confidence=0.5,
            ambiguities=["unclear requirements"],
            assumptions=[],
            prompt_intent=PromptIntent(
                raw_prompt="do something complex",
                action_verb="do",
                target="something",
                constraints=[],
                examples=[],
                summary="Do something complex",
            ),
            play_intent=PlayIntent(
                act_goal="complete task",
                act_artifact="output",
                scene_context="",
                recent_work=[],
                knowledge_hints=[],
            ),
            codebase_intent=CodebaseIntent(
                language="python",
                architecture_style="unknown",
                conventions=[],
                related_files=[],
                existing_patterns=[],
                test_patterns="",
            ),
        )

        gen = TestGenerator(mock_sandbox)
        spec = gen.generate(intent)

        assert spec.test_function == "test_feature_implemented"
        assert "pytest" in spec.imports


class TestTestGeneratorHelpers:
    """Tests for helper methods."""

    def test_extract_name_simple(self, mock_sandbox: MagicMock) -> None:
        """Should extract simple name."""
        gen = TestGenerator(mock_sandbox)

        name = gen._extract_name("function fibonacci", "function")
        assert name == "fibonacci"

    def test_extract_name_with_prefix(self, mock_sandbox: MagicMock) -> None:
        """Should extract name with prefix."""
        gen = TestGenerator(mock_sandbox)

        name = gen._extract_name("a function called calculate", "function")
        assert name == "calculate"

    def test_extract_name_named_pattern(self, mock_sandbox: MagicMock) -> None:
        """Should extract name from 'named X' pattern."""
        gen = TestGenerator(mock_sandbox)

        name = gen._extract_name("method named process_data", "method")
        assert name == "process_data"

    def test_sanitize_name(self, mock_sandbox: MagicMock) -> None:
        """Should sanitize name to valid identifier."""
        gen = TestGenerator(mock_sandbox)

        assert gen._sanitize_name("hello-world") == "hello_world"
        assert gen._sanitize_name("foo bar") == "foo_bar"
        assert gen._sanitize_name("123abc") == "f_123abc"
        assert gen._sanitize_name("___test___") == "test"

    def test_infer_test_file(
        self, mock_sandbox: MagicMock, sample_intent: DiscoveredIntent
    ) -> None:
        """Should infer test file from intent."""
        gen = TestGenerator(mock_sandbox)

        test_file = gen._infer_test_file(sample_intent)

        assert test_file.endswith(".py")
        assert "test" in test_file

    def test_infer_import_path(
        self, mock_sandbox: MagicMock, sample_intent: DiscoveredIntent
    ) -> None:
        """Should infer import path from intent."""
        gen = TestGenerator(mock_sandbox)

        import_path = gen._infer_import_path(sample_intent)

        assert "math_utils" in import_path
        assert ".py" not in import_path


# =============================================================================
# GENERATED_TEST_PASSES Criterion Tests
# =============================================================================


class TestGeneratedTestPassesCriterion:
    """Tests for GENERATED_TEST_PASSES criterion type."""

    def test_criterion_with_test_spec(self) -> None:
        """Should create criterion with test specification."""
        spec = TestSpecification(
            test_code="def test_foo(): assert True",
            test_file="tests/test_foo.py",
            test_function="test_foo",
        )

        criterion = AcceptanceCriterion(
            id="test-123",
            type=CriterionType.GENERATED_TEST_PASSES,
            description="Generated test passes",
            test_spec=spec,
        )

        assert criterion.type == CriterionType.GENERATED_TEST_PASSES
        assert criterion.test_spec == spec
        assert criterion.test_spec.test_function == "test_foo"

    def test_verify_no_test_spec(self, mock_sandbox: MagicMock) -> None:
        """Should fail verification without test spec."""
        criterion = AcceptanceCriterion(
            id="test-123",
            type=CriterionType.GENERATED_TEST_PASSES,
            description="Generated test passes",
            test_spec=None,
        )

        result = criterion.verify(mock_sandbox)

        assert result is False
        assert "No test specification" in criterion.verification_output

    def test_verify_creates_test_file(self, mock_sandbox: MagicMock) -> None:
        """Should create test file if it doesn't exist."""
        spec = TestSpecification(
            test_code="def test_foo(): assert True",
            test_file="tests/test_foo.py",
            test_function="test_foo",
        )

        criterion = AcceptanceCriterion(
            id="test-123",
            type=CriterionType.GENERATED_TEST_PASSES,
            description="Generated test passes",
            test_spec=spec,
        )

        # Simulate file not found on first read
        mock_sandbox.read_file.side_effect = FileNotFoundError("not found")
        mock_sandbox.run_command.return_value = (0, "PASSED", "")

        result = criterion.verify(mock_sandbox)

        # Should have written the test file
        mock_sandbox.write_file.assert_called_once_with(
            "tests/test_foo.py",
            "def test_foo(): assert True",
        )
        assert result is True

    def test_verify_runs_specific_test(self, mock_sandbox: MagicMock) -> None:
        """Should run only the specific test function."""
        spec = TestSpecification(
            test_code="def test_bar(): pass",
            test_file="tests/test_bar.py",
            test_function="test_bar",
        )

        criterion = AcceptanceCriterion(
            id="test-456",
            type=CriterionType.GENERATED_TEST_PASSES,
            description="Generated test passes",
            test_spec=spec,
        )

        mock_sandbox.run_command.return_value = (0, "PASSED", "")

        criterion.verify(mock_sandbox)

        # Should run pytest with specific test path
        call_args = mock_sandbox.run_command.call_args
        assert "tests/test_bar.py::test_bar" in call_args[0][0]


# =============================================================================
# ContractBuilder Integration Tests
# =============================================================================


class TestContractBuilderTestFirst:
    """Tests for ContractBuilder with test-first mode."""

    def test_builder_with_test_generator(
        self, mock_sandbox: MagicMock, sample_intent: DiscoveredIntent
    ) -> None:
        """Should use test generator when provided."""
        test_gen = TestGenerator(mock_sandbox)
        builder = ContractBuilder(
            mock_sandbox,
            test_generator=test_gen,
            test_first=True,
        )

        contract = builder.build_from_intent(sample_intent)

        # Should have GENERATED_TEST_PASSES criterion
        generated_criteria = [
            c for c in contract.acceptance_criteria
            if c.type == CriterionType.GENERATED_TEST_PASSES
        ]
        assert len(generated_criteria) >= 1

        # First criterion should have test_spec
        if generated_criteria:
            assert generated_criteria[0].test_spec is not None
            assert generated_criteria[0].test_spec.test_code

    def test_builder_creates_test_step_first(
        self, mock_sandbox: MagicMock, sample_intent: DiscoveredIntent
    ) -> None:
        """Should create test file step before implementation steps."""
        test_gen = TestGenerator(mock_sandbox)
        builder = ContractBuilder(
            mock_sandbox,
            test_generator=test_gen,
            test_first=True,
        )

        contract = builder.build_from_intent(sample_intent)

        # First step should be writing test file
        if contract.steps:
            first_step = contract.steps[0]
            assert first_step.action == "create_file"
            assert "test" in first_step.description.lower()

    def test_builder_without_test_first(
        self, mock_sandbox: MagicMock, sample_intent: DiscoveredIntent
    ) -> None:
        """Should not generate test spec when test_first is False."""
        test_gen = TestGenerator(mock_sandbox)
        builder = ContractBuilder(
            mock_sandbox,
            test_generator=test_gen,
            test_first=False,
        )

        contract = builder.build_from_intent(sample_intent)

        # Should NOT have GENERATED_TEST_PASSES criterion
        generated_criteria = [
            c for c in contract.acceptance_criteria
            if c.type == CriterionType.GENERATED_TEST_PASSES
        ]
        assert len(generated_criteria) == 0

    def test_builder_without_test_generator(
        self, mock_sandbox: MagicMock, sample_intent: DiscoveredIntent
    ) -> None:
        """Should work without test generator."""
        builder = ContractBuilder(
            mock_sandbox,
            test_generator=None,
            test_first=True,
        )

        contract = builder.build_from_intent(sample_intent)

        # Should still create a contract with standard criteria
        assert len(contract.acceptance_criteria) > 0
        assert contract.intent_summary == sample_intent.goal
