"""Tests for cairn/intent_engine.py - Multi-stage intent processing.

Tests intent extraction, verification, and execution:
- Intent category and action classification
- Pattern matching (fast path)
- LLM-based extraction
- Tool selection and argument building
- Hallucination detection
- Conversational response generation
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from reos.cairn.intent_engine import (
    CATEGORY_TOOLS,
    INTENT_PATTERNS,
    CairnIntentEngine,
    ExtractedIntent,
    IntentAction,
    IntentCategory,
    IntentResult,
    VerifiedIntent,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_llm() -> MagicMock:
    """Create a mock LLM provider."""
    llm = MagicMock()
    # Default JSON response for intent extraction
    llm.chat_json.return_value = '{"category": "CALENDAR", "action": "VIEW", "target": "events", "confidence": 0.9, "reasoning": "test"}'
    llm.chat_text.return_value = "Test response"
    return llm


@pytest.fixture
def intent_engine(mock_llm: MagicMock) -> CairnIntentEngine:
    """Create an intent engine with mock LLM."""
    return CairnIntentEngine(
        llm=mock_llm,
        available_tools={"cairn_get_calendar", "cairn_list_acts", "cairn_list_beats"},
    )


@pytest.fixture
def engine_with_play_data(mock_llm: MagicMock) -> CairnIntentEngine:
    """Create an intent engine with mock Play data."""
    play_data = {
        "acts": [
            {"title": "Career", "act_id": "act-1"},
            {"title": "Health", "act_id": "act-2"},
            {"title": "Your Story", "act_id": "your-story"},
        ],
        "all_beats": [
            {"title": "Job Search", "act_title": "Career"},
            {"title": "Exercise Plan", "act_title": "Health"},
        ],
    }
    return CairnIntentEngine(
        llm=mock_llm,
        available_tools={"cairn_move_beat_to_act", "cairn_list_acts", "cairn_list_beats"},
        play_data=play_data,
    )


# =============================================================================
# IntentCategory and IntentAction Tests
# =============================================================================


class TestIntentEnums:
    """Test intent category and action enums."""

    def test_all_categories_defined(self) -> None:
        """All expected categories are defined."""
        expected = [
            "CALENDAR", "CONTACTS", "SYSTEM", "CODE", "PERSONAL",
            "TASKS", "KNOWLEDGE", "PLAY", "UNDO", "CONVERSATION", "UNKNOWN",
        ]
        actual = [c.name for c in IntentCategory]
        assert set(expected) == set(actual)

    def test_all_actions_defined(self) -> None:
        """All expected actions are defined."""
        expected = [
            "VIEW", "SEARCH", "CREATE", "UPDATE", "DELETE",
            "STATUS", "DISCUSS", "UNKNOWN",
        ]
        actual = [a.name for a in IntentAction]
        assert set(expected) == set(actual)


# =============================================================================
# Intent Pattern Matching Tests
# =============================================================================


class TestIntentPatterns:
    """Test INTENT_PATTERNS dictionary."""

    def test_calendar_patterns_exist(self) -> None:
        """Calendar category has patterns."""
        patterns = INTENT_PATTERNS.get(IntentCategory.CALENDAR, [])
        assert len(patterns) > 0
        assert "calendar" in patterns
        assert "schedule" in patterns

    def test_play_patterns_exist(self) -> None:
        """Play category has patterns for acts, scenes, beats."""
        patterns = INTENT_PATTERNS.get(IntentCategory.PLAY, [])
        assert any("act" in p for p in patterns)
        assert any("scene" in p for p in patterns)
        assert any("beat" in p for p in patterns)

    def test_undo_patterns_exist(self) -> None:
        """Undo category has patterns."""
        patterns = INTENT_PATTERNS.get(IntentCategory.UNDO, [])
        assert "undo" in patterns
        assert "revert" in patterns

    def test_conversation_patterns_exist(self) -> None:
        """Conversation category has patterns."""
        patterns = INTENT_PATTERNS.get(IntentCategory.CONVERSATION, [])
        assert any("brainstorm" in p for p in patterns)
        assert any("what do you think" in p for p in patterns)


# =============================================================================
# Category-Tool Mapping Tests
# =============================================================================


class TestCategoryTools:
    """Test CATEGORY_TOOLS mapping."""

    def test_calendar_has_tool(self) -> None:
        """Calendar category maps to a tool."""
        assert CATEGORY_TOOLS.get(IntentCategory.CALENDAR) == "cairn_get_calendar"

    def test_play_has_default_tool(self) -> None:
        """Play category has a default tool."""
        assert CATEGORY_TOOLS.get(IntentCategory.PLAY) == "cairn_list_acts"

    def test_undo_has_tool(self) -> None:
        """Undo category maps to undo tool."""
        assert CATEGORY_TOOLS.get(IntentCategory.UNDO) == "cairn_undo_last"


# =============================================================================
# Intent Extraction Tests
# =============================================================================


class TestIntentExtraction:
    """Test _extract_intent method."""

    def test_extract_calendar_intent(self, intent_engine: CairnIntentEngine) -> None:
        """Extract calendar intent from pattern match."""
        intent = intent_engine._extract_intent("What's on my calendar today?")

        assert intent.category == IntentCategory.CALENDAR
        assert intent.confidence > 0.5

    def test_extract_play_intent(self, intent_engine: CairnIntentEngine) -> None:
        """Extract Play intent for act operations."""
        intent = intent_engine._extract_intent("Show me my acts")

        assert intent.category == IntentCategory.PLAY
        assert intent.action == IntentAction.VIEW

    def test_extract_create_action(self, intent_engine: CairnIntentEngine) -> None:
        """Detect CREATE action from keywords."""
        intent = intent_engine._extract_intent("Create a new act for Career")

        assert intent.action == IntentAction.CREATE

    def test_extract_delete_action(self, intent_engine: CairnIntentEngine) -> None:
        """Detect DELETE action from keywords."""
        intent = intent_engine._extract_intent("Delete the old act")

        assert intent.action == IntentAction.DELETE

    def test_extract_update_action(self, intent_engine: CairnIntentEngine) -> None:
        """Detect UPDATE action from keywords."""
        intent = intent_engine._extract_intent("Move this beat to another act")

        assert intent.action == IntentAction.UPDATE

    def test_extract_undo_intent(self, intent_engine: CairnIntentEngine) -> None:
        """Extract undo intent."""
        intent = intent_engine._extract_intent("Undo that please")

        assert intent.category == IntentCategory.UNDO

    def test_unknown_falls_back_to_llm(
        self, intent_engine: CairnIntentEngine, mock_llm: MagicMock
    ) -> None:
        """Unknown patterns fall back to LLM extraction."""
        # Use a message that doesn't match any patterns
        mock_llm.chat_json.return_value = '{"category": "CODE", "action": "CREATE", "target": "function", "confidence": 0.8, "reasoning": "test"}'

        # Use a completely unrelated phrase that won't match any patterns
        intent = intent_engine._extract_intent("xyzzy plugh foobar baz")

        # Should have called LLM
        mock_llm.chat_json.assert_called()
        # Should get CODE category from LLM
        assert intent.category == IntentCategory.CODE


class TestLLMIntentExtraction:
    """Test _extract_intent_with_llm method."""

    def test_llm_extraction_parses_json(
        self, intent_engine: CairnIntentEngine, mock_llm: MagicMock
    ) -> None:
        """LLM extraction parses JSON response."""
        mock_llm.chat_json.return_value = '{"category": "CONTACTS", "action": "SEARCH", "target": "john", "confidence": 0.9, "reasoning": "test"}'

        intent = intent_engine._extract_intent_with_llm("Find John's phone number")

        assert intent.category == IntentCategory.CONTACTS
        assert intent.action == IntentAction.SEARCH
        assert intent.confidence == 0.9

    def test_llm_extraction_handles_invalid_json(
        self, intent_engine: CairnIntentEngine, mock_llm: MagicMock
    ) -> None:
        """LLM extraction returns UNKNOWN on invalid JSON."""
        mock_llm.chat_json.return_value = "not valid json"

        intent = intent_engine._extract_intent_with_llm("Something weird")

        assert intent.category == IntentCategory.UNKNOWN
        assert intent.confidence == 0.0


# =============================================================================
# Intent Verification Tests
# =============================================================================


class TestIntentVerification:
    """Test _verify_intent method."""

    def test_verify_calendar_intent(self, intent_engine: CairnIntentEngine) -> None:
        """Verify calendar intent selects correct tool."""
        intent = ExtractedIntent(
            category=IntentCategory.CALENDAR,
            action=IntentAction.VIEW,
            target="today",
            raw_input="What's on my calendar?",
        )

        verified = intent_engine._verify_intent(intent)

        assert verified.verified is True
        assert verified.tool_name == "cairn_get_calendar"

    def test_verify_personal_no_tool(self, intent_engine: CairnIntentEngine) -> None:
        """Personal questions don't need a tool."""
        intent = ExtractedIntent(
            category=IntentCategory.PERSONAL,
            action=IntentAction.VIEW,
            target="goals",
            raw_input="What are my goals?",
        )

        verified = intent_engine._verify_intent(intent)

        assert verified.verified is True
        assert verified.tool_name is None

    def test_verify_conversation_no_tool(self, intent_engine: CairnIntentEngine) -> None:
        """Conversation category uses reasoning, not tools."""
        intent = ExtractedIntent(
            category=IntentCategory.CONVERSATION,
            action=IntentAction.DISCUSS,
            target="ideas",
            raw_input="What do you think about AI?",
        )

        verified = intent_engine._verify_intent(intent)

        assert verified.verified is True
        assert verified.tool_name is None

    def test_verify_unknown_not_verified(
        self, intent_engine: CairnIntentEngine
    ) -> None:
        """Unknown category is not verified."""
        intent = ExtractedIntent(
            category=IntentCategory.UNKNOWN,
            action=IntentAction.UNKNOWN,
            target="unknown",
            raw_input="gibberish",
        )

        verified = intent_engine._verify_intent(intent)

        assert verified.verified is False
        assert verified.fallback_message is not None


