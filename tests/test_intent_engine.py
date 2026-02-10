"""Tests for cairn/intent_engine.py — Response generation and hallucination checking.

Tests for:
- Intent category and action enums
- Hallucination detection
- Response generation (safe responses, feedback, conversation)
- Response parsing
- Event formatting
- Data classes
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from reos.cairn.intent_engine import (
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
    llm.chat_json.return_value = (
        '{"category": "CALENDAR", "action": "VIEW",'
        ' "target": "events", "confidence": 0.9, "reasoning": "test"}'
    )
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
            "CALENDAR",
            "CONTACTS",
            "SYSTEM",
            "CODE",
            "PERSONAL",
            "TASKS",
            "KNOWLEDGE",
            "PLAY",
            "UNDO",
            "FEEDBACK",
            "CONVERSATION",
            "UNKNOWN",
        ]
        actual = [c.name for c in IntentCategory]
        assert set(expected) == set(actual)

    def test_all_actions_defined(self) -> None:
        """All expected actions are defined."""
        expected = [
            "VIEW",
            "SEARCH",
            "CREATE",
            "UPDATE",
            "DELETE",
            "STATUS",
            "UNKNOWN",
        ]
        actual = [a.name for a in IntentAction]
        assert set(expected) == set(actual)


# =============================================================================
# Hallucination Detection Tests
# =============================================================================


class TestHallucinationDetection:
    """Test _verify_no_hallucination method."""

    def test_detect_platform_hallucination(self, intent_engine: CairnIntentEngine) -> None:
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

    def test_detect_event_hallucination_on_empty(self, intent_engine: CairnIntentEngine) -> None:
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

    def test_generate_safe_calendar_response_empty(self, intent_engine: CairnIntentEngine) -> None:
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
# Feedback Handling Tests
# =============================================================================


class TestFeedbackHandling:
    """Test _handle_feedback method."""

    def test_handle_repetition_complaint(self, intent_engine: CairnIntentEngine) -> None:
        """Handle 'you're repeating yourself' feedback."""
        intent = ExtractedIntent(
            category=IntentCategory.FEEDBACK,
            action=IntentAction.UNKNOWN,
            target="",
            raw_input="You're repeating yourself",
        )
        response = intent_engine._handle_feedback(intent)
        assert "apologize" in response.lower() or "repeating" in response.lower()

    def test_handle_misunderstanding(self, intent_engine: CairnIntentEngine) -> None:
        """Handle misunderstanding feedback."""
        intent = ExtractedIntent(
            category=IntentCategory.FEEDBACK,
            action=IntentAction.UNKNOWN,
            target="",
            raw_input="That's not what I meant",
        )
        response = intent_engine._handle_feedback(intent)
        assert "rephrase" in response.lower() or "misunderstanding" in response.lower()

    def test_handle_positive_feedback(self, intent_engine: CairnIntentEngine) -> None:
        """Handle positive feedback."""
        intent = ExtractedIntent(
            category=IntentCategory.FEEDBACK,
            action=IntentAction.UNKNOWN,
            target="",
            raw_input="That was helpful, thanks!",
        )
        response = intent_engine._handle_feedback(intent)
        assert "glad" in response.lower() or "help" in response.lower()


# =============================================================================
# Conversation Handling Tests
# =============================================================================


class TestConversationHandling:
    """Test _handle_conversation method."""

    def test_conversation_uses_llm(
        self,
        intent_engine: CairnIntentEngine,
        mock_llm: MagicMock,
    ) -> None:
        """Conversation handler calls LLM."""
        mock_llm.chat_text.return_value = "Good morning! How can I help?"
        intent = ExtractedIntent(
            category=IntentCategory.CONVERSATION,
            action=IntentAction.UNKNOWN,
            target="",
            raw_input="Good morning!",
        )
        response = intent_engine._handle_conversation(intent)
        mock_llm.chat_text.assert_called()
        assert len(response) > 0

    def test_conversation_fallback(
        self,
        intent_engine: CairnIntentEngine,
        mock_llm: MagicMock,
    ) -> None:
        """Conversation handler falls back on LLM error."""
        mock_llm.chat_text.side_effect = Exception("LLM unavailable")
        intent = ExtractedIntent(
            category=IntentCategory.CONVERSATION,
            action=IntentAction.UNKNOWN,
            target="",
            raw_input="Hi there!",
        )
        response = intent_engine._handle_conversation(intent)
        assert "Hello" in response or "help" in response.lower()


# =============================================================================
# Repetition Detection Tests
# =============================================================================


class TestRepetitionDetection:
    """Test _is_response_repetitive method."""

    def test_exact_duplicate_detected(self, intent_engine: CairnIntentEngine) -> None:
        """Detect exact duplicate responses."""
        intent_engine._track_response("Here is my response about the calendar.")
        assert intent_engine._is_response_repetitive("Here is my response about the calendar.")

    def test_similar_response_detected(self, intent_engine: CairnIntentEngine) -> None:
        """Detect highly similar responses."""
        intent_engine._track_response(
            "You have three events today: a meeting, lunch, and a review."
        )
        assert intent_engine._is_response_repetitive(
            "You have three events today: a meeting, a lunch, and a review."
        )

    def test_different_response_not_flagged(self, intent_engine: CairnIntentEngine) -> None:
        """Don't flag genuinely different responses."""
        intent_engine._track_response("Your calendar is empty today.")
        assert not intent_engine._is_response_repetitive(
            "You have 5 meetings scheduled for tomorrow."
        )

    def test_no_history_not_repetitive(self, intent_engine: CairnIntentEngine) -> None:
        """No history means nothing is repetitive."""
        assert not intent_engine._is_response_repetitive("Any response")


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

    def test_parse_response_with_thinking(self, intent_engine: CairnIntentEngine) -> None:
        """Parse response with thinking tags."""
        raw = """<thinking>
Step 1: Consider options
Step 2: Choose best one
</thinking>

Here is my response."""

        response, thinking = intent_engine._parse_response(raw)

        assert "Here is my response" in response
        assert len(thinking) > 0

    def test_parse_response_with_answer_tags(self, intent_engine: CairnIntentEngine) -> None:
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
        assert "14:30" not in formatted

    def test_format_invalid_time(self, intent_engine: CairnIntentEngine) -> None:
        """Handle invalid time formats gracefully."""
        formatted = intent_engine._format_event_time("not a date")

        assert formatted == "not a date"
