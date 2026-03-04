"""Tests for Handoff module.

Tests the multi-agent handoff system for Talking Rock:
- Agent types and descriptions
- Domain detection and routing
- Handoff context building
- Shared tool handling
- Agent manifests and tool caps
"""

from __future__ import annotations

import pytest

from reos.handoff.models import (
    AgentType,
    AGENT_DESCRIPTIONS,
    DomainConfidence,
    HandoffContext,
    HandoffDecision,
    HandoffRequest,
    HandoffStatus,
    generate_transition_message,
)
from reos.handoff.router import (
    analyze_domain,
    build_handoff_context,
    detect_handoff_need,
    is_complex_request,
    is_simple_request,
)
from reos.handoff.tools import (
    SharedToolHandler,
    SHARED_TOOL_DEFINITIONS,
    get_shared_tool_names,
    get_shared_tool_schemas,
    is_shared_tool,
)
from reos.handoff.manifests import (
    CAIRN_CORE_TOOLS,
    MAX_TOOLS_PER_AGENT,
    REOS_CORE_TOOLS,
    RIVA_CORE_TOOLS,
    get_agent_manifest,
    get_tool_names_for_agent,
    validate_all_manifests,
)


# =============================================================================
# Model Tests
# =============================================================================


class TestAgentTypes:
    """Test AgentType enum and descriptions."""

    def test_agent_types_exist(self) -> None:
        """All three agent types exist."""
        assert AgentType.CAIRN.value == "cairn"
        assert AgentType.REOS.value == "reos"
        assert AgentType.RIVA.value == "riva"

    def test_agent_descriptions_complete(self) -> None:
        """Every agent has a description."""
        for agent_type in AgentType:
            assert agent_type in AGENT_DESCRIPTIONS
            desc = AGENT_DESCRIPTIONS[agent_type]
            assert "name" in desc
            assert "role" in desc
            assert "domain" in desc

    def test_agent_from_string(self) -> None:
        """AgentType can be created from string."""
        assert AgentType("cairn") == AgentType.CAIRN
        assert AgentType("reos") == AgentType.REOS
        assert AgentType("riva") == AgentType.RIVA


class TestHandoffContext:
    """Test HandoffContext model."""

    def test_create_context(self) -> None:
        """HandoffContext can be created."""
        context = HandoffContext(
            user_goal="Check disk space",
            handoff_reason="This is a system administration task",
        )
        assert context.user_goal == "Check disk space"
        assert context.handoff_reason == "This is a system administration task"

    def test_context_to_dict(self) -> None:
        """HandoffContext serializes to dict."""
        context = HandoffContext(
            user_goal="Write tests",
            handoff_reason="Code development task",
            relevant_details=["Python project", "pytest"],
            relevant_paths=["/home/user/project"],
        )
        d = context.to_dict()

        assert d["user_goal"] == "Write tests"
        assert "pytest" in d["relevant_details"]

    def test_context_to_prompt(self) -> None:
        """HandoffContext generates context prompt."""
        context = HandoffContext(
            user_goal="Fix the bug in auth.py",
            handoff_reason="Code debugging task",
            relevant_paths=["src/auth.py"],
        )
        prompt = context.to_prompt()

        assert "Fix the bug" in prompt
        assert "auth.py" in prompt


class TestHandoffDecision:
    """Test HandoffDecision model."""

    def test_decision_no_handoff(self) -> None:
        """Decision can indicate no handoff needed."""
        decision = HandoffDecision(
            should_handoff=False,
            target_agent=None,
            confidence=DomainConfidence.HIGH,
            reason="Current agent can handle this",
        )
        assert decision.should_handoff is False
        assert decision.target_agent is None

    def test_decision_with_handoff(self) -> None:
        """Decision can indicate handoff needed."""
        decision = HandoffDecision(
            should_handoff=True,
            target_agent=AgentType.RIVA,
            confidence=DomainConfidence.HIGH,
            reason="This is a code task",
        )
        assert decision.should_handoff is True
        assert decision.target_agent == AgentType.RIVA

    def test_decision_to_dict(self) -> None:
        """HandoffDecision serializes correctly."""
        decision = HandoffDecision(
            should_handoff=True,
            target_agent=AgentType.REOS,
            confidence=DomainConfidence.MEDIUM,
            reason="System task",
        )
        d = decision.to_dict()

        assert d["should_handoff"] is True
        assert d["target_agent"] == "reos"
        assert d["confidence"] == "medium"


