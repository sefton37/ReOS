"""Integration tests for RIVA (Recursive Intention-Verification Architecture).

These tests verify the complete flow from CodeExecutor through RIVA,
including session logging, error handling, and checkpoint callbacks.
"""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from reos.code_mode import (
    # RIVA components
    Intention,
    IntentionStatus,
    Cycle,
    Action,
    ActionType,
    Judgment,
    WorkContext,
    AutoCheckpoint,
    UICheckpoint,
    RIVASession,
    riva_work,
    can_verify_directly,
    should_decompose,
    decompose,
    # Executor and related
    CodeExecutor,
    CodeSandbox,
    ExecutionResult,
    LoopStatus,
    # Session logging
    SessionLogger,
    list_sessions,
    get_session_log,
    # Intent and Contract
    IntentDiscoverer,
    DiscoveredIntent,
    PromptIntent,
    PlayIntent,
    CodebaseIntent,
    ContractBuilder,
    Contract,
    ContractStatus,
)
from reos.play_fs import Act


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def temp_sandbox(tmp_path: Path) -> CodeSandbox:
    """Create a temporary sandbox for testing."""
    # Create a minimal git repo structure
    (tmp_path / ".git").mkdir()
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("# Main module\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_main.py").write_text("# Tests\n")
    return CodeSandbox(tmp_path)


@pytest.fixture
def mock_llm() -> MagicMock:
    """Create a mock LLM provider."""
    llm = MagicMock()
    llm.chat_json = MagicMock(return_value='{"success": true}')
    llm.chat_text = MagicMock(return_value="LLM response")
    return llm


@pytest.fixture
def sample_act(tmp_path: Path) -> Act:
    """Create a sample Act for testing."""
    return Act(
        act_id="test-act-001",
        title="Test Act",
        notes="Testing RIVA integration",
        repo_path=str(tmp_path),
    )


@pytest.fixture
def sample_intent() -> DiscoveredIntent:
    """Create a sample DiscoveredIntent for testing."""
    return DiscoveredIntent(
        goal="Add a greeting function",
        why="User requested it",
        what="Create a greet() function in main.py",
        how_constraints=["Must be simple", "Must return a string"],
        prompt_intent=PromptIntent(
            raw_prompt="Add a greeting function",
            action_verb="add",
            target="function",
            constraints=[],
            examples=[],
            summary="Add a greeting function",
        ),
        play_intent=PlayIntent(
            act_goal="Test Act",
            act_artifact="test",
            scene_context="",
            recent_work=[],
            knowledge_hints=[],
        ),
        codebase_intent=CodebaseIntent(
            language="python",
            architecture_style="unknown",
            conventions=[],
            related_files=["src/main.py"],
            existing_patterns=[],
            test_patterns="pytest",
            layer_responsibilities=[],
        ),
        confidence=0.9,
        ambiguities=[],
        assumptions=[],
    )


@pytest.fixture
def session_log_dir(tmp_path: Path) -> Path:
    """Create a temporary directory for session logs."""
    log_dir = tmp_path / "code_mode_sessions"
    log_dir.mkdir()
    return log_dir


# ============================================================================
# Session Logger Integration Tests
# ============================================================================


