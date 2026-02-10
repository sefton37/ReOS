"""CAIRN Response Generator — response generation, hallucination checking, formatting.

Generates responses from tool results, detects hallucination, handles
conversation and feedback, and tracks response history for repetition detection.

Used by cairn_integration.py after behavior modes select tools and extract args.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


class ResponseGenerator:
    """Generates responses from tool results and handles conversational interactions.

    Provides:
    - LLM-based response generation from tool output
    - Hallucination detection (pattern-based + LLM verification)
    - Feedback/conversation handling
    - Repetition detection via response history
    """

    MAX_RESPONSE_HISTORY = 5

    def __init__(self, llm: Any = None):
        """Initialize response generator.

        Args:
            llm: LLM provider with chat_text() and chat_json() methods.
        """
        self.llm = llm
        self._response_history: list[str] = []

    # =========================================================================
    # Feedback handling
    # =========================================================================

    def handle_feedback(self, user_input: str) -> str:
        """Handle meta-feedback about CAIRN's responses."""
        user_lower = user_input.lower()

        if any(
            p in user_lower
            for p in [
                "repeating",
                "same thing",
                "same answer",
                "already said",
                "you just said",
            ]
        ):
            return (
                "You're right, I apologize for repeating myself. "
                "Let me try a different approach. What would you like to know or do?"
            )

        if any(
            p in user_lower
            for p in [
                "not what i meant",
                "not what i asked",
                "misunderstood",
                "wrong",
                "incorrect",
                "bad assumption",
            ]
        ):
            return (
                "I apologize for the misunderstanding. "
                "Could you rephrase what you're looking for? "
                "I want to make sure I help you correctly this time."
            )

        if any(p in user_lower for p in ["not helpful", "confusing", "makes no sense"]):
            return (
                "I'm sorry my response wasn't helpful. "
                "Let me try again - what specifically would you like me to help with?"
            )

        if any(p in user_lower for p in ["helpful", "good", "great", "thanks", "thank you"]):
            return "I'm glad I could help! Is there anything else you'd like to know?"

        return "Thank you for the feedback. I'll try to do better. How can I help you?"

    # =========================================================================
    # Conversation handling
    # =========================================================================

    def handle_conversation(
        self,
        user_input: str,
        persona_context: str = "",
        conversation_context: str = "",
    ) -> str:
        """Handle greetings, small talk, acknowledgments."""
        if not self.llm:
            return "Hello! How can I help you today?"

        conversation_section = ""
        if conversation_context:
            conversation_section = f"\nRECENT CONVERSATION:\n{conversation_context}\n"

        persona_section = ""
        if persona_context:
            persona_section = f"\nABOUT THE USER:\n{persona_context}\n"

        system = (
            "You are CAIRN, a friendly local AI assistant. "
            "The user is making casual conversation — a greeting, acknowledgment, "
            "or social nicety. Respond warmly and briefly (1-2 sentences). "
            "You can offer to help but don't be pushy. "
            "Never mention tools, APIs, or technical internals."
            f"{persona_section}{conversation_section}"
        )

        try:
            raw = self.llm.chat_text(system=system, user=user_input, temperature=0.7, top_p=0.9)
            response, _ = self.parse_response(raw)
            if response:
                self.track_response(response)
                return response
        except Exception as e:
            logger.warning("Conversation LLM call failed: %s", e)

        return "Hello! How can I help you today?"

    # =========================================================================
    # Response generation from tool results
    # =========================================================================

    def generate_from_tool_result(
        self,
        user_input: str,
        tool_result: dict[str, Any],
        system_prompt: str = "",
        conversation_context: str = "",
    ) -> str:
        """Generate a response from tool results using the LLM.

        Args:
            user_input: Original user question.
            tool_result: Result dict from tool execution.
            system_prompt: System prompt template from behavior mode.
            conversation_context: Recent conversation for continuity.

        Returns:
            Generated response string.
        """
        if not self.llm:
            return json.dumps(tool_result, indent=2, default=str)

        conversation_section = ""
        if conversation_context:
            conversation_section = f"\nRECENT CONVERSATION:\n{conversation_context}\n"

        system = system_prompt or (
            "You are CAIRN, the Attention Minder. "
            "Generate a response based STRICTLY on the data provided.\n"
            "Do NOT make up information. Do NOT mention tools or APIs.\n"
            "This is a Linux desktop application."
        )
        system += conversation_section

        result_str = json.dumps(tool_result, indent=2, default=str)
        user = (
            f"USER QUESTION: {user_input}\n\n"
            f"DATA FROM SYSTEM (use ONLY this data):\n{result_str}\n\n"
            "Generate a helpful response that accurately describes the data above."
        )

        try:
            raw = self.llm.chat_text(system=system, user=user, temperature=0.3, top_p=0.9)
            response, _ = self.parse_response(raw)
            return response
        except Exception as e:
            return f"I encountered an error generating a response: {e}"

    def generate_personal_response(
        self,
        user_input: str,
        persona_context: str,
        system_prompt: str = "",
    ) -> str:
        """Generate a response for personal questions using persona context."""
        if not self.llm:
            return "I don't have information about you yet."

        system = system_prompt or (
            "You are CAIRN, the Attention Minder. "
            "Answer using ONLY the knowledge provided about the user."
        )
        ctx = persona_context or "No personal information available yet."
        user = (
            f"USER QUESTION: {user_input}\n\n"
            f"YOUR KNOWLEDGE ABOUT THIS USER:\n"
            f"{ctx}\n\n"
            "Generate a helpful response using ONLY the knowledge above."
        )

        try:
            raw = self.llm.chat_text(system=system, user=user, temperature=0.3, top_p=0.9)
            response, _ = self.parse_response(raw)
            self.track_response(response)
            return response
        except Exception as e:
            return f"I encountered an error: {e}"

    # =========================================================================
    # Hallucination detection
    # =========================================================================

    def verify_no_hallucination(
        self,
        response: str,
        tool_result: dict[str, Any] | None,
        domain: str = "",
    ) -> tuple[bool, str]:
        """Verify the response doesn't contain hallucinated information.

        Returns:
            Tuple of (is_valid, rejection_reason).
        """
        response_lower = response.lower()

        # Platform hallucinations
        for term in ["macos", "mac os", "windows", "toolbelt", "ios", "android"]:
            if term in response_lower:
                return False, f"Response mentions wrong platform: '{term}'"

        # Empty calendar check
        if tool_result and tool_result.get("count") == 0:
            event_indicators = [
                "meeting with",
                "appointment at",
                "event at",
                "scheduled for",
                "at 10:",
                "at 11:",
                "at 12:",
                "at 1:",
                "at 2:",
                "at 3:",
                "at 4:",
                "at 5:",
                "am",
                "pm",
            ]
            for indicator in event_indicators:
                if indicator in response_lower:
                    return False, "Response mentions events but data shows count=0"

        # Empty events list check
        if (
            tool_result
            and isinstance(tool_result.get("events"), list)
            and len(tool_result.get("events", [])) == 0
        ):
            if any(w in response_lower for w in ["first event", "next meeting", "you have a"]):
                return False, "Response claims events exist but events list is empty"

        # LLM verification for complex cases
        if tool_result and tool_result.get("count", 0) > 0:
            return self._llm_verify_grounding(response, tool_result)

        return True, ""

    def _llm_verify_grounding(self, response: str, tool_result: dict[str, Any]) -> tuple[bool, str]:
        """Use LLM to verify response is grounded in actual data."""
        if not self.llm:
            return True, ""

        system = """You are a FACT CHECKER. Check if the RESPONSE accurately reflects the DATA.

Return ONLY a JSON object:
{
    "is_grounded": true/false,
    "reason": "brief explanation if false, empty if true"
}

Check for:
1. Does the response mention facts NOT in the data?
2. Does the response contradict the data?
3. Does the response add fictional details?

Be strict. If the response adds ANY information not in the data, mark it as not grounded."""

        user = f"""DATA:
{json.dumps(tool_result, indent=2, default=str)}

RESPONSE:
{response}

Is this response grounded in the data?"""

        try:
            raw = self.llm.chat_json(system=system, user=user, temperature=0.1, top_p=0.9)
            data = json.loads(raw)
            return data.get("is_grounded", True), data.get("reason", "")
        except (json.JSONDecodeError, Exception):
            return True, ""

    # =========================================================================
    # Recovery and clarification
    # =========================================================================

    def recover_with_clarification(
        self,
        user_input: str,
        domain: str,
        action: str,
        rejection_reason: str,
        execute_tool: Any,
    ) -> str | None:
        """Try to recover by gathering more data."""
        if "beat" in user_input.lower() or action == "update":
            try:
                beats_result = execute_tool("cairn_list_beats", {})
                if beats_result and not beats_result.get("error"):
                    beats = beats_result.get("beats", [])
                    if beats:
                        beat_names = [b.get("title", "Unknown") for b in beats[:10]]
                        return (
                            "I couldn't find the exact beat you mentioned. "
                            "Here are your current beats:\n\n"
                            "• "
                            + "\n• ".join(beat_names)
                            + "\n\nWhich one would you like to move? "
                            "Please use the exact name from the list above."
                        )
            except Exception as e:
                logger.warning("Recovery search failed: %s", e)
        return None

    def ask_for_clarification(
        self,
        user_input: str,
        domain: str,
        action: str,
        rejection_reason: str,
    ) -> str:
        """Generate a clarification request."""
        if "not in the provided data" in rejection_reason.lower():
            return (
                f"I want to help you {action} that, but I couldn't find it in my data. "
                f"Could you please check the exact name? You can ask me to 'list beats' "
                f"or 'list acts' to see what's available."
            )

        return (
            f"I'm not sure I understood correctly. You wanted to {action} something "
            f"related to {domain}. Could you rephrase that or provide more details?"
        )

    # =========================================================================
    # Response utilities
    # =========================================================================

    def is_response_repetitive(self, response: str) -> bool:
        """Check if a response is too similar to recent responses."""
        if not self._response_history:
            return False

        response_normalized = response.lower().strip()
        for past_response in self._response_history:
            past_normalized = past_response.lower().strip()
            if response_normalized == past_normalized:
                return True

            response_words = set(response_normalized.split())
            past_words = set(past_normalized.split())
            if len(response_words) > 5 and len(past_words) > 5:
                intersection = len(response_words & past_words)
                union = len(response_words | past_words)
                if union > 0 and intersection / union > 0.8:
                    return True

        return False

    def track_response(self, response: str) -> None:
        """Track a response for repetition detection."""
        self._response_history.append(response)
        if len(self._response_history) > self.MAX_RESPONSE_HISTORY:
            self._response_history.pop(0)

    def parse_response(self, raw: str) -> tuple[str, list[str]]:
        """Parse LLM response, extracting thinking steps if present."""
        thinking_steps: list[str] = []
        answer = raw.strip()

        thinking_match = re.search(
            r"<think(?:ing)?>(.*?)</think(?:ing)?>", raw, re.DOTALL | re.IGNORECASE
        )
        if thinking_match:
            thinking_content = thinking_match.group(1).strip()
            thinking_steps = [s.strip() for s in thinking_content.split("\n") if s.strip()]

        answer_match = re.search(r"<answer>(.*?)</answer>", raw, re.DOTALL | re.IGNORECASE)
        if answer_match:
            answer = answer_match.group(1).strip()
        else:
            answer = re.sub(
                r"<think(?:ing)?>.*?</think(?:ing)?>", "", answer, flags=re.DOTALL | re.IGNORECASE
            ).strip()

        return answer, thinking_steps

    def format_event_time(self, iso_time: str) -> str:
        """Format ISO time to human-readable format."""
        try:
            dt = datetime.fromisoformat(iso_time.replace("Z", "+00:00"))
            return dt.strftime("%A, %B %d at %I:%M %p").replace(" 0", " ")
        except (ValueError, AttributeError):
            return iso_time

    def format_event_date(self, iso_time: str) -> str:
        """Format ISO time to just the date."""
        try:
            dt = datetime.fromisoformat(iso_time.replace("Z", "+00:00"))
            return dt.strftime("%A, %B %d")
        except (ValueError, AttributeError):
            return iso_time
