"""Tests for classification package — new LLMClassifier wrapper."""

from __future__ import annotations

import json

import pytest

from classification.llm_classifier import ClassificationResult, LLMClassifier
from reos.atomic_ops.models import (
    ConsumerType,
    DestinationType,
    ExecutionSemantics,
)


class MockLLM:
    """Mock LLM provider for testing."""

    def __init__(self, response: str | None = None, error: Exception | None = None):
        self.response = response
        self.error = error
        self.last_system: str = ""
        self.call_count = 0
        self.current_model = "test-model-1b"

    def chat_json(
        self, system: str = "", user: str = "", temperature: float = 0.1, top_p: float = 0.9,
        **kwargs,
    ) -> str:
        self.last_system = system
        self.call_count += 1
        if self.error:
            raise self.error
        return self.response or "{}"


class TestLLMClassifierFallback:
    """Test keyword fallback when LLM is unavailable."""

    def test_fallback_greeting(self):
        classifier = LLMClassifier(llm=None)
        result = classifier.classify("good morning")

        assert result.model == "keyword_fallback"
        assert result.classification.confident is False
        assert result.classification.domain == "conversation"

    def test_fallback_system_query(self):
        classifier = LLMClassifier(llm=None)
        result = classifier.classify("show memory usage")

        assert result.classification.destination == DestinationType.STREAM
        assert result.classification.semantics == ExecutionSemantics.READ
        assert result.classification.domain == "system"

    def test_fallback_execute(self):
        classifier = LLMClassifier(llm=None)
        result = classifier.classify("run pytest")

        assert result.classification.destination == DestinationType.PROCESS
        assert result.classification.semantics == ExecutionSemantics.EXECUTE

    def test_fallback_file_operation(self):
        classifier = LLMClassifier(llm=None)
        result = classifier.classify("save this note")

        assert result.classification.destination == DestinationType.FILE
        assert result.classification.semantics == ExecutionSemantics.EXECUTE

    def test_fallback_calendar(self):
        classifier = LLMClassifier(llm=None)
        result = classifier.classify("show my calendar schedule")

        assert result.classification.domain == "calendar"
        assert result.classification.action_hint == "view"


class TestLLMClassifierWithLLM:
    """Test LLM-based classification."""

    def test_llm_classification(self):
        llm = MockLLM(response=json.dumps({
            "destination": "stream",
            "consumer": "human",
            "semantics": "interpret",
            "confident": True,
            "reasoning": "Greeting detected",
            "domain": "conversation",
            "action_hint": None,
        }))

        classifier = LLMClassifier(llm=llm)
        result = classifier.classify("good morning")

        assert result.classification.destination == DestinationType.STREAM
        assert result.classification.consumer == ConsumerType.HUMAN
        assert result.classification.semantics == ExecutionSemantics.INTERPRET
        assert result.classification.confident is True
        assert result.classification.domain == "conversation"
        assert result.raw_response is not None

    def test_llm_failure_falls_back(self):
        llm = MockLLM(error=Exception("Connection refused"))

        classifier = LLMClassifier(llm=llm)
        result = classifier.classify("hello")

        assert result.model == "keyword_fallback"
        assert result.classification.confident is False

    def test_corrections_included_in_prompt(self):
        llm = MockLLM(response=json.dumps({
            "destination": "stream",
            "consumer": "human",
            "semantics": "read",
            "confident": True,
            "reasoning": "system query",
            "domain": "system",
            "action_hint": "view",
        }))

        corrections = [{
            "request": "check disk",
            "system_destination": "stream",
            "system_consumer": "human",
            "system_semantics": "interpret",
            "corrected_destination": "stream",
            "corrected_consumer": "human",
            "corrected_semantics": "read",
        }]

        classifier = LLMClassifier(llm=llm)
        classifier.classify("show disk usage", corrections=corrections)

        assert "PAST CORRECTIONS" in llm.last_system


class TestBuildClassificationPrompt:
    """Test prompt building."""

    def test_prompt_without_corrections(self):
        classifier = LLMClassifier(llm=None)
        prompt = classifier._build_classification_prompt()

        assert "REQUEST CLASSIFIER" in prompt
        assert "PAST CORRECTIONS" not in prompt

    def test_prompt_with_corrections(self):
        classifier = LLMClassifier(llm=None)
        corrections = [{
            "request": "test",
            "system_destination": "stream",
            "system_consumer": "human",
            "system_semantics": "interpret",
            "corrected_destination": "stream",
            "corrected_consumer": "human",
            "corrected_semantics": "read",
        }]
        prompt = classifier._build_classification_prompt(corrections=corrections)

        assert "PAST CORRECTIONS" in prompt
        assert "test" in prompt
