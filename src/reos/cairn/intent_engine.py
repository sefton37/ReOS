"""CAIRN Intent Engine - Multi-stage intent processing.

This module implements a structured approach to understanding user intent:

Stage 1: Intent Extraction
  - Parse user input to extract intent
  - Classify into categories: CALENDAR, SYSTEM, CODE, PERSONAL, etc.
  - Extract target, action, and any parameters

Stage 2: Intent Verification
  - Verify the intent is actionable
  - Check if we have the required capability
  - Return verified intent with confidence

Stage 3: Tool Selection (done externally)
  - Map verified intent to appropriate tools

Stage 4: Response Generation
  - Generate response STRICTLY from tool results
  - No hallucination - only use actual data
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any

from reos.providers.base import LLMProvider


class IntentCategory(Enum):
    """Categories of user intent."""
    CALENDAR = auto()      # Calendar/schedule questions
    CONTACTS = auto()      # Contact/people questions
    SYSTEM = auto()        # System/computer questions
    CODE = auto()          # Code/development questions
    PERSONAL = auto()      # Personal questions (about user)
    TASKS = auto()         # Task/todo questions
    KNOWLEDGE = auto()     # Knowledge base questions
    UNKNOWN = auto()       # Cannot determine


class IntentAction(Enum):
    """Types of actions the user might want."""
    VIEW = auto()          # View/list/show
    SEARCH = auto()        # Search/find
    CREATE = auto()        # Create/add
    UPDATE = auto()        # Update/modify
    DELETE = auto()        # Delete/remove
    STATUS = auto()        # Check status
    UNKNOWN = auto()


@dataclass
class ExtractedIntent:
    """Result of intent extraction (Stage 1)."""
    category: IntentCategory
    action: IntentAction
    target: str              # What the user is asking about
    parameters: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0  # 0-1, how confident we are
    raw_input: str = ""      # Original user input
    reasoning: str = ""      # Why we classified this way


@dataclass
class VerifiedIntent:
    """Result of intent verification (Stage 2)."""
    intent: ExtractedIntent
    verified: bool
    tool_name: str | None    # The tool to use, if verified
    tool_args: dict[str, Any] = field(default_factory=dict)
    reason: str = ""         # Why verified or not
    fallback_message: str | None = None  # Message if we can't help


@dataclass
class IntentResult:
    """Final result after tool execution and response generation."""
    verified_intent: VerifiedIntent
    tool_result: dict[str, Any] | None
    response: str
    thinking_steps: list[str] = field(default_factory=list)


# Intent category keywords for pattern matching (fast path before LLM)
INTENT_PATTERNS: dict[IntentCategory, list[str]] = {
    IntentCategory.CALENDAR: [
        "calendar", "schedule", "appointment", "meeting", "event",
        "today", "tomorrow", "this week", "next week",
        "when am i", "what's on", "what do i have",
    ],
    IntentCategory.CONTACTS: [
        "contact", "person", "people", "who is", "email address",
        "phone number", "reach out to",
    ],
    IntentCategory.SYSTEM: [
        "cpu", "memory", "ram", "disk", "storage", "process",
        "service", "package", "docker", "container", "system",
        "computer", "machine", "uptime", "running",
    ],
    IntentCategory.TASKS: [
        "todo", "task", "reminder", "due", "deadline",
        "what should i", "what do i need to",
    ],
    IntentCategory.PERSONAL: [
        "about me", "my goals", "my values", "who am i",
        "my story", "my identity", "tell me about myself",
    ],
}

# Tool mappings for each category
CATEGORY_TOOLS: dict[IntentCategory, str] = {
    IntentCategory.CALENDAR: "cairn_get_calendar",
    IntentCategory.CONTACTS: "cairn_search_contacts",
    IntentCategory.SYSTEM: "linux_system_info",
    IntentCategory.TASKS: "cairn_get_todos",
    IntentCategory.KNOWLEDGE: "cairn_list_items",
}


class CairnIntentEngine:
    """Multi-stage intent processing for CAIRN."""

    def __init__(self, llm: LLMProvider, available_tools: set[str] | None = None):
        """Initialize the intent engine.

        Args:
            llm: LLM provider for intent extraction
            available_tools: Set of available tool names (for verification)
        """
        self.llm = llm
        self.available_tools = available_tools or set()

    def process(
        self,
        user_input: str,
        *,
        execute_tool: Any | None = None,  # Callable to execute tools
        persona_context: str = "",
    ) -> IntentResult:
        """Process user input through all stages.

        Args:
            user_input: The user's message
            execute_tool: Function to call tools: (name, args) -> result
            persona_context: Context about the user (from THE_PLAY)

        Returns:
            IntentResult with the final response
        """
        import sys

        # Stage 1: Extract intent
        print(f"[INTENT] Stage 1: Extracting intent from: {user_input[:100]!r}", file=sys.stderr)
        intent = self._extract_intent(user_input)
        print(f"[INTENT] Stage 1 result: category={intent.category.name}, action={intent.action.name}, confidence={intent.confidence:.2f}", file=sys.stderr)

        # Stage 2: Verify intent
        print(f"[INTENT] Stage 2: Verifying intent", file=sys.stderr)
        verified = self._verify_intent(intent)
        print(f"[INTENT] Stage 2 result: verified={verified.verified}, tool={verified.tool_name}", file=sys.stderr)

        # Stage 3: Execute tool if verified
        tool_result = None
        if verified.verified and verified.tool_name and execute_tool:
            print(f"[INTENT] Stage 3: Executing tool {verified.tool_name} with args {verified.tool_args}", file=sys.stderr)
            try:
                tool_result = execute_tool(verified.tool_name, verified.tool_args)
                print(f"[INTENT] Stage 3 result: {json.dumps(tool_result, default=str)[:500]}", file=sys.stderr)
            except Exception as e:
                print(f"[INTENT] Stage 3 error: {e}", file=sys.stderr)
                tool_result = {"error": str(e)}

        # Stage 4: Generate response
        print(f"[INTENT] Stage 4: Generating response", file=sys.stderr)
        response, thinking = self._generate_response(
            verified_intent=verified,
            tool_result=tool_result,
            persona_context=persona_context,
        )
        print(f"[INTENT] Stage 4 response: {response[:200]}...", file=sys.stderr)

        return IntentResult(
            verified_intent=verified,
            tool_result=tool_result,
            response=response,
            thinking_steps=thinking,
        )

    def _extract_intent(self, user_input: str) -> ExtractedIntent:
        """Stage 1: Extract intent from user input."""
        user_lower = user_input.lower()

        # Fast path: pattern matching for common cases
        for category, patterns in INTENT_PATTERNS.items():
            for pattern in patterns:
                if pattern in user_lower:
                    # Determine action based on common verbs
                    action = IntentAction.VIEW  # Default
                    if any(w in user_lower for w in ["create", "add", "new", "make"]):
                        action = IntentAction.CREATE
                    elif any(w in user_lower for w in ["find", "search", "look for", "where"]):
                        action = IntentAction.SEARCH
                    elif any(w in user_lower for w in ["update", "change", "modify", "edit"]):
                        action = IntentAction.UPDATE
                    elif any(w in user_lower for w in ["delete", "remove", "cancel"]):
                        action = IntentAction.DELETE
                    elif any(w in user_lower for w in ["status", "how is", "check"]):
                        action = IntentAction.STATUS

                    return ExtractedIntent(
                        category=category,
                        action=action,
                        target=pattern,
                        confidence=0.85,  # High confidence for pattern match
                        raw_input=user_input,
                        reasoning=f"Pattern matched: '{pattern}' indicates {category.name}",
                    )

        # Slow path: Use LLM for complex cases
        return self._extract_intent_with_llm(user_input)

    def _extract_intent_with_llm(self, user_input: str) -> ExtractedIntent:
        """Use LLM to extract intent when patterns don't match."""
        system = """You are an INTENT EXTRACTOR. Analyze the user's message and extract their intent.

Return ONLY a JSON object with these fields:
{
    "category": "CALENDAR|CONTACTS|SYSTEM|CODE|TASKS|PERSONAL|KNOWLEDGE|UNKNOWN",
    "action": "VIEW|SEARCH|CREATE|UPDATE|DELETE|STATUS|UNKNOWN",
    "target": "what they're asking about (string)",
    "confidence": 0.0-1.0,
    "reasoning": "brief explanation"
}

Categories:
- CALENDAR: Questions about schedule, events, appointments, meetings
- CONTACTS: Questions about people, contacts, phone numbers, emails
- SYSTEM: Questions about computer, CPU, memory, disk, processes, services
- CODE: Questions about programming, development, code
- TASKS: Questions about todos, tasks, reminders, deadlines
- PERSONAL: Questions about the user themselves (identity, goals, values)
- KNOWLEDGE: Questions about stored knowledge, notes, projects
- UNKNOWN: Cannot determine

Actions:
- VIEW: View, list, show, tell me about
- SEARCH: Find, search, look for
- CREATE: Create, add, new, make
- UPDATE: Update, change, modify
- DELETE: Delete, remove, cancel
- STATUS: Check status, how is
- UNKNOWN: Cannot determine

Be precise. Output ONLY valid JSON."""

        user = f"USER MESSAGE: {user_input}"

        try:
            raw = self.llm.chat_json(system=system, user=user, temperature=0.1, top_p=0.9)
            data = json.loads(raw)

            category = IntentCategory[data.get("category", "UNKNOWN").upper()]
            action = IntentAction[data.get("action", "UNKNOWN").upper()]

            return ExtractedIntent(
                category=category,
                action=action,
                target=data.get("target", "unknown"),
                confidence=float(data.get("confidence", 0.5)),
                raw_input=user_input,
                reasoning=data.get("reasoning", "LLM extraction"),
            )
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            # Fallback to unknown
            return ExtractedIntent(
                category=IntentCategory.UNKNOWN,
                action=IntentAction.UNKNOWN,
                target="unknown",
                confidence=0.0,
                raw_input=user_input,
                reasoning=f"LLM extraction failed: {e}",
            )

    def _verify_intent(self, intent: ExtractedIntent) -> VerifiedIntent:
        """Stage 2: Verify the intent is actionable."""
        # Check if we have a tool for this category
        tool_name = CATEGORY_TOOLS.get(intent.category)

        # For PERSONAL category, no tool needed - answer from context
        if intent.category == IntentCategory.PERSONAL:
            return VerifiedIntent(
                intent=intent,
                verified=True,
                tool_name=None,  # No tool needed
                reason="Personal questions answered from THE_PLAY context",
            )

        # Check if the tool is available
        if tool_name and (not self.available_tools or tool_name in self.available_tools):
            # Build tool arguments based on intent
            tool_args = self._build_tool_args(intent, tool_name)

            return VerifiedIntent(
                intent=intent,
                verified=True,
                tool_name=tool_name,
                tool_args=tool_args,
                reason=f"Tool '{tool_name}' available for {intent.category.name}",
            )

        # Unknown category or tool not available
        if intent.category == IntentCategory.UNKNOWN:
            return VerifiedIntent(
                intent=intent,
                verified=False,
                tool_name=None,
                reason="Could not determine user intent",
                fallback_message="I'm not sure what you're asking. Could you rephrase that?",
            )

        return VerifiedIntent(
            intent=intent,
            verified=False,
            tool_name=None,
            reason=f"No tool available for {intent.category.name}",
            fallback_message=f"I don't have a way to help with {intent.category.name.lower()} questions right now.",
        )

    def _build_tool_args(self, intent: ExtractedIntent, tool_name: str) -> dict[str, Any]:
        """Build tool arguments based on the intent."""
        args: dict[str, Any] = {}

        # Calendar tools might need date ranges
        if tool_name == "cairn_get_calendar":
            # Default: show today and upcoming
            # Could parse "tomorrow", "next week" etc from intent
            pass

        # Contacts might need a search query
        if tool_name == "cairn_search_contacts":
            args["query"] = intent.target

        return args

    def _generate_response(
        self,
        verified_intent: VerifiedIntent,
        tool_result: dict[str, Any] | None,
        persona_context: str,
    ) -> tuple[str, list[str]]:
        """Stage 4: Generate response strictly from tool results."""

        # If not verified, return fallback
        if not verified_intent.verified:
            return verified_intent.fallback_message or "I couldn't process that request.", []

        # Build a strict prompt that prevents hallucination
        system = f"""You are CAIRN, the Attention Minder. Generate a response based STRICTLY on the data provided.

CRITICAL RULES:
1. Use ONLY the DATA PROVIDED below - do NOT make up information
2. If data shows empty results, say so clearly
3. Do NOT mention tools, APIs, or technical details
4. Be conversational but factual
5. This is a Linux desktop application - NEVER mention macOS, Windows, or other platforms

INTENT: The user asked about {verified_intent.intent.category.name.lower()} ({verified_intent.intent.action.name.lower()})
TARGET: {verified_intent.intent.target}
"""

        # Build user message with actual data
        if verified_intent.intent.category == IntentCategory.PERSONAL:
            # Personal questions - use persona context
            user = f"""USER QUESTION: {verified_intent.intent.raw_input}

YOUR KNOWLEDGE ABOUT THIS USER:
{persona_context if persona_context else "No personal information available yet."}

Generate a helpful response using ONLY the knowledge above. If no knowledge is available, politely explain that the user can fill out 'Your Story' in The Play to teach you about themselves."""

        elif tool_result:
            # Tool was called - use its results
            result_str = json.dumps(tool_result, indent=2, default=str)

            # Add formatting instructions for calendar events
            format_instructions = ""
            if verified_intent.intent.category == IntentCategory.CALENDAR:
                format_instructions = """

FORMAT INSTRUCTIONS for calendar events:
- List each event on its own line
- Use human-readable dates: "Tuesday, January 14" not "2026-01-14"
- Use human-readable times: "10:00 AM" not "10:00:00"
- Format like:
  Tuesday, January 14 at 10:00 AM
    Event Title
    Location: Place (if available)

  Wednesday, January 15 at 2:30 PM
    Another Event
"""

            user = f"""USER QUESTION: {verified_intent.intent.raw_input}

DATA FROM SYSTEM (use ONLY this data):
{result_str}
{format_instructions}
Generate a helpful response that accurately describes the data above. If the data shows empty results (count: 0, events: []), clearly tell the user there are no items."""

        else:
            # No tool result
            user = f"""USER QUESTION: {verified_intent.intent.raw_input}

No data was retrieved. Explain that you couldn't get the requested information."""

        try:
            raw = self.llm.chat_text(system=system, user=user, temperature=0.3, top_p=0.9)
            response, thinking = self._parse_response(raw)

            # Stage 5: Hallucination check (cheap local LLM verification)
            import sys
            print(f"[INTENT] Stage 5: Verifying response for hallucination", file=sys.stderr)

            is_valid, rejection_reason = self._verify_no_hallucination(
                response=response,
                tool_result=tool_result,
                intent=verified_intent.intent,
            )

            if not is_valid:
                print(f"[INTENT] Stage 5: REJECTED - {rejection_reason}", file=sys.stderr)
                # Generate a safer response
                safe_response = self._generate_safe_response(
                    tool_result=tool_result,
                    intent=verified_intent.intent,
                )
                return safe_response, thinking + [f"[Hallucination prevented: {rejection_reason}]"]

            print(f"[INTENT] Stage 5: Response verified OK", file=sys.stderr)
            return response, thinking

        except Exception as e:
            return f"I encountered an error generating a response: {e}", []

    def _verify_no_hallucination(
        self,
        response: str,
        tool_result: dict[str, Any] | None,
        intent: ExtractedIntent,
    ) -> tuple[bool, str]:
        """Verify the response doesn't contain hallucinated information.

        Uses a cheap local LLM call to check if the response is grounded in data.

        Returns:
            Tuple of (is_valid, rejection_reason)
        """
        # Quick pattern checks (no LLM needed)
        response_lower = response.lower()

        # Check for platform hallucinations
        platform_hallucinations = ["macos", "mac os", "windows", "toolbelt", "ios", "android"]
        for term in platform_hallucinations:
            if term in response_lower:
                return False, f"Response mentions wrong platform: '{term}'"

        # For empty calendar, check we're not making up events
        if tool_result and tool_result.get("count") == 0:
            # If count is 0, response shouldn't mention specific events
            event_indicators = [
                "meeting with", "appointment at", "event at", "scheduled for",
                "at 10:", "at 11:", "at 12:", "at 1:", "at 2:", "at 3:", "at 4:", "at 5:",
                "am", "pm",  # Time indicators suggesting specific events
            ]
            for indicator in event_indicators:
                if indicator in response_lower:
                    return False, f"Response mentions events but data shows count=0"

        # For empty events list, ensure we're reporting empty correctly
        if tool_result and isinstance(tool_result.get("events"), list) and len(tool_result.get("events", [])) == 0:
            # Response should indicate empty, not list fake events
            if any(word in response_lower for word in ["first event", "next meeting", "you have a"]):
                return False, "Response claims events exist but events list is empty"

        # LLM-based verification for more complex cases
        # Only do this if we have actual data to compare
        if tool_result and tool_result.get("count", 0) > 0:
            return self._llm_verify_grounding(response, tool_result)

        return True, ""

    def _llm_verify_grounding(self, response: str, tool_result: dict[str, Any]) -> tuple[bool, str]:
        """Use LLM to verify response is grounded in actual data."""
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
            is_grounded = data.get("is_grounded", True)
            reason = data.get("reason", "")
            return is_grounded, reason
        except (json.JSONDecodeError, Exception):
            # If verification fails, assume it's OK (fail open)
            return True, ""

    def _format_event_time(self, iso_time: str) -> str:
        """Format ISO time to human-readable format."""
        from datetime import datetime
        try:
            dt = datetime.fromisoformat(iso_time.replace("Z", "+00:00"))
            # Format: "Tuesday, January 14 at 10:00 AM"
            return dt.strftime("%A, %B %d at %I:%M %p").replace(" 0", " ")
        except (ValueError, AttributeError):
            return iso_time

    def _format_event_date(self, iso_time: str) -> str:
        """Format ISO time to just the date."""
        from datetime import datetime
        try:
            dt = datetime.fromisoformat(iso_time.replace("Z", "+00:00"))
            return dt.strftime("%A, %B %d")
        except (ValueError, AttributeError):
            return iso_time

    def _generate_safe_response(
        self,
        tool_result: dict[str, Any] | None,
        intent: ExtractedIntent,
    ) -> str:
        """Generate a simple, safe response that can't hallucinate."""
        # Direct template-based responses - no LLM, no hallucination possible

        if intent.category == IntentCategory.CALENDAR:
            if tool_result is None:
                return "I couldn't access your calendar right now."

            count = tool_result.get("count", 0)
            events = tool_result.get("events", [])

            if count == 0 or len(events) == 0:
                return "Your calendar is empty - no upcoming events found."

            # Format events in a human-readable way
            lines = []
            if count == 1:
                lines.append("You have 1 upcoming event:\n")
            else:
                lines.append(f"You have {count} upcoming events:\n")

            for e in events[:10]:  # Show up to 10 events
                title = e.get("title", "Untitled")
                start = e.get("start", "")
                location = e.get("location", "")
                all_day = e.get("all_day", False)

                if all_day:
                    date_str = self._format_event_date(start)
                    lines.append(f"  {date_str}")
                    lines.append(f"    {title} (all day)")
                else:
                    time_str = self._format_event_time(start)
                    lines.append(f"  {time_str}")
                    lines.append(f"    {title}")

                if location:
                    lines.append(f"    Location: {location}")
                lines.append("")  # Blank line between events

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
                name = c.get("name", "Unknown")
                lines.append(f"- {name}")
            return "\n".join(lines)

        if intent.category == IntentCategory.SYSTEM:
            if tool_result is None:
                return "I couldn't get system information right now."
            # Just dump the key facts
            parts = []
            if "cpu" in tool_result:
                parts.append(f"CPU: {tool_result['cpu']}")
            if "memory" in tool_result:
                parts.append(f"Memory: {tool_result['memory']}")
            return "\n".join(parts) if parts else "System information retrieved."

        # Generic fallback
        return "I processed your request but couldn't format a detailed response."

    def _parse_response(self, raw: str) -> tuple[str, list[str]]:
        """Parse LLM response, extracting thinking steps if present."""
        thinking_steps: list[str] = []
        answer = raw.strip()

        # Check for thinking tags
        thinking_match = re.search(r"<think(?:ing)?>(.*?)</think(?:ing)?>", raw, re.DOTALL | re.IGNORECASE)
        if thinking_match:
            thinking_content = thinking_match.group(1).strip()
            thinking_steps = [s.strip() for s in thinking_content.split("\n") if s.strip()]

        # Check for answer tags
        answer_match = re.search(r"<answer>(.*?)</answer>", raw, re.DOTALL | re.IGNORECASE)
        if answer_match:
            answer = answer_match.group(1).strip()
        else:
            # Remove thinking tags from answer
            answer = re.sub(r"<think(?:ing)?>.*?</think(?:ing)?>", "", answer, flags=re.DOTALL | re.IGNORECASE).strip()

        return answer, thinking_steps