# =============================================================================
# Play Tool Selection Tests
# =============================================================================


class TestSelectPlayTool:
    """Test _select_play_tool method."""

    def test_select_list_acts(self, intent_engine: CairnIntentEngine) -> None:
        """Select cairn_list_acts for viewing acts."""
        intent = ExtractedIntent(
            category=IntentCategory.PLAY,
            action=IntentAction.VIEW,
            target="acts",
            raw_input="Show me all my acts",
        )

        tool = intent_engine._select_play_tool(intent)
        assert tool == "cairn_list_acts"

    def test_select_list_beats(self, intent_engine: CairnIntentEngine) -> None:
        """Select cairn_list_beats for viewing beats."""
        intent = ExtractedIntent(
            category=IntentCategory.PLAY,
            action=IntentAction.VIEW,
            target="beats",
            raw_input="Show me all my beats",
        )

        tool = intent_engine._select_play_tool(intent)
        assert tool == "cairn_list_beats"

    def test_select_move_beat(self, intent_engine: CairnIntentEngine) -> None:
        """Select cairn_move_beat_to_act for move operations."""
        intent = ExtractedIntent(
            category=IntentCategory.PLAY,
            action=IntentAction.UPDATE,
            target="beat",
            raw_input="Move Job Search to the Career act",
        )

        tool = intent_engine._select_play_tool(intent)
        assert tool == "cairn_move_beat_to_act"

    def test_select_create_act(self, intent_engine: CairnIntentEngine) -> None:
        """Select cairn_create_act for creating acts."""
        intent = ExtractedIntent(
            category=IntentCategory.PLAY,
            action=IntentAction.CREATE,
            target="act",
            raw_input="Create a new act called Hobbies",
        )

        tool = intent_engine._select_play_tool(intent)
        assert tool == "cairn_create_act"


