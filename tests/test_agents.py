"""Tests for agents package — BaseAgent, CAIRNAgent, ReOSAgent."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from agents.base_agent import AgentContext, AgentResponse, BaseAgent
from agents.cairn_agent import CAIRNAgent
from agents.reos_agent import ReOSAgent
from reos.atomic_ops.models import (
    Classification,
    ConsumerType,
    DestinationType,
    ExecutionSemantics,
)


class MockLLMProvider:
    """Mock LLM for testing agents."""

    provider_type = "mock"

    def __init__(self, response: str = "Mock response"):
        self._response = response

    def chat_text(self, *, system: str, user: str, **kwargs) -> str:
        return self._response

    def chat_json(self, *, system: str, user: str, **kwargs) -> str:
        return '{"result": "ok"}'

    def list_models(self):
        return []

    def check_health(self):
        return MagicMock(reachable=True)


class TestBaseAgent:
    """Test BaseAgent ABC and common methods."""

    def test_get_temperature_read(self):
        """READ operations get low temperature."""
        llm = MockLLMProvider()
        agent = CAIRNAgent(llm=llm, use_play_db=False)

        cls = Classification(
            destination=DestinationType.STREAM,
            consumer=ConsumerType.HUMAN,
            semantics=ExecutionSemantics.READ,
        )
        assert agent.get_temperature(cls) == 0.1

    def test_get_temperature_interpret(self):
        """INTERPRET operations get moderate temperature."""
        llm = MockLLMProvider()
        agent = CAIRNAgent(llm=llm, use_play_db=False)

        cls = Classification(
            destination=DestinationType.STREAM,
            consumer=ConsumerType.HUMAN,
            semantics=ExecutionSemantics.INTERPRET,
        )
        assert agent.get_temperature(cls) == 0.7

    def test_get_temperature_execute(self):
        """EXECUTE operations get low temperature."""
        llm = MockLLMProvider()
        agent = CAIRNAgent(llm=llm, use_play_db=False)

        cls = Classification(
            destination=DestinationType.PROCESS,
            consumer=ConsumerType.MACHINE,
            semantics=ExecutionSemantics.EXECUTE,
        )
        assert agent.get_temperature(cls) == 0.2

    def test_get_temperature_none(self):
        """No classification gets default temperature."""
        llm = MockLLMProvider()
        agent = CAIRNAgent(llm=llm, use_play_db=False)
        assert agent.get_temperature(None) == 0.7


class TestCAIRNAgent:
    """Test CAIRNAgent implementation."""

    def test_agent_name(self):
        agent = CAIRNAgent(llm=MockLLMProvider(), use_play_db=False)
        assert agent.agent_name == "cairn"

    def test_respond_returns_agent_response(self):
        agent = CAIRNAgent(llm=MockLLMProvider("Hello! Good morning."), use_play_db=False)

        result = agent.respond("good morning")

        assert isinstance(result, AgentResponse)
        assert result.text == "Hello! Good morning."

    def test_gather_context_without_stores(self):
        agent = CAIRNAgent(llm=MockLLMProvider(), use_play_db=False, cairn_store=None)

        context = agent.gather_context("hello")

        assert isinstance(context, AgentContext)
        assert context.play_data == {}

    def test_build_system_prompt_includes_persona(self):
        agent = CAIRNAgent(llm=MockLLMProvider(), use_play_db=False)
        context = AgentContext()

        prompt = agent.build_system_prompt(context)

        assert "CAIRN" in prompt
        assert "attention minder" in prompt

    def test_build_system_prompt_includes_play_data(self):
        agent = CAIRNAgent(llm=MockLLMProvider(), use_play_db=False)
        context = AgentContext(
            play_data={
                "acts": [
                    {
                        "title": "Career",
                        "scenes": [
                            {"title": "Job Search", "stage": "in_progress"},
                        ],
                    }
                ]
            }
        )

        prompt = agent.build_system_prompt(context)

        assert "Career" in prompt
        assert "Job Search" in prompt
        assert "in_progress" in prompt

    def test_format_response(self):
        agent = CAIRNAgent(llm=MockLLMProvider(), use_play_db=False)
        context = AgentContext()

        result = agent.format_response("  Hello world  ", context)

        assert result.text == "Hello world"
        assert result.confidence == 1.0


class TestReOSAgent:
    """Test ReOSAgent implementation."""

    def test_agent_name(self):
        agent = ReOSAgent(llm=MockLLMProvider())
        assert agent.agent_name == "reos"

    def test_respond_returns_agent_response(self):
        agent = ReOSAgent(llm=MockLLMProvider("Here's how to check memory: `free -h`"))

        result = agent.respond("show memory usage")

        assert isinstance(result, AgentResponse)
        assert "memory" in result.text.lower() or "free" in result.text.lower()

    def test_gather_context_includes_system_info(self):
        agent = ReOSAgent(llm=MockLLMProvider())

        context = agent.gather_context("show disk usage")

        assert "kernel" in context.system_info
        assert "os" in context.system_info

    def test_build_user_prompt_execute(self):
        agent = ReOSAgent(llm=MockLLMProvider())
        cls = Classification(
            destination=DestinationType.PROCESS,
            consumer=ConsumerType.MACHINE,
            semantics=ExecutionSemantics.EXECUTE,
        )

        prompt = agent.build_user_prompt("install htop", cls)

        assert "install htop" in prompt
        assert "CAUTION" in prompt

    def test_build_user_prompt_read(self):
        agent = ReOSAgent(llm=MockLLMProvider())
        cls = Classification(
            destination=DestinationType.STREAM,
            consumer=ConsumerType.HUMAN,
            semantics=ExecutionSemantics.READ,
        )

        prompt = agent.build_user_prompt("show disk usage", cls)

        assert prompt == "show disk usage"

    def test_format_response_flags_commands(self):
        agent = ReOSAgent(llm=MockLLMProvider())
        context = AgentContext()

        result = agent.format_response("Run: ```sudo apt install htop```", context)

        assert result.needs_approval is True

    def test_format_response_no_approval_for_info(self):
        agent = ReOSAgent(llm=MockLLMProvider())
        context = AgentContext()

        result = agent.format_response("Your system is running Linux.", context)

        assert result.needs_approval is False
