"""Tests for verification.intent_verifier — LLM-as-judge verification."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from reos.providers.base import LLMError
from verification.intent_verifier import IntentJudgment, LLMIntentVerifier


class MockLLM:
    """Mock LLM for intent verification tests."""

    def __init__(self, response: dict | None = None, error: Exception | None = None):
        self._response = response or {}
        self._error = error
        self.last_system: str = ""
        self.last_user: str = ""

    @property
    def provider_type(self) -> str:
        return "mock"

    def chat_json(self, *, system: str, user: str, **kwargs) -> str:
        self.last_system = system
        self.last_user = user
        if self._error:
            raise self._error
        return json.dumps(self._response)

    def chat_text(self, **kwargs) -> str:
        return "ok"

    def list_models(self):
        return []

    def check_health(self):
        return MagicMock(reachable=True)


class TestLLMIntentVerifier:
    """Test LLM-as-judge intent verification."""

    def test_aligned_response(self):
        llm = MockLLM(response={
            "alignment": 0.95,
            "missed_aspects": [],
            "scope_creep": [],
            "issues": [],
            "reasoning": "Response directly addresses the question",
        })

        verifier = LLMIntentVerifier(llm=llm)
        result = verifier.verify(
            request="What time is it?",
            response="It's 3:45 PM.",
        )

        assert result.aligned is True
        assert result.alignment_score == 0.95
        assert result.missed_aspects == []
        assert result.scope_creep == []

    def test_misaligned_response(self):
        llm = MockLLM(response={
            "alignment": 0.3,
            "missed_aspects": ["Did not answer the time question"],
            "scope_creep": ["Added weather information"],
            "issues": ["Response is off-topic"],
            "reasoning": "Response talks about weather instead of time",
        })

        verifier = LLMIntentVerifier(llm=llm)
        result = verifier.verify(
            request="What time is it?",
            response="The weather is nice today!",
        )

        assert result.aligned is False
        assert result.alignment_score == 0.3
        assert len(result.missed_aspects) == 1
        assert len(result.scope_creep) == 1

    def test_borderline_alignment(self):
        llm = MockLLM(response={
            "alignment": 0.7,
            "missed_aspects": [],
            "scope_creep": [],
            "issues": [],
            "reasoning": "Technically correct but could be better",
        })

        verifier = LLMIntentVerifier(llm=llm)
        result = verifier.verify(request="test", response="test")

        # 0.7 is the threshold
        assert result.aligned is True

    def test_llm_failure_defaults_to_pass(self):
        llm = MockLLM(error=LLMError("Connection refused"))

        verifier = LLMIntentVerifier(llm=llm)
        result = verifier.verify(request="test", response="test")

        assert result.aligned is True
        assert result.alignment_score == 0.5
        assert len(result.issues) == 1
        assert "unavailable" in result.issues[0].lower()

    def test_invalid_json_defaults_to_pass(self):
        llm = MockLLM()
        # Override to return invalid JSON
        llm.chat_json = lambda **kwargs: "not json"

        verifier = LLMIntentVerifier(llm=llm)
        result = verifier.verify(request="test", response="test")

        assert result.aligned is True
        assert result.alignment_score == 0.5

    def test_classification_context_included(self):
        llm = MockLLM(response={
            "alignment": 0.9,
            "missed_aspects": [],
            "scope_creep": [],
            "issues": [],
            "reasoning": "ok",
        })

        verifier = LLMIntentVerifier(llm=llm)
        verifier.verify(
            request="show memory",
            response="Memory: 8GB",
            classification={"destination": "stream", "consumer": "human", "semantics": "read"},
        )

        assert "stream/human/read" in llm.last_user

    def test_prompt_includes_request_and_response(self):
        llm = MockLLM(response={
            "alignment": 0.9,
            "missed_aspects": [],
            "scope_creep": [],
            "issues": [],
            "reasoning": "ok",
        })

        verifier = LLMIntentVerifier(llm=llm)
        verifier.verify(request="hello world", response="hi there")

        assert "hello world" in llm.last_user
        assert "hi there" in llm.last_user

    def test_system_prompt_is_judge_prompt(self):
        llm = MockLLM(response={
            "alignment": 0.9,
            "missed_aspects": [],
            "scope_creep": [],
            "issues": [],
            "reasoning": "ok",
        })

        verifier = LLMIntentVerifier(llm=llm)
        verifier.verify(request="test", response="test")

        assert "INTENT JUDGE" in llm.last_system