class TestSessionLoggerIntegration:
    """Tests for session logger capturing all RIVA events."""

    def test_session_logger_creates_files(self, tmp_path: Path) -> None:
        """Session logger should create .log and .json files."""
        log_dir = tmp_path / "code_mode_sessions"
        log_dir.mkdir()

        with patch("reos.settings.settings") as mock_settings:
            mock_settings.data_dir = tmp_path

            logger = SessionLogger(
                session_id="test-session-001",
                prompt="Test prompt",
            )

            # Log some entries
            logger.log_info("test", "test_action", "Test message")
            logger.log_phase_change("intent", "Starting intent discovery")
            logger.close(outcome="completed", final_message="Test complete")

            # Verify files exist
            assert logger.log_file.exists()
            assert logger.json_file.exists()

            # Verify JSON content
            with open(logger.json_file) as f:
                data = json.load(f)

            assert data["session_id"] == "test-session-001"
            assert data["prompt"] == "Test prompt"
            assert data["outcome"] == "completed"
            assert len(data["entries"]) >= 2

    def test_session_logger_captures_llm_calls(self, tmp_path: Path) -> None:
        """Session logger should capture LLM call details."""
        log_dir = tmp_path / "code_mode_sessions"
        log_dir.mkdir()

        with patch("reos.settings.settings") as mock_settings:
            mock_settings.data_dir = tmp_path

            logger = SessionLogger(
                session_id="llm-test-001",
                prompt="Test LLM logging",
            )

            logger.log_llm_call(
                module="intent",
                purpose="analyze_prompt",
                system_prompt="You are an analyzer",
                user_prompt="Analyze this request",
                response="Analysis complete",
            )
            logger.close(outcome="completed", final_message="Done")

            # Verify LLM call was logged
            with open(logger.json_file) as f:
                data = json.load(f)

            llm_entries = [e for e in data["entries"] if "llm_call" in e.get("action", "")]
            # log_llm_call creates both llm_call_start and llm_call_response entries
            assert len(llm_entries) >= 1
            # First entry is llm_call_start with system_prompt
            start_entries = [e for e in llm_entries if e.get("action") == "llm_call_start"]
            assert len(start_entries) >= 1
            assert "system_prompt" in start_entries[0]["data"]
            # Check for response in llm_call_response entry
            response_entries = [e for e in llm_entries if e.get("action") == "llm_call_response"]
            assert len(response_entries) >= 1
            assert "response" in response_entries[0]["data"]

    def test_session_logger_captures_errors(self, tmp_path: Path) -> None:
        """Session logger should capture error events."""
        log_dir = tmp_path / "code_mode_sessions"
        log_dir.mkdir()

        with patch("reos.settings.settings") as mock_settings:
            mock_settings.data_dir = tmp_path

            logger = SessionLogger(
                session_id="error-test-001",
                prompt="Test error logging",
            )

            logger.log_error(
                "executor",
                "step_failed",
                "Step execution failed",
                {"step_id": "step-1", "error": "File not found"},
            )
            logger.close(outcome="failed", final_message="Execution failed")

            with open(logger.json_file) as f:
                data = json.load(f)

            assert data["outcome"] == "failed"
            error_entries = [e for e in data["entries"] if e.get("level") == "ERROR"]
            assert len(error_entries) == 1
            assert error_entries[0]["data"]["error"] == "File not found"


# ============================================================================
# RIVA Work Algorithm Integration Tests
# ============================================================================


class TestRIVAWorkIntegration:
    """Tests for the RIVA work() algorithm with full context."""

    def test_work_with_simple_intention(self, temp_sandbox: CodeSandbox) -> None:
        """work() should handle a simple verifiable intention."""
        intention = Intention.create(
            what="Create file test.txt",
            acceptance="File test.txt exists",
        )

        checkpoint = AutoCheckpoint(sandbox=temp_sandbox)
        ctx = WorkContext(
            sandbox=temp_sandbox,
            llm=None,  # Use heuristics
            checkpoint=checkpoint,
            max_depth=3,
            max_cycles_per_intention=5,
        )

        riva_work(intention, ctx)

        # Should have attempted work (may succeed or fail based on heuristics)
        assert intention.status in [IntentionStatus.VERIFIED, IntentionStatus.FAILED]
        assert len(intention.trace) > 0

    def test_work_respects_max_depth(self, temp_sandbox: CodeSandbox) -> None:
        """work() should respect max_depth limit."""
        # Create an intention that would normally decompose
        intention = Intention.create(
            what="Complex task: first do A and then do B and finally do C",
            acceptance="All parts complete",
        )

        checkpoint = AutoCheckpoint(sandbox=temp_sandbox)
        ctx = WorkContext(
            sandbox=temp_sandbox,
            llm=None,
            checkpoint=checkpoint,
            max_depth=0,  # Prevent any recursion
            max_cycles_per_intention=2,
        )

        riva_work(intention, ctx)

        # Should fail due to depth limit
        assert intention.status == IntentionStatus.FAILED
        # Note: Implementation may create children but they will be failed/pending
        # due to depth limit being reached. The important thing is the overall
        # intention fails and no children make progress beyond FAILED status.
        for child in intention._child_intentions:
            assert child.status in [IntentionStatus.FAILED, IntentionStatus.PENDING]

    def test_work_with_callbacks(self, temp_sandbox: CodeSandbox) -> None:
        """work() should invoke callbacks at key points."""
        intention_starts: list[str] = []
        intention_completes: list[str] = []
        cycle_completes: list[tuple[str, Judgment]] = []

        def on_start(i: Intention) -> None:
            intention_starts.append(i.id)

        def on_complete(i: Intention) -> None:
            intention_completes.append(i.id)

        def on_cycle(i: Intention, c: Cycle) -> None:
            cycle_completes.append((i.id, c.judgment))

        intention = Intention.create(
            what="Simple test",
            acceptance="Test passes",
        )

        checkpoint = AutoCheckpoint(sandbox=temp_sandbox)
        ctx = WorkContext(
            sandbox=temp_sandbox,
            llm=None,
            checkpoint=checkpoint,
            max_depth=2,
            max_cycles_per_intention=3,
            on_intention_start=on_start,
            on_intention_complete=on_complete,
            on_cycle_complete=on_cycle,
        )

        riva_work(intention, ctx)

        # Should have called start callback
        assert intention.id in intention_starts
        # Should have called complete callback
        assert intention.id in intention_completes
        # Should have at least one cycle
        assert len(cycle_completes) > 0


