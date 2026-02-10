"""Tests for cairn/response_generator.py — Response generation, hallucination checking.

Tests the ResponseGenerator class directly (not through CairnIntentEngine delegation).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from reos.cairn.response_generator import ResponseGenerator

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_llm() -> MagicMock:
    llm = MagicMock()
    llm.chat_text.return_value = "Test response"
    llm.chat_json.return_value = '{"is_grounded": true, "reason": ""}'
    return llm


@pytest.fixture
def rg(mock_llm: MagicMock) -> ResponseGenerator:
    return ResponseGenerator(llm=mock_llm)


@pytest.fixture
def rg_no_llm() -> ResponseGenerator:
    return ResponseGenerator(llm=None)


# =============================================================================
# Feedback Tests
# =============================================================================


class TestFeedbackHandling:
    def test_repetition_complaint(self, rg: ResponseGenerator) -> None:
        response = rg.handle_feedback("You're repeating yourself")
        assert "apologize" in response.lower() or "repeating" in response.lower()

    def test_misunderstanding(self, rg: ResponseGenerator) -> None:
        response = rg.handle_feedback("That's not what I meant")
        assert "rephrase" in response.lower() or "misunderstanding" in response.lower()

    def test_positive_feedback(self, rg: ResponseGenerator) -> None:
        response = rg.handle_feedback("That was helpful, thanks!")
        assert "glad" in response.lower() or "help" in response.lower()

    def test_quality_complaint(self, rg: ResponseGenerator) -> None:
        response = rg.handle_feedback("That was confusing")
        assert "sorry" in response.lower()

    def test_generic_feedback(self, rg: ResponseGenerator) -> None:
        response = rg.handle_feedback("Some random feedback")
        assert "feedback" in response.lower() or "help" in response.lower()


# =============================================================================
# Conversation Tests
# =============================================================================


class TestConversationHandling:
    def test_conversation_uses_llm(self, rg: ResponseGenerator, mock_llm: MagicMock) -> None:
        mock_llm.chat_text.return_value = "Good morning! How can I help?"
        response = rg.handle_conversation("Good morning!")
        mock_llm.chat_text.assert_called()
        assert len(response) > 0

    def test_conversation_fallback_no_llm(self, rg_no_llm: ResponseGenerator) -> None:
        response = rg_no_llm.handle_conversation("Hi there!")
        assert "Hello" in response or "help" in response.lower()

    def test_conversation_fallback_on_error(
        self, rg: ResponseGenerator, mock_llm: MagicMock
    ) -> None:
        mock_llm.chat_text.side_effect = Exception("LLM down")
        response = rg.handle_conversation("Hey!")
        assert "Hello" in response


# =============================================================================
# Hallucination Detection Tests
# =============================================================================


class TestHallucinationDetection:
    def test_detect_platform_hallucination(self, rg: ResponseGenerator) -> None:
        is_valid, reason = rg.verify_no_hallucination(
            response="On macOS, you can use Finder",
            tool_result={"events": []},
        )
        assert is_valid is False
        assert "platform" in reason.lower()

    def test_detect_event_hallucination_on_empty(self, rg: ResponseGenerator) -> None:
        is_valid, reason = rg.verify_no_hallucination(
            response="You have a meeting with John at 10:00 AM",
            tool_result={"count": 0, "events": []},
        )
        assert is_valid is False

    def test_allow_valid_empty_response(self, rg: ResponseGenerator) -> None:
        is_valid, reason = rg.verify_no_hallucination(
            response="Your calendar is empty today.",
            tool_result={"count": 0, "events": []},
        )
        assert is_valid is True

    def test_llm_grounding_check(self, rg: ResponseGenerator, mock_llm: MagicMock) -> None:
        mock_llm.chat_json.return_value = '{"is_grounded": true, "reason": ""}'
        is_valid, reason = rg.verify_no_hallucination(
            response="You have a meeting at 10 AM.",
            tool_result={"count": 1, "events": [{"title": "Meeting", "start": "10:00"}]},
        )
        assert is_valid is True

    def test_llm_grounding_rejects(self, rg: ResponseGenerator, mock_llm: MagicMock) -> None:
        mock_llm.chat_json.return_value = '{"is_grounded": false, "reason": "Made up data"}'
        is_valid, reason = rg.verify_no_hallucination(
            response="You have 5 meetings today.",
            tool_result={"count": 1, "events": [{"title": "Meeting"}]},
        )
        assert is_valid is False
        assert "Made up data" in reason


# =============================================================================
# Repetition Detection Tests
# =============================================================================


class TestRepetitionDetection:
    def test_exact_duplicate(self, rg: ResponseGenerator) -> None:
        rg.track_response("Here is my response about the calendar.")
        assert rg.is_response_repetitive("Here is my response about the calendar.")

    def test_similar_response(self, rg: ResponseGenerator) -> None:
        rg.track_response("You have three events today: a meeting, lunch, and a review.")
        assert rg.is_response_repetitive(
            "You have three events today: a meeting, a lunch, and a review."
        )

    def test_different_response(self, rg: ResponseGenerator) -> None:
        rg.track_response("Your calendar is empty today.")
        assert not rg.is_response_repetitive("You have 5 meetings scheduled for tomorrow.")

    def test_no_history(self, rg: ResponseGenerator) -> None:
        assert not rg.is_response_repetitive("Any response")

    def test_history_limit(self, rg: ResponseGenerator) -> None:
        for i in range(10):
            rg.track_response(f"Unique response number {i} with enough words to matter")
        assert len(rg._response_history) == ResponseGenerator.MAX_RESPONSE_HISTORY


# =============================================================================
# Parse Response Tests
# =============================================================================


class TestParseResponse:
    def test_plain_response(self, rg: ResponseGenerator) -> None:
        response, thinking = rg.parse_response("Hello, world!")
        assert response == "Hello, world!"
        assert thinking == []

    def test_response_with_thinking(self, rg: ResponseGenerator) -> None:
        raw = "<thinking>\nStep 1\nStep 2\n</thinking>\n\nHere is my response."
        response, thinking = rg.parse_response(raw)
        assert "Here is my response" in response
        assert len(thinking) > 0

    def test_response_with_answer_tags(self, rg: ResponseGenerator) -> None:
        raw = "<thinking>Some thinking</thinking>\n<answer>The actual answer</answer>"
        response, thinking = rg.parse_response(raw)
        assert response == "The actual answer"


# =============================================================================
# Event Formatting Tests
# =============================================================================


class TestEventFormatting:
    def test_format_event_time(self, rg: ResponseGenerator) -> None:
        formatted = rg.format_event_time("2026-01-15T14:30:00")
        assert "January" in formatted
        assert "15" in formatted

    def test_format_event_date(self, rg: ResponseGenerator) -> None:
        formatted = rg.format_event_date("2026-01-15T14:30:00")
        assert "January" in formatted
        assert "14:30" not in formatted

    def test_format_invalid_time(self, rg: ResponseGenerator) -> None:
        assert rg.format_event_time("not a date") == "not a date"


# =============================================================================
# Generate From Tool Result Tests
# =============================================================================


class TestGenerateFromToolResult:
    def test_generates_from_tool_result(self, rg: ResponseGenerator, mock_llm: MagicMock) -> None:
        mock_llm.chat_text.return_value = "You have 2 events today."
        response = rg.generate_from_tool_result(
            user_input="What's on my calendar?",
            tool_result={"count": 2, "events": [{"title": "A"}, {"title": "B"}]},
        )
        assert "2 events" in response

    def test_no_llm_returns_json(self, rg_no_llm: ResponseGenerator) -> None:
        response = rg_no_llm.generate_from_tool_result(
            user_input="test",
            tool_result={"key": "value"},
        )
        assert "key" in response
        assert "value" in response

    def test_personal_response(self, rg: ResponseGenerator, mock_llm: MagicMock) -> None:
        mock_llm.chat_text.return_value = "Your goal is to learn Python."
        response = rg.generate_personal_response(
            user_input="What are my goals?",
            persona_context="User goal: Learn Python",
        )
        assert "Python" in response


# =============================================================================
# Recovery and Clarification Tests
# =============================================================================


class TestRecoveryAndClarification:
    def test_clarification_for_missing_data(self, rg: ResponseGenerator) -> None:
        response = rg.ask_for_clarification(
            user_input="Move X to Y",
            domain="play",
            action="update",
            rejection_reason="X not in the provided data",
        )
        assert "list beats" in response.lower() or "list acts" in response.lower()

    def test_generic_clarification(self, rg: ResponseGenerator) -> None:
        response = rg.ask_for_clarification(
            user_input="Do the thing",
            domain="system",
            action="view",
            rejection_reason="Cannot determine",
        )
        assert "rephrase" in response.lower()

    def test_recovery_with_beats(self, rg: ResponseGenerator) -> None:
        mock_execute = MagicMock(return_value={"beats": [{"title": "Beat A"}, {"title": "Beat B"}]})
        result = rg.recover_with_clarification(
            user_input="Move beat X to Career",
            domain="play",
            action="update",
            rejection_reason="not found",
            execute_tool=mock_execute,
        )
        assert result is not None
        assert "Beat A" in result

    def test_recovery_returns_none_when_no_beats(self, rg: ResponseGenerator) -> None:
        mock_execute = MagicMock(return_value={"beats": []})
        result = rg.recover_with_clarification(
            user_input="Move beat X to Career",
            domain="play",
            action="update",
            rejection_reason="not found",
            execute_tool=mock_execute,
        )
        assert result is None