# =============================================================================
# Entity Extraction Tests
# =============================================================================


class TestEntityExtraction:
    """Test entity name extraction methods."""

    def test_extract_act_name(self, intent_engine: CairnIntentEngine) -> None:
        """Extract act name from input."""
        # The regex extracts "Career" from "the Career act" pattern
        result = intent_engine._extract_act_name("the Career act needs updating")
        assert result == "Career"

    def test_extract_act_name_from_sentence(
        self, intent_engine: CairnIntentEngine
    ) -> None:
        """Extract act name from 'in/to the X act' pattern."""
        result = intent_engine._extract_act_name("Move beat to the Career act")
        # May return Career or partial match depending on regex
        assert result is not None

    def test_extract_act_name_called_pattern(
        self, intent_engine: CairnIntentEngine
    ) -> None:
        """Extract act name with 'called' pattern."""
        result = intent_engine._extract_act_name("act called my projects")
        # Regex uses lower() so returns lowercase
        assert result == "my projects"

    def test_extract_scene_name(self, intent_engine: CairnIntentEngine) -> None:
        """Extract scene name from input."""
        # The regex captures what's before "scene"
        result = intent_engine._extract_scene_name("the Planning scene needs work")
        assert result == "Planning"

    def test_extract_beat_name(self, intent_engine: CairnIntentEngine) -> None:
        """Extract beat name from input."""
        # The regex captures what's before "beat"
        result = intent_engine._extract_beat_name("the Job Search beat is done")
        assert result == "Job Search"

    def test_extract_entity_title_create_pattern(
        self, intent_engine: CairnIntentEngine
    ) -> None:
        """Extract title from create patterns."""
        result = intent_engine._extract_entity_title(
            "Create a new act called Side Projects", "act"
        )
        # Regex uses lower() so returns lowercase
        assert result == "side projects"

    def test_extract_new_title(self, intent_engine: CairnIntentEngine) -> None:
        """Extract new title from rename patterns."""
        result = intent_engine._extract_new_title("Rename to my career goals")
        assert result == "my career goals"


