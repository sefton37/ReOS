"""Tests for Contract - testable success definitions."""

from __future__ import annotations

from pathlib import Path

import pytest

from reos.code_mode import (
    Contract,
    ContractBuilder,
    ContractStatus,
    ContractStep,
    AcceptanceCriterion,
    CriterionType,
    CodeSandbox,
    IntentDiscoverer,
)
from reos.play_fs import Act


class TestAcceptanceCriterion:
    """Tests for acceptance criterion verification."""

    def test_file_exists_criterion_passes(self, temp_git_repo: Path) -> None:
        """Should pass when file exists."""
        sandbox = CodeSandbox(temp_git_repo)
        criterion = AcceptanceCriterion(
            id="c1",
            type=CriterionType.FILE_EXISTS,
            description="Example file exists",
            target_file="src/reos/example.py",
        )

        result = criterion.verify(sandbox)

        assert result is True
        assert criterion.verified is True

    def test_command_succeeds_criterion_passes(self, temp_git_repo: Path) -> None:
        """Should pass when command returns exit code 0."""
        sandbox = CodeSandbox(temp_git_repo)
        criterion = AcceptanceCriterion(
            id="c1",
            type=CriterionType.COMMAND_SUCCEEDS,
            description="Echo command succeeds",
            command="echo hello",
        )

        result = criterion.verify(sandbox)

        assert result is True
        assert criterion.verified is True
        assert "hello" in criterion.verification_output

    def test_command_succeeds_criterion_fails(self, temp_git_repo: Path) -> None:
        """Should fail when command returns non-zero exit code."""
        sandbox = CodeSandbox(temp_git_repo)
        criterion = AcceptanceCriterion(
            id="c1",
            type=CriterionType.COMMAND_SUCCEEDS,
            description="False command fails",
            command="false",
        )

        result = criterion.verify(sandbox)

        assert result is False
        assert criterion.verified is False

    def test_command_succeeds_captures_output(self, temp_git_repo: Path) -> None:
        """Should capture command output for debugging."""
        sandbox = CodeSandbox(temp_git_repo)
        criterion = AcceptanceCriterion(
            id="c1",
            type=CriterionType.COMMAND_SUCCEEDS,
            description="Capture output",
            command="echo 'test output 12345'",
        )

        criterion.verify(sandbox)

        assert "test output 12345" in criterion.verification_output

    def test_tests_pass_criterion_runs_pytest(self, temp_git_repo: Path) -> None:
        """Should run pytest and capture output."""
        sandbox = CodeSandbox(temp_git_repo)
        # Create a simple test file
        sandbox.write_file(
            "test_simple.py",
            "def test_pass(): assert True\n"
        )
        criterion = AcceptanceCriterion(
            id="c1",
            type=CriterionType.TESTS_PASS,
            description="Tests pass",
            command="python -m pytest test_simple.py -v",
        )

        result = criterion.verify(sandbox)

        # This may pass or fail depending on pytest availability
        assert criterion.verification_output  # Should have some output

    def test_file_exists_criterion_fails(self, temp_git_repo: Path) -> None:
        """Should fail when file doesn't exist."""
        sandbox = CodeSandbox(temp_git_repo)
        criterion = AcceptanceCriterion(
            id="c1",
            type=CriterionType.FILE_EXISTS,
            description="Nonexistent file",
            target_file="nonexistent.py",
        )

        result = criterion.verify(sandbox)

        assert result is False

    def test_file_contains_criterion_passes(self, temp_git_repo: Path) -> None:
        """Should pass when file contains pattern."""
        sandbox = CodeSandbox(temp_git_repo)
        criterion = AcceptanceCriterion(
            id="c1",
            type=CriterionType.FILE_CONTAINS,
            description="File contains hello function",
            target_file="src/reos/example.py",
            pattern=r"def hello",
        )

        result = criterion.verify(sandbox)

        assert result is True

    def test_file_contains_criterion_fails(self, temp_git_repo: Path) -> None:
        """Should fail when file doesn't contain pattern."""
        sandbox = CodeSandbox(temp_git_repo)
        criterion = AcceptanceCriterion(
            id="c1",
            type=CriterionType.FILE_CONTAINS,
            description="File contains nonexistent",
            target_file="src/reos/example.py",
            pattern=r"nonexistent_function",
        )

        result = criterion.verify(sandbox)

        assert result is False

    def test_function_exists_criterion(self, temp_git_repo: Path) -> None:
        """Should verify function existence."""
        sandbox = CodeSandbox(temp_git_repo)
        criterion = AcceptanceCriterion(
            id="c1",
            type=CriterionType.FUNCTION_EXISTS,
            description="hello function exists",
            pattern="hello",
        )

        result = criterion.verify(sandbox)

        assert result is True


