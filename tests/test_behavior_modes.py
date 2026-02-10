"""Tests for cairn/behavior_modes.py — Behavior Mode Registry.

Tests that the registry correctly maps (destination, consumer, semantics, domain)
classifications to behavior modes, and that tool selectors / arg extractors work.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from reos.atomic_ops.models import (
    Classification,
    ConsumerType,
    DestinationType,
    ExecutionSemantics,
)
from reos.cairn.behavior_modes import (
    CALENDAR_QUERY_MODE,
    CONTACTS_QUERY_MODE,
    CONVERSATION_MODE,
    FEEDBACK_MODE,
    PERSONAL_QUERY_MODE,
    PLAY_MUTATION_MODE,
    PLAY_QUERY_MODE,
    SYSTEM_QUERY_MODE,
    TASKS_QUERY_MODE,
    UNDO_MODE,
    BehaviorModeContext,
    BehaviorModeRegistry,
    _play_tool_selector,
    _static_tool,
    create_default_registry,
)

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def registry() -> BehaviorModeRegistry:
    """Create a default behavior mode registry."""
    return create_default_registry()


def _make_classification(
    dest: str = "stream",
    consumer: str = "human",
    semantics: str = "interpret",
    domain: str | None = None,
    action_hint: str | None = None,
) -> Classification:
    """Helper to create Classification objects."""
    return Classification(
        destination=DestinationType(dest),
        consumer=ConsumerType(consumer),
        semantics=ExecutionSemantics(semantics),
        domain=domain,
        action_hint=action_hint,
    )


# =============================================================================
# Registry Lookup Tests
# =============================================================================


class TestRegistryLookup:
    """Test BehaviorModeRegistry.get_mode()."""

    def test_conversation_exact_match(self, registry: BehaviorModeRegistry) -> None:
        """Conversation domain returns CONVERSATION_MODE."""
        c = _make_classification(domain="conversation")
        mode = registry.get_mode(c)
        assert mode.name == "conversation"
        assert mode.needs_tool is False

    def test_calendar_read(self, registry: BehaviorModeRegistry) -> None:
        """Calendar read returns CALENDAR_QUERY_MODE."""
        c = _make_classification(semantics="read", domain="calendar")
        mode = registry.get_mode(c)
        assert mode.name == "calendar_query"
        assert mode.needs_tool is True

    def test_personal_interpret(self, registry: BehaviorModeRegistry) -> None:
        """Personal interpret returns PERSONAL_QUERY_MODE."""
        c = _make_classification(domain="personal")
        mode = registry.get_mode(c)
        assert mode.name == "personal_query"
        assert mode.needs_tool is False

    def test_feedback_mode(self, registry: BehaviorModeRegistry) -> None:
        """Feedback domain returns FEEDBACK_MODE."""
        c = _make_classification(domain="feedback")
        mode = registry.get_mode(c)
        assert mode.name == "feedback"

    def test_play_query(self, registry: BehaviorModeRegistry) -> None:
        """Play read returns PLAY_QUERY_MODE."""
        c = _make_classification(semantics="read", domain="play")
        mode = registry.get_mode(c)
        assert mode.name == "play_query"
        assert mode.needs_tool is True

    def test_play_mutation(self, registry: BehaviorModeRegistry) -> None:
        """Play execute returns PLAY_MUTATION_MODE."""
        c = _make_classification(dest="file", semantics="execute", domain="play")
        mode = registry.get_mode(c)
        assert mode.name == "play_mutation"
        assert mode.verification_mode == "STANDARD"

    def test_undo_mode(self, registry: BehaviorModeRegistry) -> None:
        """Undo domain returns UNDO_MODE."""
        c = _make_classification(dest="file", semantics="execute", domain="undo")
        mode = registry.get_mode(c)
        assert mode.name == "undo"

    def test_system_read(self, registry: BehaviorModeRegistry) -> None:
        """System read returns SYSTEM_QUERY_MODE."""
        c = _make_classification(semantics="read", domain="system")
        mode = registry.get_mode(c)
        assert mode.name == "system_query"

    def test_tasks_read(self, registry: BehaviorModeRegistry) -> None:
        """Tasks read returns TASKS_QUERY_MODE."""
        c = _make_classification(semantics="read", domain="tasks")
        mode = registry.get_mode(c)
        assert mode.name == "tasks_query"

    def test_contacts_read(self, registry: BehaviorModeRegistry) -> None:
        """Contacts read returns CONTACTS_QUERY_MODE."""
        c = _make_classification(semantics="read", domain="contacts")
        mode = registry.get_mode(c)
        assert mode.name == "contacts_query"


class TestDomainDefaults:
    """Test domain-level default lookups."""

    def test_calendar_domain_default(self, registry: BehaviorModeRegistry) -> None:
        """Unregistered calendar combo falls back to domain default."""
        # This exact combo isn't registered but domain default should match
        c = _make_classification(dest="file", semantics="execute", domain="calendar")
        mode = registry.get_mode(c)
        assert mode.name == "calendar_query"

    def test_play_domain_default(self, registry: BehaviorModeRegistry) -> None:
        """Unregistered play combo falls back to domain default."""
        c = _make_classification(
            dest="process", consumer="machine", semantics="read", domain="play"
        )
        mode = registry.get_mode(c)
        assert mode.name == "play_query"


class TestFallbackModes:
    """Test semantics-based fallback when no domain match."""

    def test_interpret_fallback(self, registry: BehaviorModeRegistry) -> None:
        """No domain + interpret → conversation mode."""
        c = _make_classification()  # interpret, no domain
        mode = registry.get_mode(c)
        assert mode.name == "conversation"

    def test_read_fallback(self, registry: BehaviorModeRegistry) -> None:
        """No domain + read → generic query mode."""
        c = _make_classification(semantics="read")
        mode = registry.get_mode(c)
        assert mode.name == "generic_query"
        assert mode.needs_tool is False

    def test_execute_fallback(self, registry: BehaviorModeRegistry) -> None:
        """No domain + execute → generic mutation mode."""
        c = _make_classification(semantics="execute")
        mode = registry.get_mode(c)
        assert mode.name == "generic_mutation"
        assert mode.needs_tool is True
        assert mode.verification_mode == "STANDARD"


# =============================================================================
# Tool Selector Tests
# =============================================================================


class TestToolSelectors:
    """Test tool selector functions."""

    def test_static_tool_selector(self) -> None:
        """Static tool selector always returns the same tool."""
        selector = _static_tool("cairn_get_calendar")
        ctx = BehaviorModeContext(
            user_input="test",
            classification=_make_classification(),
        )
        assert selector(ctx) == "cairn_get_calendar"

    def test_play_tool_selector_list_acts(self) -> None:
        """Play tool selector returns cairn_list_acts for act queries."""
        ctx = BehaviorModeContext(
            user_input="Show me all my acts",
            classification=_make_classification(
                semantics="read", domain="play", action_hint="view"
            ),
        )
        assert _play_tool_selector(ctx) == "cairn_list_acts"

    def test_play_tool_selector_list_beats(self) -> None:
        """Play tool selector returns cairn_list_beats for beat queries."""
        ctx = BehaviorModeContext(
            user_input="Show me all my beats",
            classification=_make_classification(
                semantics="read", domain="play", action_hint="view"
            ),
        )
        assert _play_tool_selector(ctx) == "cairn_list_beats"

    def test_play_tool_selector_move_beat(self) -> None:
        """Play tool selector returns cairn_move_beat_to_act for move."""
        ctx = BehaviorModeContext(
            user_input="Move Job Search to Career act",
            classification=_make_classification(
                semantics="execute", domain="play", action_hint="update"
            ),
        )
        assert _play_tool_selector(ctx) == "cairn_move_beat_to_act"

    def test_play_tool_selector_create_act(self) -> None:
        """Play tool selector returns cairn_create_act for creation."""
        ctx = BehaviorModeContext(
            user_input="Create a new act called Hobbies",
            classification=_make_classification(
                semantics="execute", domain="play", action_hint="create"
            ),
        )
        assert _play_tool_selector(ctx) == "cairn_create_act"

    def test_play_tool_selector_should_be_in(self) -> None:
        """Play tool selector recognizes 'should be in' as move."""
        ctx = BehaviorModeContext(
            user_input="Job Search should be in the Career act",
            classification=_make_classification(
                semantics="execute", domain="play", action_hint="update"
            ),
        )
        assert _play_tool_selector(ctx) == "cairn_move_beat_to_act"

    def test_play_tool_selector_delete_scene(self) -> None:
        """Play tool selector returns cairn_delete_scene for scene deletion."""
        ctx = BehaviorModeContext(
            user_input="Delete the Planning scene",
            classification=_make_classification(
                semantics="execute", domain="play", action_hint="delete"
            ),
        )
        assert _play_tool_selector(ctx) == "cairn_delete_scene"

    def test_play_tool_selector_list_scenes(self) -> None:
        """Play tool selector returns cairn_list_scenes for scene queries."""
        ctx = BehaviorModeContext(
            user_input="Show me my scenes",
            classification=_make_classification(
                semantics="read", domain="play", action_hint="view"
            ),
        )
        assert _play_tool_selector(ctx) == "cairn_list_scenes"


# =============================================================================
# BehaviorMode Attributes Tests
# =============================================================================


class TestBehaviorModeAttributes:
    """Test that pre-defined modes have correct attributes."""

    def test_conversation_mode_no_hallucination_check(self) -> None:
        """Conversation mode skips hallucination check."""
        assert CONVERSATION_MODE.needs_hallucination_check is False

    def test_calendar_mode_has_hallucination_check(self) -> None:
        """Calendar mode does hallucination check."""
        assert CALENDAR_QUERY_MODE.needs_hallucination_check is True

    def test_play_mutation_standard_verification(self) -> None:
        """Play mutation uses STANDARD verification."""
        assert PLAY_MUTATION_MODE.verification_mode == "STANDARD"

    def test_conversation_mode_fast_verification(self) -> None:
        """Conversation mode uses FAST verification."""
        assert CONVERSATION_MODE.verification_mode == "FAST"

    def test_all_modes_have_names(self) -> None:
        """All pre-defined modes have non-empty names."""
        modes = [
            CONVERSATION_MODE,
            PERSONAL_QUERY_MODE,
            FEEDBACK_MODE,
            CALENDAR_QUERY_MODE,
            CONTACTS_QUERY_MODE,
            SYSTEM_QUERY_MODE,
            TASKS_QUERY_MODE,
            PLAY_QUERY_MODE,
            PLAY_MUTATION_MODE,
            UNDO_MODE,
        ]
        for mode in modes:
            assert mode.name, f"Mode missing name: {mode}"


# =============================================================================
# LLM-based Arg Extraction Tests
# =============================================================================


class TestLLMArgExtraction:
    """Test LLM-based argument extraction."""

    def test_beat_move_args_with_llm(self) -> None:
        """LLM extracts beat_name and target_act_name."""
        mock_llm = MagicMock()
        mock_llm.chat_json.return_value = '{"beat_name": "Job Search", "target_act_name": "Career"}'

        from reos.cairn.behavior_modes import _llm_extract_beat_move_args

        ctx = BehaviorModeContext(
            user_input="Move Job Search to Career act",
            classification=_make_classification(domain="play", action_hint="update"),
            play_data={
                "acts": [{"title": "Career"}, {"title": "Health"}],
                "all_beats": [{"title": "Job Search", "act_title": "Health"}],
            },
            llm=mock_llm,
        )
        args = _llm_extract_beat_move_args(ctx)

        assert args.get("beat_name") == "Job Search"
        assert args.get("target_act_name") == "Career"

    def test_beat_move_args_without_llm(self) -> None:
        """Without LLM, returns empty args."""
        from reos.cairn.behavior_modes import _llm_extract_beat_move_args

        ctx = BehaviorModeContext(
            user_input="Move Job Search to Career",
            classification=_make_classification(domain="play"),
            play_data={},
            llm=None,
        )
        args = _llm_extract_beat_move_args(ctx)
        assert args == {}

    def test_scene_move_args_with_llm(self) -> None:
        """LLM extracts scene move arguments."""
        mock_llm = MagicMock()
        mock_llm.chat_json.return_value = (
            '{"scene_name": "Planning", "act_name": "Career",' ' "new_act_name": "Health"}'
        )

        from reos.cairn.behavior_modes import _llm_extract_scene_move_args

        ctx = BehaviorModeContext(
            user_input="Move the Planning scene to Health",
            classification=_make_classification(domain="play", action_hint="update"),
            play_data={
                "acts": [{"title": "Career"}, {"title": "Health"}],
                "all_scenes": [{"title": "Planning", "act_title": "Career"}],
            },
            llm=mock_llm,
        )
        args = _llm_extract_scene_move_args(ctx)

        assert args.get("scene_name") == "Planning"
        assert args.get("new_act_name") == "Health"
        assert args.get("act_name") == "Career"