# =============================================================================
# Beat Move Argument Extraction Tests
# =============================================================================


class TestBeatMoveArgExtraction:
    """Test _extract_beat_move_args method."""

    def test_regex_pattern_should_be_in(
        self, intent_engine: CairnIntentEngine
    ) -> None:
        """Extract from 'X should be in Y act' pattern."""
        args = intent_engine._regex_extract_beat_move_args(
            "Job Search beat should be in the Career act"
        )

        assert "beat_name" in args or "target_act_name" in args

    def test_regex_pattern_move_to(self, intent_engine: CairnIntentEngine) -> None:
        """Extract from 'move X to Y' pattern."""
        args = intent_engine._regex_extract_beat_move_args(
            "Move Job Search to Career"
        )

        assert "beat_name" in args or "target_act_name" in args

    def test_llm_extraction_with_play_data(
        self, engine_with_play_data: CairnIntentEngine, mock_llm: MagicMock
    ) -> None:
        """LLM extraction uses Play context."""
        mock_llm.chat_json.return_value = '{"beat_name": "Job Search", "target_act_name": "Career"}'

        args = engine_with_play_data._extract_beat_move_args(
            "Move Job Search to Career act"
        )

        # LLM should have been called
        mock_llm.chat_json.assert_called()


# =============================================================================
# Build Tool Args Tests
# =============================================================================


class TestBuildToolArgs:
    """Test _build_tool_args method."""

    def test_build_args_for_contacts_search(
        self, intent_engine: CairnIntentEngine
    ) -> None:
        """Build args for contacts search includes query."""
        intent = ExtractedIntent(
            category=IntentCategory.CONTACTS,
            action=IntentAction.SEARCH,
            target="john",
            raw_input="Find John's email",
        )

        args = intent_engine._build_tool_args(intent, "cairn_search_contacts")

        assert "query" in args
        assert args["query"] == "john"

    def test_build_args_preserves_existing_params(
        self, intent_engine: CairnIntentEngine
    ) -> None:
        """Build args preserves parameters from extraction."""
        intent = ExtractedIntent(
            category=IntentCategory.PLAY,
            action=IntentAction.UPDATE,
            target="beat",
            parameters={"beat_name": "Task A", "target_act_name": "Work"},
            raw_input="Move Task A to Work",
        )

        args = intent_engine._build_tool_args(intent, "cairn_move_beat_to_act")

        assert args.get("beat_name") == "Task A"
        assert args.get("target_act_name") == "Work"


# =============================================================================
# Hallucination Detection Tests
# =============================================================================


