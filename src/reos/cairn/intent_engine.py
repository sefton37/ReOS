"""CAIRN Intent Engine — Types and backward-compatible CairnIntentEngine.

This module provides:
- Intent enums (IntentCategory, IntentAction) for backward compatibility
- Intent dataclasses (ExtractedIntent, VerifiedIntent, IntentResult)
- CairnIntentEngine class (now a thin wrapper providing LLM + play_data
  and delegating response generation to cairn/response_generator.py)

The actual processing pipeline is:
- atomic_ops/classifier.py — 3x2x3 + domain + action_hint classification
- cairn/behavior_modes.py — classification → execution strategy
- cairn/response_generator.py — response generation + hallucination checking
- atomic_ops/cairn_integration.py — orchestration
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any

from reos.cairn.response_generator import ResponseGenerator
from reos.providers.base import LLMProvider


class IntentCategory(Enum):
    """Categories of user intent."""

    CALENDAR = auto()
    CONTACTS = auto()
    SYSTEM = auto()
    CODE = auto()
    PERSONAL = auto()
    TASKS = auto()
    KNOWLEDGE = auto()
    PLAY = auto()
    UNDO = auto()
    FEEDBACK = auto()
    CONVERSATION = auto()
    UNKNOWN = auto()


class IntentAction(Enum):
    """Types of actions the user might want."""

    VIEW = auto()
    SEARCH = auto()
    CREATE = auto()
    UPDATE = auto()
    DELETE = auto()
    STATUS = auto()
    UNKNOWN = auto()


@dataclass
class ExtractedIntent:
    """Result of intent extraction."""

    category: IntentCategory
    action: IntentAction
    target: str
    parameters: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    raw_input: str = ""
    reasoning: str = ""


@dataclass
class VerifiedIntent:
    """Result of intent verification."""

    intent: ExtractedIntent
    verified: bool
    tool_name: str | None
    tool_args: dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    fallback_message: str | None = None


@dataclass
class IntentResult:
    """Final result after tool execution and response generation."""

    verified_intent: VerifiedIntent
    tool_result: dict[str, Any] | None
    response: str
    thinking_steps: list[str] = field(default_factory=list)


class CairnIntentEngine:
    """Thin wrapper providing LLM, play_data, and response generation.

    This class exists for backward compatibility with agent.py which creates
    it and passes it to CairnAtomicBridge. The actual work is done by
    ResponseGenerator and the behavior mode registry.
    """

    MAX_RESPONSE_HISTORY = 5

    def __init__(
        self,
        llm: LLMProvider,
        available_tools: set[str] | None = None,
        play_data: dict[str, Any] | None = None,
    ):
        self.llm = llm
        self.available_tools = available_tools or set()
        self.play_data = play_data or {}
        self._response_gen = ResponseGenerator(llm=llm)

    # Delegate all response generation to ResponseGenerator

    def _handle_feedback(self, intent: ExtractedIntent) -> str:
        return self._response_gen.handle_feedback(intent.raw_input)

    def _handle_conversation(
        self,
        intent: ExtractedIntent,
        persona_context: str = "",
        conversation_context: str = "",
    ) -> str:
        return self._response_gen.handle_conversation(
            intent.raw_input, persona_context, conversation_context
        )

    def _verify_no_hallucination(
        self,
        response: str,
        tool_result: dict[str, Any] | None,
        intent: ExtractedIntent,
    ) -> tuple[bool, str]:
        return self._response_gen.verify_no_hallucination(
            response, tool_result, intent.category.name.lower()
        )

    def _recover_with_clarification(
        self,
        user_input: str,
        intent: ExtractedIntent,
        rejection_reason: str,
        execute_tool: Any,
    ) -> str | None:
        return self._response_gen.recover_with_clarification(
            user_input,
            intent.category.name.lower(),
            intent.action.name.lower(),
            rejection_reason,
            execute_tool,
        )

    def _ask_for_clarification(
        self,
        user_input: str,
        intent: ExtractedIntent,
        rejection_reason: str,
    ) -> str:
        return self._response_gen.ask_for_clarification(
            user_input,
            intent.category.name.lower(),
            intent.action.name.lower(),
            rejection_reason,
        )

    def _is_response_repetitive(self, response: str) -> bool:
        return self._response_gen.is_response_repetitive(response)

    def _track_response(self, response: str) -> None:
        self._response_gen.track_response(response)

    def _parse_response(self, raw: str) -> tuple[str, list[str]]:
        return self._response_gen.parse_response(raw)

    def _format_event_time(self, iso_time: str) -> str:
        return self._response_gen.format_event_time(iso_time)

    def _format_event_date(self, iso_time: str) -> str:
        return self._response_gen.format_event_date(iso_time)

    def _generate_safe_response(
        self,
        tool_result: dict[str, Any] | None,
        intent: ExtractedIntent,
    ) -> str:
        """Generate a simple, safe response that can't hallucinate."""
        if intent.category == IntentCategory.CALENDAR:
            if tool_result is None:
                return "I couldn't access your calendar right now."

            count = tool_result.get("count", 0)
            events = tool_result.get("events", [])

            if count == 0 or len(events) == 0:
                return "Your calendar is empty - no upcoming events found."

            lines = []
            if count == 1:
                lines.append("You have 1 upcoming event:\n")
            else:
                lines.append(f"You have {count} upcoming events:\n")

            for e in events[:10]:
                title = e.get("title", "Untitled")
                start = e.get("start", "")
                location = e.get("location", "")
                all_day = e.get("all_day", False)

                if all_day:
                    lines.append(f"  {self._format_event_date(start)}")
                    lines.append(f"    {title} (all day)")
                else:
                    lines.append(f"  {self._format_event_time(start)}")
                    lines.append(f"    {title}")

                if location:
                    lines.append(f"    Location: {location}")
                lines.append("")

            if count > 10:
                lines.append(f"  ... and {count - 10} more events")

            return "\n".join(lines).strip()

        if intent.category == IntentCategory.CONTACTS:
            if tool_result is None:
                return "I couldn't search your contacts right now."
            contacts = tool_result.get("contacts", [])
            if len(contacts) == 0:
                return "No contacts found matching your search."
            lines = [f"Found {len(contacts)} contact(s):"]
            for c in contacts[:5]:
                lines.append(f"- {c.get('name', 'Unknown')}")
            return "\n".join(lines)

        if intent.category == IntentCategory.SYSTEM:
            if tool_result is None:
                return "I couldn't get system information right now."
            parts = []
            if "cpu" in tool_result:
                parts.append(f"CPU: {tool_result['cpu']}")
            if "memory" in tool_result:
                parts.append(f"Memory: {tool_result['memory']}")
            return "\n".join(parts) if parts else "System information retrieved."

        return "I processed your request but couldn't format a detailed response."