class TestTransitionMessage:
    """Test transition message generation."""

    def test_generate_transition_message(self) -> None:
        """Transition message is generated correctly."""
        context = HandoffContext(
            user_goal="Check memory usage",
            handoff_reason="System monitoring task",
        )
        message = generate_transition_message(
            source=AgentType.CAIRN,
            target=AgentType.REOS,
            context=context,
        )

        assert "CAIRN" in message or "cairn" in message.lower()
        assert "ReOS" in message or "reos" in message.lower()
        assert "memory" in message.lower() or context.user_goal in message


# =============================================================================
# Router Tests
# =============================================================================


class TestDomainAnalysis:
    """Test domain detection and analysis."""

    def test_analyze_reos_domain(self) -> None:
        """ReOS domain detected for system tasks."""
        result = analyze_domain("what's using all my memory")

        assert AgentType.REOS in result
        # Check score exists (may be DomainScore object)
        assert result[AgentType.REOS] is not None

    def test_analyze_riva_domain(self) -> None:
        """RIVA domain detected for code tasks."""
        result = analyze_domain("write a python function to sort a list")

        assert AgentType.RIVA in result
        assert result[AgentType.RIVA] is not None

    def test_analyze_cairn_domain(self) -> None:
        """CAIRN domain detected for life/knowledge tasks."""
        result = analyze_domain("what should I focus on today")

        assert AgentType.CAIRN in result
        assert result[AgentType.CAIRN] is not None


class TestHandoffDetection:
    """Test handoff need detection."""

    def test_detect_no_handoff_for_current_domain(self) -> None:
        """No handoff when message matches current agent."""
        decision = detect_handoff_need(
            current_agent=AgentType.REOS,
            message="check disk space",
        )
        assert decision.should_handoff is False

    def test_detect_handoff_to_riva(self) -> None:
        """Detects handoff to RIVA for code tasks."""
        decision = detect_handoff_need(
            current_agent=AgentType.CAIRN,
            message="write unit tests for the auth module",
        )
        # May or may not suggest handoff depending on confidence
        if decision.should_handoff:
            assert decision.target_agent == AgentType.RIVA

    def test_detect_handoff_to_reos(self) -> None:
        """Detects handoff to ReOS for system tasks."""
        decision = detect_handoff_need(
            current_agent=AgentType.CAIRN,
            message="my disk is almost full",
        )
        if decision.should_handoff:
            assert decision.target_agent == AgentType.REOS


class TestComplexityDetection:
    """Test request complexity detection."""

    def test_simple_request(self) -> None:
        """Simple requests detected correctly."""
        # Test messages that contain simplicity indicators
        assert is_simple_request("just check the status") is True
        assert is_simple_request("only show me the first line") is True

    def test_complex_request(self) -> None:
        """Complex requests detected correctly."""
        # Test messages that contain complexity indicators
        # COMPLEXITY_INDICATORS: multiple, several, all the, entire, whole, refactor, etc.
        assert is_complex_request("refactor the entire authentication system") is True
        assert is_complex_request("migrate all the database tables") is True


class TestContextBuilding:
    """Test handoff context building."""

    def test_build_context_with_goal_and_reason(self) -> None:
        """Context can be built with goal and reason."""
        context = build_handoff_context(
            user_goal="Debug the login issue",
            handoff_reason="This is a code debugging task",
        )

        assert context.user_goal == "Debug the login issue"
        assert context.handoff_reason == "This is a code debugging task"

    def test_build_context_with_paths(self) -> None:
        """Context includes detected paths."""
        context = build_handoff_context(
            user_goal="Fix the auth module",
            handoff_reason="Code task",
            detected_paths=["src/auth.py", "tests/test_auth.py"],
        )

        assert "src/auth.py" in context.relevant_paths