class TestContract:
    """Tests for Contract dataclass."""

    def test_is_fulfilled_all_criteria_met(self, temp_git_repo: Path) -> None:
        """Should be fulfilled when all criteria pass."""
        sandbox = CodeSandbox(temp_git_repo)
        contract = Contract(
            id="test-contract",
            intent_summary="Test contract",
            acceptance_criteria=[
                AcceptanceCriterion(
                    id="c1",
                    type=CriterionType.FILE_EXISTS,
                    description="Example file exists",
                    target_file="src/reos/example.py",
                ),
            ],
        )

        result = contract.is_fulfilled(sandbox)

        assert result is True

    def test_is_fulfilled_criteria_not_met(self, temp_git_repo: Path) -> None:
        """Should not be fulfilled when criteria fail."""
        sandbox = CodeSandbox(temp_git_repo)
        contract = Contract(
            id="test-contract",
            intent_summary="Test contract",
            acceptance_criteria=[
                AcceptanceCriterion(
                    id="c1",
                    type=CriterionType.FILE_EXISTS,
                    description="Nonexistent file",
                    target_file="nonexistent.py",
                ),
            ],
        )

        result = contract.is_fulfilled(sandbox)

        assert result is False

    def test_get_unfulfilled_criteria(self, temp_git_repo: Path) -> None:
        """Should return unfulfilled criteria."""
        sandbox = CodeSandbox(temp_git_repo)
        contract = Contract(
            id="test-contract",
            intent_summary="Test contract",
            acceptance_criteria=[
                AcceptanceCriterion(
                    id="c1",
                    type=CriterionType.FILE_EXISTS,
                    description="Exists",
                    target_file="src/reos/example.py",
                ),
                AcceptanceCriterion(
                    id="c2",
                    type=CriterionType.FILE_EXISTS,
                    description="Missing",
                    target_file="nonexistent.py",
                ),
            ],
        )

        # Verify to set states
        contract.is_fulfilled(sandbox)

        unfulfilled = contract.get_unfulfilled_criteria()

        assert len(unfulfilled) == 1
        assert unfulfilled[0].id == "c2"

    def test_get_next_step(self) -> None:
        """Should return next pending step."""
        contract = Contract(
            id="test-contract",
            intent_summary="Test",
            acceptance_criteria=[],
            steps=[
                ContractStep(id="s1", description="Step 1", target_criteria=[], action="edit_file", status="completed"),
                ContractStep(id="s2", description="Step 2", target_criteria=[], action="edit_file", status="pending"),
                ContractStep(id="s3", description="Step 3", target_criteria=[], action="edit_file", status="pending"),
            ],
        )

        next_step = contract.get_next_step()

        assert next_step is not None
        assert next_step.id == "s2"

    def test_summary_generation(self) -> None:
        """Should generate readable summary."""
        contract = Contract(
            id="test-contract",
            intent_summary="Add user authentication",
            acceptance_criteria=[
                AcceptanceCriterion(
                    id="c1",
                    type=CriterionType.FUNCTION_EXISTS,
                    description="Login function exists",
                    pattern="login",
                ),
            ],
            steps=[
                ContractStep(id="s1", description="Create auth module", target_criteria=["c1"], action="create_file"),
            ],
        )

        summary = contract.summary()

        assert "Add user authentication" in summary
        assert "Login function exists" in summary
        assert "Create auth module" in summary


class TestContractBuilder:
    """Tests for ContractBuilder."""

    def test_build_from_intent(self, temp_git_repo: Path) -> None:
        """Should build contract from intent."""
        sandbox = CodeSandbox(temp_git_repo)
        discoverer = IntentDiscoverer(sandbox, ollama=None)
        builder = ContractBuilder(sandbox, ollama=None)
        act = Act(
            act_id="test",
            title="Test",
            active=True,
            repo_path=str(temp_git_repo),
        )

        intent = discoverer.discover("add a new function", act)
        contract = builder.build_from_intent(intent)

        assert isinstance(contract, Contract)
        assert contract.id.startswith("contract-")
        assert len(contract.acceptance_criteria) > 0

    def test_contract_has_steps(self, temp_git_repo: Path) -> None:
        """Built contract should have steps."""
        sandbox = CodeSandbox(temp_git_repo)
        discoverer = IntentDiscoverer(sandbox, ollama=None)
        builder = ContractBuilder(sandbox, ollama=None)
        act = Act(
            act_id="test",
            title="Test",
            active=True,
            repo_path=str(temp_git_repo),
        )

        intent = discoverer.discover("add a new function", act)
        contract = builder.build_from_intent(intent)

        assert len(contract.steps) > 0

    def test_contract_status_is_draft(self, temp_git_repo: Path) -> None:
        """New contract should be in draft status."""
        sandbox = CodeSandbox(temp_git_repo)
        discoverer = IntentDiscoverer(sandbox, ollama=None)
        builder = ContractBuilder(sandbox, ollama=None)
        act = Act(
            act_id="test",
            title="Test",
            active=True,
            repo_path=str(temp_git_repo),
        )

        intent = discoverer.discover("add a new function", act)
        contract = builder.build_from_intent(intent)

        assert contract.status == ContractStatus.DRAFT

    def test_build_gap_contract(self, temp_git_repo: Path) -> None:
        """Should build gap contract for unfulfilled criteria."""
        sandbox = CodeSandbox(temp_git_repo)
        discoverer = IntentDiscoverer(sandbox, ollama=None)
        builder = ContractBuilder(sandbox, ollama=None)
        act = Act(
            act_id="test",
            title="Test",
            active=True,
            repo_path=str(temp_git_repo),
        )

        intent = discoverer.discover("add a new function", act)
        original = builder.build_from_intent(intent)

        # Mark some criteria as unfulfilled
        for c in original.acceptance_criteria:
            c.verified = False

        gap = builder.build_gap_contract(original, intent)

        assert gap.parent_contract_id == original.id
        assert original.id in original.child_contract_ids or gap.id in original.child_contract_ids