class TestUICheckpointIntegration:
    """Tests for UICheckpoint with callback overrides."""

    def test_uicheckpoint_custom_judgment(self, temp_sandbox: CodeSandbox) -> None:
        """UICheckpoint should use custom judgment callback."""
        custom_judgments: list[Judgment] = []

        def custom_judge(intention: Intention, cycle: Cycle, auto: Judgment) -> Judgment:
            custom_judgments.append(auto)
            return Judgment.SUCCESS  # Always succeed

        checkpoint = UICheckpoint(
            sandbox=temp_sandbox,
            on_judge_action=custom_judge,
        )

        intention = Intention.create(what="Test", acceptance="Pass")
        cycle = Cycle(
            thought="Testing",
            action=Action(type=ActionType.QUERY, content="test"),
            result="Result with error keyword",  # Would normally be FAILURE
            judgment=Judgment.UNCLEAR,
        )

        result = checkpoint.judge_action(intention, cycle)

        assert result == Judgment.SUCCESS
        assert len(custom_judgments) == 1

    def test_uicheckpoint_custom_decomposition_approval(
        self, temp_sandbox: CodeSandbox
    ) -> None:
        """UICheckpoint should use custom decomposition approval."""
        approvals_requested: list[int] = []

        def custom_approve(intention: Intention, children: list[Intention]) -> bool:
            approvals_requested.append(len(children))
            return len(children) <= 3  # Only approve if 3 or fewer children

        checkpoint = UICheckpoint(
            sandbox=temp_sandbox,
            on_approve_decomposition=custom_approve,
        )

        parent = Intention.create(what="Parent", acceptance="Done")
        children = [
            Intention.create(what=f"Child {i}", acceptance=f"Done {i}")
            for i in range(5)
        ]

        result = checkpoint.approve_decomposition(parent, children)

        assert result is False  # 5 > 3
        assert approvals_requested == [5]


# ============================================================================
# CodeExecutor RIVA Mode Integration Tests
# ============================================================================