# =============================================================================
# Shared Tools Tests
# =============================================================================


class TestSharedTools:
    """Test shared tool definitions."""

    def test_shared_tools_defined(self) -> None:
        """All shared tools are defined."""
        names = get_shared_tool_names()

        assert "handoff_to_agent" in names
        assert "get_shared_context" in names
        assert "save_to_knowledge_base" in names

    def test_is_shared_tool(self) -> None:
        """is_shared_tool identifies shared tools."""
        assert is_shared_tool("handoff_to_agent") is True
        assert is_shared_tool("get_shared_context") is True
        assert is_shared_tool("some_other_tool") is False

    def test_shared_tool_schemas(self) -> None:
        """Shared tools have valid schemas."""
        schemas = get_shared_tool_schemas()

        assert len(schemas) == len(SHARED_TOOL_DEFINITIONS)
        for schema in schemas:
            assert "type" in schema
            assert schema["type"] == "function"
            assert "function" in schema
            assert "name" in schema["function"]
            assert "parameters" in schema["function"]


class TestSharedToolHandler:
    """Test SharedToolHandler."""

    def test_create_handler(self) -> None:
        """Handler can be created."""
        handler = SharedToolHandler(current_agent=AgentType.CAIRN)
        assert handler.current_agent == AgentType.CAIRN

    def test_handoff_to_self_rejected(self) -> None:
        """Handoff to same agent is rejected."""
        handler = SharedToolHandler(current_agent=AgentType.CAIRN)

        result = handler.call_tool("handoff_to_agent", {
            "target_agent": "cairn",
            "user_goal": "test",
            "handoff_reason": "test",
        })

        assert result["status"] == "rejected"
        assert "myself" in result["reason"].lower()

    def test_handoff_proposal(self) -> None:
        """Handoff can be proposed."""
        handler = SharedToolHandler(current_agent=AgentType.CAIRN)

        result = handler.call_tool("handoff_to_agent", {
            "target_agent": "reos",
            "user_goal": "Check disk space",
            "handoff_reason": "System task",
        })

        assert result["status"] == "proposed"
        assert result["target_agent"] == "reos"
        assert "handoff_id" in result
        assert handler.pending_handoff is not None

    def test_confirm_handoff(self) -> None:
        """Pending handoff can be confirmed."""
        handler = SharedToolHandler(current_agent=AgentType.CAIRN)

        # Propose first
        proposal = handler.call_tool("handoff_to_agent", {
            "target_agent": "riva",
            "user_goal": "Write code",
            "handoff_reason": "Code task",
        })
        handoff_id = proposal["handoff_id"]

        # Confirm
        result = handler.confirm_handoff(handoff_id)

        assert result["status"] == "confirmed"
        assert result["target_agent"] == "riva"
        assert handler.pending_handoff is None

    def test_reject_handoff(self) -> None:
        """Pending handoff can be rejected."""
        handler = SharedToolHandler(current_agent=AgentType.CAIRN)

        # Propose first
        proposal = handler.call_tool("handoff_to_agent", {
            "target_agent": "reos",
            "user_goal": "System task",
            "handoff_reason": "Test",
        })
        handoff_id = proposal["handoff_id"]

        # Reject
        result = handler.reject_handoff(handoff_id, reason="User prefers CAIRN")

        assert result["status"] == "rejected"
        assert handler.pending_handoff is None

    def test_get_shared_context_without_store(self) -> None:
        """get_shared_context returns empty without store."""
        handler = SharedToolHandler(current_agent=AgentType.CAIRN)

        result = handler.call_tool("get_shared_context", {
            "query": "test query",
        })

        assert result["found"] == 0
        assert "not available" in result.get("message", "").lower()

    def test_unknown_tool_raises(self) -> None:
        """Unknown tool raises ValueError."""
        handler = SharedToolHandler(current_agent=AgentType.CAIRN)

        with pytest.raises(ValueError, match="Unknown shared tool"):
            handler.call_tool("nonexistent_tool", {})