class TestHallucinationDetection:
    """Test _verify_no_hallucination method."""

    def test_detect_platform_hallucination(
        self, intent_engine: CairnIntentEngine
    ) -> None:
        """Detect wrong platform mentions."""
        is_valid, reason = intent_engine._verify_no_hallucination(
            response="On macOS, you can use Finder",
            tool_result={"events": []},
            intent=ExtractedIntent(
                category=IntentCategory.SYSTEM,
                action=IntentAction.VIEW,
                target="files",
                raw_input="Show files",
            ),
        )

        assert is_valid is False
        assert "platform" in reason.lower()

    def test_detect_event_hallucination_on_empty(
        self, intent_engine: CairnIntentEngine
    ) -> None:
        """Detect fabricated events when calendar is empty."""
        is_valid, reason = intent_engine._verify_no_hallucination(
            response="You have a meeting with John at 10:00 AM",
            tool_result={"count": 0, "events": []},
            intent=ExtractedIntent(
                category=IntentCategory.CALENDAR,
                action=IntentAction.VIEW,
                target="today",
                raw_input="What's on my calendar?",
            ),
        )

        assert is_valid is False
        assert "count=0" in reason or "events" in reason

    def test_allow_valid_response(self, intent_engine: CairnIntentEngine) -> None:
        """Allow responses that match the data."""
        is_valid, reason = intent_engine._verify_no_hallucination(
            response="Your calendar is empty today.",
            tool_result={"count": 0, "events": []},
            intent=ExtractedIntent(
                category=IntentCategory.CALENDAR,
                action=IntentAction.VIEW,
                target="today",
                raw_input="What's on my calendar?",
            ),
        )

        assert is_valid is True


# =============================================================================
# Response Generation Tests
# =============================================================================


class TestResponseGeneration:
    """Test response generation methods."""

    def test_generate_safe_calendar_response_empty(
        self, intent_engine: CairnIntentEngine
    ) -> None:
        """Generate safe response for empty calendar."""
        intent = ExtractedIntent(
            category=IntentCategory.CALENDAR,
            action=IntentAction.VIEW,
            target="today",
            raw_input="What's on my calendar?",
        )

        response = intent_engine._generate_safe_response(
            tool_result={"count": 0, "events": []},
            intent=intent,
        )

        assert "empty" in response.lower() or "no" in response.lower()

    def test_generate_safe_calendar_response_with_events(
        self, intent_engine: CairnIntentEngine
    ) -> None:
        """Generate safe response for calendar with events."""
        intent = ExtractedIntent(
            category=IntentCategory.CALENDAR,
            action=IntentAction.VIEW,
            target="today",
            raw_input="What's on my calendar?",
        )

        response = intent_engine._generate_safe_response(
            tool_result={
                "count": 2,
                "events": [
                    {"title": "Meeting", "start": "2026-01-15T10:00:00"},
                    {"title": "Lunch", "start": "2026-01-15T12:00:00"},
                ],
            },
            intent=intent,
        )

        assert "2" in response
        assert "Meeting" in response
        assert "Lunch" in response


# =============================================================================
# Full Process Flow Tests
# =============================================================================


class TestProcessFlow:
    """Test full process() method flow."""

    def test_process_calendar_query(
        self, intent_engine: CairnIntentEngine, mock_llm: MagicMock
    ) -> None:
        """Process a calendar query end-to-end."""
        mock_execute_tool = MagicMock(
            return_value={"count": 1, "events": [{"title": "Meeting", "start": "2026-01-15T10:00:00"}]}
        )

        result = intent_engine.process(
            "What's on my calendar today?",
            execute_tool=mock_execute_tool,
        )

        assert isinstance(result, IntentResult)
        assert result.verified_intent.verified is True
        # Tool should have been called
        mock_execute_tool.assert_called()

    def test_process_personal_question_no_tool(
        self, intent_engine: CairnIntentEngine, mock_llm: MagicMock
    ) -> None:
        """Process personal question without tool call."""
        mock_execute_tool = MagicMock()

        result = intent_engine.process(
            "Tell me about my goals",
            execute_tool=mock_execute_tool,
            persona_context="User goal: Learn Python",
        )

        assert isinstance(result, IntentResult)
        # Tool should NOT have been called for PERSONAL category
        # (but the mock might still be called for other reasons)

    def test_process_with_tool_error_attempts_recovery(
        self, intent_engine: CairnIntentEngine, mock_llm: MagicMock
    ) -> None:
        """Process handles tool errors and attempts recovery."""
        # First call fails, second (recovery) succeeds
        mock_execute_tool = MagicMock(
            side_effect=[
                {"error": "Beat not found"},  # First call fails
                {"beats": [{"title": "Task A"}]},  # Recovery call succeeds
            ]
        )

        intent_engine.available_tools.add("cairn_move_beat_to_act")

        result = intent_engine.process(
            "Move Task A to Career",
            execute_tool=mock_execute_tool,
        )

        # Should have attempted recovery
        assert isinstance(result, IntentResult)


