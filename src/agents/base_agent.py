"""Base agent abstraction — defines the contract all agents implement.

Every agent (CAIRN, ReOS, RIVA) follows the same lifecycle:
1. gather_context() — collect relevant data for this request
2. build_system_prompt() — create the system prompt with context
3. build_user_prompt() — format the user's request
4. format_response() — post-process the LLM response

The BaseAgent provides the contract. Subclasses fill in domain-specific logic.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from reos.atomic_ops.models import Classification, ExecutionSemantics
from reos.providers.base import LLMProvider


@dataclass
class AgentContext:
    """Context gathered by an agent before generating a response."""

    play_data: dict[str, Any] = field(default_factory=dict)
    calendar_events: list[dict[str, Any]] = field(default_factory=list)
    knowledge_entries: list[dict[str, Any]] = field(default_factory=list)
    system_info: dict[str, Any] = field(default_factory=dict)
    conversation_history: list[dict[str, str]] = field(default_factory=list)


@dataclass
class AgentResponse:
    """Structured response from an agent."""

    text: str
    thinking_steps: list[str] = field(default_factory=list)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    confidence: float = 1.0
    needs_approval: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


class BaseAgent(ABC):
    """Abstract base for all ReOS agents.

    Subclasses must implement:
    - agent_name: identifier
    - gather_context(): domain-specific data collection
    - build_system_prompt(): persona + context assembly
    - build_user_prompt(): request formatting
    - format_response(): post-processing
    """

    def __init__(self, llm: LLMProvider) -> None:
        self.llm = llm

    @property
    @abstractmethod
    def agent_name(self) -> str:
        """Agent identifier (e.g., 'cairn', 'reos', 'riva')."""
        ...

    @abstractmethod
    def gather_context(
        self,
        request: str,
        classification: Classification | None = None,
    ) -> AgentContext:
        """Gather domain-specific context for this request.

        Called before generating a response to collect relevant data
        from stores, APIs, and system state.
        """
        ...

    @abstractmethod
    def build_system_prompt(self, context: AgentContext) -> str:
        """Build the system prompt with agent persona and context."""
        ...

    @abstractmethod
    def build_user_prompt(
        self,
        request: str,
        classification: Classification | None = None,
    ) -> str:
        """Format the user's request for the LLM."""
        ...

    @abstractmethod
    def format_response(self, raw_response: str, context: AgentContext) -> AgentResponse:
        """Post-process the LLM response into structured output."""
        ...

    def get_temperature(self, classification: Classification | None = None) -> float:
        """Select temperature based on execution semantics.

        READ operations need precision (low temperature).
        INTERPRET operations benefit from creativity (higher temperature).
        EXECUTE operations need reliability (low temperature).
        """
        if classification is None:
            return 0.7

        match classification.semantics:
            case ExecutionSemantics.READ:
                return 0.1
            case ExecutionSemantics.INTERPRET:
                return 0.7
            case ExecutionSemantics.EXECUTE:
                return 0.2

    def respond(
        self,
        request: str,
        classification: Classification | None = None,
    ) -> AgentResponse:
        """Full response lifecycle: context → prompts → LLM → format.

        This is the main entry point. Orchestrates the agent lifecycle
        without requiring callers to manage individual steps.
        """
        context = self.gather_context(request, classification)
        system_prompt = self.build_system_prompt(context)
        user_prompt = self.build_user_prompt(request, classification)
        temperature = self.get_temperature(classification)

        raw = self.llm.chat_text(
            system=system_prompt,
            user=user_prompt,
            temperature=temperature,
        )

        return self.format_response(raw, context)
