"""Tests for routing package — RequestRouter."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from agents.base_agent import AgentContext, AgentResponse, BaseAgent
from classification.llm_classifier import LLMClassifier
from reos.atomic_ops.models import (
    Classification,
    ConsumerType,
    DestinationType,
    ExecutionSemantics,
)
from routing.router import RequestRouter, RoutingResult


class MockAgent(BaseAgent):
    """Mock agent for testing routing."""

    def __init__(self, name: str, response_text: str = "Mock response"):
        self._name = name
        self._response_text = response_text
        self.last_request: str | None = None
        # Don't call super().__init__ — we don't need a real LLM
        self.llm = MagicMock()

    @property
    def agent_name(self) -> str:
        return self._name

    def gather_context(self, request, classification=None):
        return AgentContext()

    def build_system_prompt(self, context):
        return "mock"

    def build_user_prompt(self, request, classification=None):
        return request

    def format_response(self, raw_response, context):
        return AgentResponse(text=raw_response)

    def respond(self, request, classification=None):
        self.last_request = request
        return AgentResponse(text=self._response_text)


class MockLLM:
    """Mock LLM for classifier."""

    def __init__(self, response: dict):
        self._response = response

    def chat_json(self, **kwargs) -> str:
        return json.dumps(self._response)


class TestRequestRouter:
    """Test request routing."""

    def _make_router(self, domain: str, semantics: str = "interpret"):
        """Create a router with a mock classifier that returns a fixed classification."""
        llm = MockLLM({
            "destination": "stream",
            "consumer": "human",
            "semantics": semantics,
            "confident": True,
            "domain": domain,
            "action_hint": None,
        })
        classifier = LLMClassifier(llm=llm)
        cairn = MockAgent("cairn", "CAIRN response")
        reos = MockAgent("reos", "ReOS response")

        router = RequestRouter(classifier=classifier, agents={"cairn": cairn, "reos": reos})
        return router, cairn, reos

    def test_routes_conversation_to_cairn(self):
        router, cairn, reos = self._make_router("conversation")

        result = router.handle("good morning")

        assert result.agent_name == "cairn"
        assert result.response.text == "CAIRN response"
        assert cairn.last_request == "good morning"

    def test_routes_calendar_to_cairn(self):
        router, cairn, _ = self._make_router("calendar")

        result = router.handle("what's on my calendar?")

        assert result.agent_name == "cairn"

    def test_routes_system_to_reos(self):
        router, _, reos = self._make_router("system")

        result = router.handle("show memory usage")

        assert result.agent_name == "reos"
        assert result.response.text == "ReOS response"

    def test_routes_unknown_execute_to_reos(self):
        router, _, reos = self._make_router(None, semantics="execute")

        result = router.handle("do something")

        assert result.agent_name == "reos"

    def test_routes_unknown_interpret_to_cairn(self):
        router, cairn, _ = self._make_router(None, semantics="interpret")

        result = router.handle("hmm")

        assert result.agent_name == "cairn"

    def test_no_agents_returns_empty_response(self):
        classifier = LLMClassifier(llm=None)
        router = RequestRouter(classifier=classifier, agents={})

        result = router.handle("hello")

        assert result.agent_name == "none"
        assert result.response.confidence == 0.0

    def test_register_agent(self):
        classifier = LLMClassifier(llm=None)
        router = RequestRouter(classifier=classifier)

        mock = MockAgent("cairn")
        router.register_agent("cairn", mock)

        result = router.handle("hello")
        assert result.agent_name == "cairn"

    def test_routing_result_includes_classification(self):
        router, _, _ = self._make_router("system")

        result = router.handle("show cpu")

        assert isinstance(result, RoutingResult)
        assert result.classification is not None
        assert result.classification.classification.domain == "system"