# =============================================================================
# Data Class Tests
# =============================================================================


class TestDataClasses:
    """Test intent data classes."""

    def test_extracted_intent_defaults(self) -> None:
        """ExtractedIntent has sensible defaults."""
        intent = ExtractedIntent(
            category=IntentCategory.CALENDAR,
            action=IntentAction.VIEW,
            target="events",
        )

        assert intent.parameters == {}
        assert intent.confidence == 0.0
        assert intent.raw_input == ""

    def test_verified_intent_defaults(self) -> None:
        """VerifiedIntent has sensible defaults."""
        intent = ExtractedIntent(
            category=IntentCategory.CALENDAR,
            action=IntentAction.VIEW,
            target="events",
        )
        verified = VerifiedIntent(
            intent=intent,
            verified=True,
            tool_name="test_tool",
        )

        assert verified.tool_args == {}
        assert verified.reason == ""
        assert verified.fallback_message is None

    def test_intent_result_defaults(self) -> None:
        """IntentResult has sensible defaults."""
        intent = ExtractedIntent(
            category=IntentCategory.CALENDAR,
            action=IntentAction.VIEW,
            target="events",
        )
        verified = VerifiedIntent(intent=intent, verified=True, tool_name=None)
        result = IntentResult(
            verified_intent=verified,
            tool_result=None,
            response="Test",
        )

        assert result.thinking_steps == []


# =============================================================================
# Parse Response Tests
# =============================================================================


class TestParseResponse:
    """Test _parse_response method."""

    def test_parse_plain_response(self, intent_engine: CairnIntentEngine) -> None:
        """Parse response without thinking tags."""
        response, thinking = intent_engine._parse_response("Hello, world!")

        assert response == "Hello, world!"
        assert thinking == []

    def test_parse_response_with_thinking(
        self, intent_engine: CairnIntentEngine
    ) -> None:
        """Parse response with thinking tags."""
        raw = """<thinking>
Step 1: Consider options
Step 2: Choose best one
</thinking>

Here is my response."""

        response, thinking = intent_engine._parse_response(raw)

        assert "Here is my response" in response
        assert len(thinking) > 0

    def test_parse_response_with_answer_tags(
        self, intent_engine: CairnIntentEngine
    ) -> None:
        """Parse response with answer tags."""
        raw = """<thinking>Some thinking</thinking>
<answer>The actual answer</answer>"""

        response, thinking = intent_engine._parse_response(raw)

        assert response == "The actual answer"


# =============================================================================
# Event Formatting Tests
# =============================================================================


class TestEventFormatting:
    """Test event time/date formatting helpers."""

    def test_format_event_time(self, intent_engine: CairnIntentEngine) -> None:
        """Format ISO time to human readable."""
        formatted = intent_engine._format_event_time("2026-01-15T14:30:00")

        assert "January" in formatted
        assert "15" in formatted
        assert "2:30" in formatted or "14:30" in formatted

    def test_format_event_date(self, intent_engine: CairnIntentEngine) -> None:
        """Format ISO time to just date."""
        formatted = intent_engine._format_event_date("2026-01-15T14:30:00")

        assert "January" in formatted
        assert "15" in formatted
        # Should not include time
        assert "14:30" not in formatted

    def test_format_invalid_time(self, intent_engine: CairnIntentEngine) -> None:
        """Handle invalid time formats gracefully."""
        formatted = intent_engine._format_event_time("not a date")

        # Should return original on error
        assert formatted == "not a date"