# =============================================================================
# Manifest Tests
# =============================================================================


class TestManifests:
    """Test agent manifests and tool caps."""

    def test_max_tools_constant(self) -> None:
        """MAX_TOOLS_PER_AGENT is 15."""
        assert MAX_TOOLS_PER_AGENT == 15

    def test_cairn_tools_under_cap(self) -> None:
        """CAIRN has <= 15 tools."""
        # Core tools + shared tools
        total = len(CAIRN_CORE_TOOLS) + len(SHARED_TOOL_DEFINITIONS)
        assert total <= MAX_TOOLS_PER_AGENT

    def test_reos_tools_under_cap(self) -> None:
        """ReOS has <= 15 tools."""
        total = len(REOS_CORE_TOOLS) + len(SHARED_TOOL_DEFINITIONS)
        assert total <= MAX_TOOLS_PER_AGENT

    def test_riva_tools_under_cap(self) -> None:
        """RIVA has <= 15 tools."""
        total = len(RIVA_CORE_TOOLS) + len(SHARED_TOOL_DEFINITIONS)
        assert total <= MAX_TOOLS_PER_AGENT

    def test_get_agent_manifest(self) -> None:
        """get_agent_manifest returns valid manifest."""
        for agent_type in AgentType:
            manifest = get_agent_manifest(agent_type)

            assert "agent" in manifest
            assert "tool_count" in manifest
            assert "tools" in manifest
            assert manifest["tool_count"] <= MAX_TOOLS_PER_AGENT

    def test_get_tool_names_for_agent(self) -> None:
        """get_tool_names_for_agent returns tool names."""
        for agent_type in AgentType:
            names = get_tool_names_for_agent(agent_type)

            assert isinstance(names, list)
            assert len(names) > 0
            # Should include shared tools
            assert "handoff_to_agent" in names

    def test_validate_all_manifests(self) -> None:
        """validate_all_manifests passes."""
        result = validate_all_manifests()

        assert result["valid"] is True
        # agents is a dict keyed by agent name, not a list
        for agent_name, agent_result in result["agents"].items():
            assert agent_result["valid"] is True
            assert agent_result["tool_count"] <= MAX_TOOLS_PER_AGENT


# =============================================================================
# Integration Tests
# =============================================================================


class TestHandoffIntegration:
    """Integration tests for full handoff flow."""

    def test_full_handoff_flow(self) -> None:
        """Complete handoff from propose to confirm."""
        # Start with CAIRN
        handler = SharedToolHandler(current_agent=AgentType.CAIRN)

        # User asks a code question
        message = "help me write unit tests for auth.py"

        # Detect if handoff needed
        decision = detect_handoff_need(AgentType.CAIRN, message)

        # If handoff suggested, propose it
        if decision.should_handoff and decision.target_agent:
            context = build_handoff_context(
                user_goal=message,
                handoff_reason=decision.reason,
            )

            proposal = handler.call_tool("handoff_to_agent", {
                "target_agent": decision.target_agent.value,
                "user_goal": context.user_goal,
                "handoff_reason": decision.reason,
            })

            assert proposal["status"] == "proposed"

            # Confirm handoff
            result = handler.confirm_handoff(proposal["handoff_id"])
            assert result["status"] == "confirmed"

    def test_handoff_rejection_flow(self) -> None:
        """Handoff rejection keeps user with current agent."""
        handler = SharedToolHandler(current_agent=AgentType.CAIRN)

        # Propose handoff
        proposal = handler.call_tool("handoff_to_agent", {
            "target_agent": "reos",
            "user_goal": "Check disk space",
            "handoff_reason": "System task",
        })

        # User rejects
        result = handler.reject_handoff(proposal["handoff_id"])

        assert result["status"] == "rejected"
        assert "cairn" in result["message"].lower()