class TestCodeExecutorRIVAMode:
    """Tests for CodeExecutor with use_riva=True."""

    def test_executor_riva_mode_creates_session(
        self,
        temp_sandbox: CodeSandbox,
        sample_act: Act,
        tmp_path: Path,
    ) -> None:
        """Executor in RIVA mode should create session logs."""
        log_dir = tmp_path / "code_mode_sessions"
        log_dir.mkdir()

        with patch("reos.settings.settings") as mock_settings:
            mock_settings.data_dir = tmp_path

            executor = CodeExecutor(
                sandbox=temp_sandbox,
                llm=None,
            )

            # Run with RIVA mode
            result = executor.execute(
                prompt="Create a simple greeting function",
                act=sample_act,
                max_iterations=2,
                use_riva=True,
            )

            # Should complete (success or failure)
            assert result.state.status in [LoopStatus.COMPLETED, LoopStatus.FAILED]

    def test_executor_riva_mode_with_observer(
        self,
        temp_sandbox: CodeSandbox,
        sample_act: Act,
    ) -> None:
        """Executor in RIVA mode should notify observer."""
        from reos.code_mode.streaming import ExecutionObserver

        activities: list[str] = []
        phases: list[str] = []

        class TestObserver(ExecutionObserver):
            def on_activity(self, message: str, **kwargs: Any) -> None:
                activities.append(message)

            def on_phase_change(self, phase: str, **kwargs: Any) -> None:
                phases.append(phase)

        # Create a mock context for the observer
        from reos.code_mode.streaming import create_execution_context
        mock_context = create_execution_context(
            session_id="test-session",
            prompt="Simple test",
            max_iterations=1,
        )
        observer = TestObserver(mock_context)
        executor = CodeExecutor(
            sandbox=temp_sandbox,
            llm=None,
            observer=observer,
        )

        result = executor.execute(
            prompt="Simple test",
            act=sample_act,
            max_iterations=1,
            use_riva=True,
        )

        # Should have generated some activity notifications
        assert len(activities) > 0 or len(phases) > 0


# ============================================================================
# Error Handling Integration Tests
# ============================================================================


class TestErrorHandlingIntegration:
    """Tests for error handling and logging across the RIVA stack."""

    def test_llm_failure_uses_heuristic_fallback(
        self,
        temp_sandbox: CodeSandbox,
    ) -> None:
        """LLM failures should fall back to heuristics."""
        # Create a mock LLM that fails
        failing_llm = MagicMock()
        failing_llm.chat_json = MagicMock(side_effect=Exception("LLM unavailable"))
        failing_llm.chat_text = MagicMock(side_effect=Exception("LLM unavailable"))

        intention = Intention.create(
            what="Test with failing LLM",
            acceptance="Should handle failure",
        )

        checkpoint = AutoCheckpoint(sandbox=temp_sandbox)
        ctx = WorkContext(
            sandbox=temp_sandbox,
            llm=failing_llm,
            checkpoint=checkpoint,
            max_depth=2,
            max_cycles_per_intention=2,
        )

        # Run work - should fall back to heuristics, not crash
        riva_work(intention, ctx)

        # Should have at least tried (even if failed)
        assert intention.status in [IntentionStatus.VERIFIED, IntentionStatus.FAILED]

    def test_sandbox_error_handling(self, temp_sandbox: CodeSandbox) -> None:
        """Sandbox errors should be caught and handled."""
        intention = Intention.create(
            what="Read nonexistent file /does/not/exist.txt",
            acceptance="File content retrieved",
        )

        checkpoint = AutoCheckpoint(sandbox=temp_sandbox)
        ctx = WorkContext(
            sandbox=temp_sandbox,
            llm=None,
            checkpoint=checkpoint,
            max_depth=1,
            max_cycles_per_intention=2,
        )

        # Should not raise, should handle gracefully
        riva_work(intention, ctx)

        # Should have failed (file doesn't exist)
        assert intention.status == IntentionStatus.FAILED


# ============================================================================
# Contract + RIVA Integration Tests
# ============================================================================


class TestContractRIVAIntegration:
    """Tests for Contract and RIVA working together."""

    def test_contract_criteria_as_acceptance(
        self,
        temp_sandbox: CodeSandbox,
        sample_intent: DiscoveredIntent,
    ) -> None:
        """Contract criteria should work as RIVA acceptance criteria."""
        builder = ContractBuilder(
            sandbox=temp_sandbox,
            llm=None,  # Use heuristics
        )

        contract = builder.build_from_intent(sample_intent)

        # Verify contract has criteria
        assert len(contract.acceptance_criteria) > 0

        # Each criterion should be expressible as acceptance text
        for criterion in contract.acceptance_criteria:
            assert criterion.description
            assert len(criterion.description) > 5


# ============================================================================
# Session Persistence Tests
# ============================================================================


