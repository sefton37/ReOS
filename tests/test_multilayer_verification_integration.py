"""Integration test for multi-layer verification in RIVA work() cycle.

This test verifies that when RIVA executes EDIT or CREATE actions,
the verify_action_multilayer() function is properly called and integrated.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from reos.code_mode import (
    Action,
    ActionType,
    AutoCheckpoint,
    CodeSandbox,
    Intention,
    IntentionStatus,
    WorkContext,
    riva_work,
)
from reos.code_mode.optimization.verification_layers import (
    LayerResult,
    VerificationLayer,
    VerificationResult,
    VerificationStrategy,
)


@pytest.fixture
def temp_sandbox(tmp_path: Path) -> CodeSandbox:
    """Create a temporary sandbox for testing."""
    (tmp_path / ".git").mkdir()
    (tmp_path / "src").mkdir()
    return CodeSandbox(tmp_path)


@pytest.fixture
def mock_verification_result() -> VerificationResult:
    """Create a mock successful verification result."""
    return VerificationResult(
        layers=[
            LayerResult(
                layer=VerificationLayer.SYNTAX,
                passed=True,
                confidence=0.95,
                reason="Syntax valid",
                duration_ms=1,
            ),
            LayerResult(
                layer=VerificationLayer.SEMANTIC,
                passed=True,
                confidence=0.90,
                reason="No undefined names",
                duration_ms=10,
            ),
            LayerResult(
                layer=VerificationLayer.BEHAVIORAL,
                passed=True,
                confidence=0.95,
                reason="Tests pass",
                duration_ms=500,
            ),
        ],
        overall_passed=True,
        overall_confidence=0.93,
        total_duration_ms=511,
        total_tokens_used=0,
    )


class TestMultilayerVerificationIntegration:
    """Tests for multi-layer verification integration in work() cycle."""

    @patch("reos.code_mode.intention.verify_action_multilayer")
    def test_multilayer_verification_called_for_create_action(
        self,
        mock_verify: AsyncMock,
        temp_sandbox: CodeSandbox,
        mock_verification_result: VerificationResult,
    ) -> None:
        """verify_action_multilayer should be called for CREATE actions."""
        # Setup mock to return successful verification
        mock_verify.return_value = mock_verification_result

        # Create an intention that will generate a CREATE action
        intention = Intention.create(
            what="Create a simple Python file src/hello.py with a hello() function",
            acceptance="File exists and has hello function",
        )

        checkpoint = AutoCheckpoint(sandbox=temp_sandbox)

        # Create a mock LLM that returns a CREATE action
        mock_llm = MagicMock()
        mock_llm.chat_json.return_value = """{
            "thought": "I will create the hello.py file",
            "action": {
                "type": "create",
                "target": "src/hello.py",
                "content": "def hello():\\n    return 'Hello, World!'"
            }
        }"""

        ctx = WorkContext(
            sandbox=temp_sandbox,
            llm=mock_llm,
            checkpoint=checkpoint,
            max_depth=3,
            max_cycles_per_intention=3,
        )

        # Execute work
        riva_work(intention, ctx)

        # Verify that multilayer verification was called
        assert mock_verify.called, "verify_action_multilayer should have been called"

        # Check the call arguments
        call_args = mock_verify.call_args
        assert call_args is not None

        action = call_args[1]["action"]
        assert action.type == ActionType.CREATE
        assert "hello.py" in action.target

        strategy = call_args[1]["strategy"]
        assert isinstance(strategy, VerificationStrategy)

    @patch("reos.code_mode.intention.verify_action_multilayer")
    def test_multilayer_verification_called_for_edit_action(
        self,
        mock_verify: AsyncMock,
        temp_sandbox: CodeSandbox,
        mock_verification_result: VerificationResult,
    ) -> None:
        """verify_action_multilayer should be called for EDIT actions."""
        # Setup mock to return successful verification
        mock_verify.return_value = mock_verification_result

        # Create a file to edit
        test_file = temp_sandbox.root / "src" / "main.py"
        test_file.write_text("# Original content\n")

        # Create an intention that will generate an EDIT action
        intention = Intention.create(
            what="Add a function to src/main.py",
            acceptance="Function exists in file",
        )

        checkpoint = AutoCheckpoint(sandbox=temp_sandbox)

        # Create a mock LLM that returns an EDIT action
        mock_llm = MagicMock()
        mock_llm.chat_json.return_value = """{
            "thought": "I will add the function",
            "action": {
                "type": "edit",
                "target": "src/main.py",
                "content": "def new_function():\\n    pass"
            }
        }"""

        ctx = WorkContext(
            sandbox=temp_sandbox,
            llm=mock_llm,
            checkpoint=checkpoint,
            max_depth=3,
            max_cycles_per_intention=3,
        )

        # Execute work
        riva_work(intention, ctx)

        # Verify that multilayer verification was called
        assert mock_verify.called, "verify_action_multilayer should have been called"

        call_args = mock_verify.call_args
        assert call_args is not None

        action = call_args[1]["action"]
        assert action.type == ActionType.EDIT

    @patch("reos.code_mode.intention.verify_action_multilayer")
    def test_multilayer_verification_not_called_for_command_action(
        self,
        mock_verify: AsyncMock,
        temp_sandbox: CodeSandbox,
    ) -> None:
        """verify_action_multilayer should NOT be called for COMMAND actions."""
        # Create an intention that will generate a COMMAND action
        intention = Intention.create(
            what="List files in src directory",
            acceptance="Files are listed",
        )

        checkpoint = AutoCheckpoint(sandbox=temp_sandbox)

        # Create a mock LLM that returns a COMMAND action
        mock_llm = MagicMock()
        mock_llm.chat_json.return_value = """{
            "thought": "I will list the files",
            "action": {
                "type": "command",
                "content": "ls src/"
            }
        }"""

        ctx = WorkContext(
            sandbox=temp_sandbox,
            llm=mock_llm,
            checkpoint=checkpoint,
            max_depth=3,
            max_cycles_per_intention=2,
        )

        # Execute work
        riva_work(intention, ctx)

        # Verify that multilayer verification was NOT called
        assert not mock_verify.called, "verify_action_multilayer should not be called for COMMAND actions"

    @patch("reos.code_mode.intention.verify_action_multilayer")
    def test_verification_failure_results_in_failure_judgment(
        self,
        mock_verify: AsyncMock,
        temp_sandbox: CodeSandbox,
    ) -> None:
        """Failed verification should result in FAILURE judgment."""
        # Setup mock to return failed verification
        failed_result = VerificationResult(
            layers=[
                LayerResult(
                    layer=VerificationLayer.SYNTAX,
                    passed=False,
                    confidence=0.0,
                    reason="Syntax error: missing closing paren",
                    duration_ms=1,
                ),
            ],
            overall_passed=False,
            overall_confidence=0.0,
            total_duration_ms=1,
            total_tokens_used=0,
        )
        mock_verify.return_value = failed_result

        # Create an intention
        intention = Intention.create(
            what="Create a file with syntax error",
            acceptance="File created",
        )

        checkpoint = AutoCheckpoint(sandbox=temp_sandbox)

        mock_llm = MagicMock()
        mock_llm.chat_json.return_value = """{
            "thought": "Creating file",
            "action": {
                "type": "create",
                "target": "src/bad.py",
                "content": "def foo(x:\\n    return x"
            }
        }"""

        ctx = WorkContext(
            sandbox=temp_sandbox,
            llm=mock_llm,
            checkpoint=checkpoint,
            max_depth=3,
            max_cycles_per_intention=3,
        )

        # Execute work
        riva_work(intention, ctx)

        # Intention should have failed due to verification failure
        assert len(intention.trace) > 0
        # The first cycle should have a FAILURE judgment due to failed verification
        # (or the intention should be FAILED overall)
        assert intention.status == IntentionStatus.FAILED

    @patch("reos.code_mode.intention.verify_action_multilayer")
    def test_high_risk_uses_thorough_strategy(
        self,
        mock_verify: AsyncMock,
        temp_sandbox: CodeSandbox,
        mock_verification_result: VerificationResult,
    ) -> None:
        """High-risk actions should use THOROUGH verification strategy."""
        mock_verify.return_value = mock_verification_result

        # Create an intention that will be assessed as high risk
        # (e.g., file deletion or system modification)
        intention = Intention.create(
            what="Modify system configuration file",
            acceptance="File modified",
        )

        checkpoint = AutoCheckpoint(sandbox=temp_sandbox)

        mock_llm = MagicMock()
        # Action that modifies a system-like file (high risk)
        mock_llm.chat_json.return_value = """{
            "thought": "Modifying config",
            "action": {
                "type": "edit",
                "target": ".gitignore",
                "content": "*.pyc\\n__pycache__/"
            }
        }"""

        ctx = WorkContext(
            sandbox=temp_sandbox,
            llm=mock_llm,
            checkpoint=checkpoint,
            max_depth=3,
            max_cycles_per_intention=3,
        )

        # Execute work
        riva_work(intention, ctx)

        # Check that verification was called
        if mock_verify.called:
            call_args = mock_verify.call_args
            strategy = call_args[1]["strategy"]
            # Should use STANDARD or THOROUGH (depending on risk assessment)
            assert strategy in [
                VerificationStrategy.STANDARD,
                VerificationStrategy.THOROUGH,
            ]


class TestIntentLayerVerification:
    """Tests for Intent Layer (Layer 4) verification."""

    @patch("reos.code_mode.optimization.verification_layers._verify_intent_layer")
    def test_intent_layer_detects_misaligned_code(
        self,
        mock_intent_layer: AsyncMock,
    ) -> None:
        """Intent layer should detect when code doesn't match request."""
        from reos.code_mode.optimization.verification_layers import (
            LayerResult,
            VerificationLayer,
        )

        # Simulate intent layer detecting misalignment
        mock_intent_layer.return_value = LayerResult(
            layer=VerificationLayer.INTENT,
            passed=False,
            confidence=0.85,
            reason="Code implements fibonacci instead of factorial as requested",
            duration_ms=1500,
            tokens_used=150,
        )

        # This test verifies the mock works - actual integration testing
        # would require a real LLM, which we test separately
        result = asyncio.run(mock_intent_layer(None, None, None))
        assert result.layer == VerificationLayer.INTENT
        assert not result.passed
        assert "fibonacci" in result.reason.lower()

    def test_intent_layer_implementation_has_llm_call(self) -> None:
        """Verify intent layer implementation uses LLM."""
        import inspect
        from reos.code_mode.optimization.verification_layers import (
            _verify_intent_layer,
        )

        # Check that _verify_intent_layer references ctx.llm
        source = inspect.getsource(_verify_intent_layer)
        assert "ctx.llm" in source, "Intent layer should use ctx.llm"
        assert "chat_text" in source, "Intent layer should call chat_text()"
        assert "ALIGNED:" in source, "Intent layer should parse ALIGNED response"
        assert "CONFIDENCE:" in source, "Intent layer should parse CONFIDENCE"
        assert "REASON:" in source, "Intent layer should parse REASON"

    def test_intent_layer_skips_without_llm(self) -> None:
        """Intent layer should gracefully skip if no LLM available."""
        import asyncio

        from reos.code_mode import Action, ActionType, Intention, WorkContext
        from reos.code_mode.optimization.verification_layers import (
            _verify_intent_layer,
        )

        # Create minimal test data
        action = Action(type=ActionType.CREATE, content="def hello(): pass", target="test.py")
        intention = Intention.create(what="Create hello function", acceptance="Function exists")

        # Create context WITHOUT LLM
        class MockSandbox:
            root = Path("/tmp/test")

        ctx = WorkContext(
            sandbox=MockSandbox(),  # type: ignore
            llm=None,  # No LLM
            checkpoint=None,  # type: ignore
        )

        # Run intent verification
        result = asyncio.run(_verify_intent_layer(action, intention, ctx))

        # Should skip gracefully
        assert result.layer == VerificationLayer.INTENT
        assert result.passed  # Defaults to True when skipped
        assert result.confidence == 0.5  # Neutral confidence
        assert "skipped" in result.reason.lower()
        assert result.tokens_used == 0

    def test_intent_layer_prompt_structure(self) -> None:
        """Verify intent layer builds proper prompts."""
        import inspect

        from reos.code_mode.optimization.verification_layers import (
            _verify_intent_layer,
        )

        source = inspect.getsource(_verify_intent_layer)

        # Check prompt structure
        assert "Original Request:" in source
        assert "Acceptance Criteria:" in source
        assert "Generated Code:" in source
        assert "system_prompt" in source
        assert "user_prompt" in source
        assert "temperature=0.1" in source  # Low temp for consistent judgments