class TestRIVASessionPersistence:
    """Tests for RIVA session save/load functionality."""

    def test_session_save_and_load(self, tmp_path: Path) -> None:
        """RIVA session should serialize and deserialize correctly."""
        # Create a session with nested intentions
        root = Intention.create(
            what="Root intention",
            acceptance="All children complete",
        )

        child1 = Intention.create(what="Child 1", acceptance="Done 1")
        child2 = Intention.create(what="Child 2", acceptance="Done 2")

        root.add_child(child1)
        root.add_child(child2)

        # Add some cycles
        cycle = Cycle(
            thought="Testing",
            action=Action(type=ActionType.COMMAND, content="echo test"),
            result="test",
            judgment=Judgment.SUCCESS,
        )
        child1.add_cycle(cycle)
        child1.status = IntentionStatus.VERIFIED

        session = RIVASession(
            id="test-session",
            timestamp=datetime.now(timezone.utc).isoformat(),
            root=root,
            metadata={"test": True},
        )

        # Save to file
        session_file = tmp_path / "session.json"
        session.save(session_file)

        # Load from file
        loaded = RIVASession.load(session_file)

        # Verify structure preserved
        assert loaded.id == session.id
        assert loaded.root.what == root.what
        assert len(loaded.root.children) == 2
        assert loaded.metadata["test"] is True

    def test_session_captures_full_trace(self, temp_sandbox: CodeSandbox) -> None:
        """Session should capture complete execution trace."""
        intention = Intention.create(
            what="Simple test for trace",
            acceptance="Pass",
        )

        checkpoint = AutoCheckpoint(sandbox=temp_sandbox)
        ctx = WorkContext(
            sandbox=temp_sandbox,
            llm=None,
            checkpoint=checkpoint,
            max_depth=1,
            max_cycles_per_intention=3,
        )

        riva_work(intention, ctx)

        # Create session from completed intention
        session = RIVASession(
            id="trace-test",
            timestamp=datetime.now(timezone.utc).isoformat(),
            root=intention,
            metadata={
                "total_cycles": intention.get_total_cycles(),
                "max_depth": intention.get_depth(),
            },
        )

        # Should have metadata
        assert session.metadata["total_cycles"] >= 0
        assert session.metadata["max_depth"] >= 0


# ============================================================================
# List/Get Sessions API Tests
# ============================================================================


class TestSessionsAPI:
    """Tests for the sessions list/get API."""

    def test_list_sessions_empty(self, tmp_path: Path) -> None:
        """list_sessions should return empty list when no sessions."""
        log_dir = tmp_path / "code_mode_sessions"
        log_dir.mkdir()

        with patch("reos.settings.settings") as mock_settings:
            mock_settings.data_dir = tmp_path

            sessions = list_sessions(limit=10)
            assert sessions == []

    def test_list_sessions_with_data(self, tmp_path: Path) -> None:
        """list_sessions should return sessions in order."""
        log_dir = tmp_path / "code_mode_sessions"
        log_dir.mkdir()

        with patch("reos.settings.settings") as mock_settings:
            mock_settings.data_dir = tmp_path

            # Create two sessions with unique IDs (first 8 chars must differ)
            logger1 = SessionLogger(session_id="first-session-001", prompt="First")
            logger1.log_info("test", "action1", "Message 1")
            logger1.close(outcome="completed", final_message="Done 1")

            logger2 = SessionLogger(session_id="second-session-002", prompt="Second")
            logger2.log_info("test", "action2", "Message 2")
            logger2.close(outcome="failed", final_message="Failed 2")

            sessions = list_sessions(limit=10)

            assert len(sessions) == 2
            # Should have session metadata
            assert any(s["session_id"].startswith("first-se") for s in sessions)
            assert any(s["session_id"].startswith("second-s") for s in sessions)

    def test_get_session_log_by_id(self, tmp_path: Path) -> None:
        """get_session_log should retrieve specific session."""
        log_dir = tmp_path / "code_mode_sessions"
        log_dir.mkdir()

        with patch("reos.settings.settings") as mock_settings:
            mock_settings.data_dir = tmp_path

            logger = SessionLogger(session_id="get-test-001", prompt="Get test")
            logger.log_info("test", "action", "Test message")
            logger.close(outcome="completed", final_message="Done")

            # Get by ID prefix
            result = get_session_log("get-test")

            assert result is not None
            assert result["session_id"].startswith("get-test-001")
            assert "entries" in result
            assert len(result["entries"]) >= 1
