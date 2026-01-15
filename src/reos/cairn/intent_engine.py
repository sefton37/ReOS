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
    PLAY = auto()          # The Play hierarchy (Acts, Scenes, Beats)
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
    IntentCategory.PLAY: [
        # Acts
        "act", "acts", "create act", "new act", "delete act", "remove act",
        "list acts", "show acts", "my acts", "all acts",
        # Scenes
        "scene", "scenes", "create scene", "new scene", "delete scene",
        "list scenes", "show scenes",
        # Beats
        "beat", "beats", "create beat", "new beat", "delete beat",
        "list beats", "show beats", "move beat", "move to",
        # Organization
        "should be in", "belongs to", "put in", "organize", "reorganize",
        "not your story", "wrong act", "different act",
        # The Play
        "the play", "my play",
    ],
}

# Tool mappings for each category (default tool - may be refined in _verify_intent)
CATEGORY_TOOLS: dict[IntentCategory, str] = {
    IntentCategory.CALENDAR: "cairn_get_calendar",
    IntentCategory.CONTACTS: "cairn_search_contacts",
    IntentCategory.SYSTEM: "linux_system_info",
    IntentCategory.TASKS: "cairn_get_todos",
    IntentCategory.KNOWLEDGE: "cairn_list_items",
    IntentCategory.PLAY: "cairn_list_acts",  # Default, refined based on action/target
}


class CairnIntentEngine:
    """Multi-stage intent processing for CAIRN."""

    def __init__(
        self,
        llm: LLMProvider,
        available_tools: set[str] | None = None,
        play_data: dict[str, Any] | None = None,
    ):
        """Initialize the intent engine.

        Args:
            llm: LLM provider for intent extraction
            available_tools: Set of available tool names (for verification)
            play_data: Dictionary with 'acts' and 'beats' lists for context
        """
        self.llm = llm
        self.available_tools = available_tools or set()
        self.play_data = play_data or {}

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
        all_tool_results = []  # Track all tool calls for recovery
        if verified.verified and verified.tool_name and execute_tool:
            print(f"[INTENT] Stage 3: Executing tool {verified.tool_name} with args {verified.tool_args}", file=sys.stderr)
            try:
                tool_result = execute_tool(verified.tool_name, verified.tool_args)
                all_tool_results.append({"tool": verified.tool_name, "result": tool_result})
                print(f"[INTENT] Stage 3 result: {json.dumps(tool_result, default=str)[:500]}", file=sys.stderr)

                # Stage 3.5: Recovery - if tool failed or returned error, try to recover
                if tool_result and tool_result.get("error"):
                    print(f"[INTENT] Stage 3.5: Tool returned error, attempting recovery", file=sys.stderr)
                    recovery_result = self._attempt_recovery(
                        user_input=user_input,
                        intent=intent,
                        failed_tool=verified.tool_name,
                        error=tool_result.get("error"),
                        execute_tool=execute_tool,
                    )
                    if recovery_result:
                        tool_result = recovery_result
                        all_tool_results.append({"tool": "recovery", "result": recovery_result})

            except Exception as e:
                print(f"[INTENT] Stage 3 error: {e}", file=sys.stderr)
                tool_result = {"error": str(e)}

        # Stage 4: Generate response
        print(f"[INTENT] Stage 4: Generating response", file=sys.stderr)
        response, thinking = self._generate_response(
            verified_intent=verified,
            tool_result=tool_result,
            persona_context=persona_context,
            user_input=user_input,
            execute_tool=execute_tool,
        )
        print(f"[INTENT] Stage 4 response: {response[:200]}...", file=sys.stderr)

        return IntentResult(
            verified_intent=verified,
            tool_result=tool_result,
            response=response,
            thinking_steps=thinking,
        )

    def _attempt_recovery(
        self,
        user_input: str,
        intent: ExtractedIntent,
        failed_tool: str,
        error: str,
        execute_tool: Any,
    ) -> dict[str, Any] | None:
        """Attempt to recover from a tool failure.

        Instead of giving up, try alternative strategies:
        1. For beat operations: search for the beat first
        2. For missing data: gather more context
        """
        import sys

        # For beat move failures, try to find the beat first
        if failed_tool == "cairn_move_beat_to_act" and "not found" in error.lower():
            print(f"[INTENT] Recovery: Beat not found, searching...", file=sys.stderr)
            try:
                # List all beats to find the one the user mentioned
                beats_result = execute_tool("cairn_list_beats", {})
                if beats_result and not beats_result.get("error"):
                    return {
                        "recovery": True,
                        "action": "search_beats",
                        "beats": beats_result,
                        "original_error": error,
                    }
            except Exception as e:
                print(f"[INTENT] Recovery failed: {e}", file=sys.stderr)

        return None

    def _extract_intent(self, user_input: str) -> ExtractedIntent:
        """Stage 1: Extract intent from user input.

        For PLAY operations, also extracts entity names (beat_name, act_name, etc.)
        in the same pass to avoid redundant extraction later.
        """
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
                    elif any(w in user_lower for w in ["update", "change", "modify", "edit", "move", "assign", "put"]):
                        action = IntentAction.UPDATE
                    elif any(w in user_lower for w in ["delete", "remove", "cancel"]):
                        action = IntentAction.DELETE
                    elif any(w in user_lower for w in ["status", "how is", "check"]):
                        action = IntentAction.STATUS

                    # For PLAY category with UPDATE action, extract entity names NOW
                    # This avoids redundant extraction in _build_tool_args
                    parameters: dict[str, Any] = {}
                    if category == IntentCategory.PLAY and action == IntentAction.UPDATE:
                        parameters = self._extract_beat_move_args(user_input)

                    return ExtractedIntent(
                        category=category,
                        action=action,
                        target=pattern,
                        parameters=parameters,
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

        # For PLAY category, choose tool based on action and target
        if intent.category == IntentCategory.PLAY:
            tool_name = self._select_play_tool(intent)

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
        """Build tool arguments based on the intent.

        Uses intent.parameters if already extracted, otherwise extracts from raw_input.
        This avoids redundant extraction passes.
        """
        # Start with any parameters already extracted during intent parsing
        args: dict[str, Any] = dict(intent.parameters)

        # Calendar tools might need date ranges
        if tool_name == "cairn_get_calendar":
            pass

        # Contacts might need a search query
        if tool_name == "cairn_search_contacts":
            if "query" not in args:
                args["query"] = intent.target

        # Beat organization - use already-extracted params or extract now
        if tool_name == "cairn_move_beat_to_act":
            if "beat_name" not in args or "target_act_name" not in args:
                args.update(self._extract_beat_move_args(intent.raw_input))

        # Play CRUD tools
        if tool_name == "cairn_list_beats":
            # Check if filtering by act
            if intent.target and intent.target != "beats":
                args["act_name"] = intent.target

        if tool_name == "cairn_list_scenes":
            # Extract act name for filtering
            act_name = self._extract_act_name(intent.raw_input)
            if act_name:
                args["act_name"] = act_name

        if tool_name == "cairn_create_act":
            # Extract title for new act
            title = self._extract_entity_title(intent.raw_input, "act")
            if title:
                args["title"] = title

        if tool_name == "cairn_update_act":
            # Extract act name and new title
            act_name = self._extract_act_name(intent.raw_input)
            new_title = self._extract_new_title(intent.raw_input)
            if act_name:
                args["act_name"] = act_name
            if new_title:
                args["new_title"] = new_title

        if tool_name == "cairn_delete_act":
            # Extract act name to delete
            act_name = self._extract_act_name(intent.raw_input)
            if act_name:
                args["act_name"] = act_name

        if tool_name == "cairn_create_scene":
            # Extract act name and scene title
            act_name = self._extract_act_name(intent.raw_input)
            title = self._extract_entity_title(intent.raw_input, "scene")
            if act_name:
                args["act_name"] = act_name
            if title:
                args["title"] = title

        if tool_name == "cairn_update_scene":
            # Extract scene name and new title
            scene_name = self._extract_scene_name(intent.raw_input)
            new_title = self._extract_new_title(intent.raw_input)
            if scene_name:
                args["scene_name"] = scene_name
            if new_title:
                args["new_title"] = new_title

        if tool_name == "cairn_delete_scene":
            # Extract scene name
            scene_name = self._extract_scene_name(intent.raw_input)
            if scene_name:
                args["scene_name"] = scene_name

        if tool_name == "cairn_create_beat":
            # Extract beat details
            beat_args = self._extract_beat_create_args(intent.raw_input)
            args.update(beat_args)

        if tool_name == "cairn_update_beat":
            # Extract beat name and updates
            beat_args = self._extract_beat_update_args(intent.raw_input)
            args.update(beat_args)

        if tool_name == "cairn_delete_beat":
            # Extract beat name
            beat_name = self._extract_beat_name(intent.raw_input)
            if beat_name:
                args["beat_name"] = beat_name

        return args

    def _extract_act_name(self, user_input: str) -> str | None:
        """Extract an act name from user input."""
        user_lower = user_input.lower()

        # Pattern: "the X act" or "X act"
        match = re.search(r"(?:the\s+)?([A-Za-z][A-Za-z\s]+?)\s+act", user_input, re.IGNORECASE)
        if match:
            return match.group(1).strip()

        # Pattern: "act called/named X"
        match = re.search(r"act\s+(?:called|named)\s+[\"']?([^\"']+)[\"']?", user_lower)
        if match:
            return match.group(1).strip()

        # Pattern: "in X" (act context)
        if "act" in user_lower:
            match = re.search(r"(?:in|from|to)\s+(?:the\s+)?([A-Za-z][A-Za-z\s]+?)(?:\s+act|\s*$|,|\.)", user_input, re.IGNORECASE)
            if match:
                return match.group(1).strip()

        return None

    def _extract_scene_name(self, user_input: str) -> str | None:
        """Extract a scene name from user input."""
        # Pattern: "the X scene" or "X scene"
        match = re.search(r"(?:the\s+)?([A-Za-z][A-Za-z\s]+?)\s+scene", user_input, re.IGNORECASE)
        if match:
            return match.group(1).strip()

        # Pattern: "scene called/named X"
        match = re.search(r"scene\s+(?:called|named)\s+[\"']?([^\"']+)[\"']?", user_input.lower())
        if match:
            return match.group(1).strip()

        return None

    def _extract_beat_name(self, user_input: str) -> str | None:
        """Extract a beat name from user input."""
        # Pattern: "the X beat" or "X beat"
        match = re.search(r"(?:the\s+)?([A-Za-z][A-Za-z\s]+?)\s+(?:beat|event)", user_input, re.IGNORECASE)
        if match:
            return match.group(1).strip()

        # Pattern: "beat called/named X"
        match = re.search(r"(?:beat|event)\s+(?:called|named)\s+[\"']?([^\"']+)[\"']?", user_input.lower())
        if match:
            return match.group(1).strip()

        return None

    def _extract_entity_title(self, user_input: str, entity_type: str) -> str | None:
        """Extract a title for creating a new entity (act, scene, beat)."""
        user_lower = user_input.lower()

        # Pattern: "create/add/new X called/named Y"
        match = re.search(
            rf"(?:create|add|new|make)\s+(?:a\s+)?(?:new\s+)?{entity_type}\s+(?:called|named)\s+[\"']?([^\"']+)[\"']?",
            user_lower
        )
        if match:
            return match.group(1).strip()

        # Pattern: "create/add/new X Y" (title after entity type)
        match = re.search(
            rf"(?:create|add|new|make)\s+(?:a\s+)?(?:new\s+)?{entity_type}\s+([A-Za-z][A-Za-z\s]+?)(?:\s+in|\s+for|$|,|\.)",
            user_input,
            re.IGNORECASE
        )
        if match:
            title = match.group(1).strip()
            # Filter out common words
            if title.lower() not in ("called", "named", "in", "for", "the"):
                return title

        # Pattern: "X as a new act/scene/beat"
        match = re.search(
            rf"([A-Za-z][A-Za-z\s]+?)\s+(?:as\s+)?(?:a\s+)?(?:new\s+)?{entity_type}",
            user_input,
            re.IGNORECASE
        )
        if match:
            return match.group(1).strip()

        return None

    def _extract_new_title(self, user_input: str) -> str | None:
        """Extract a new title for updating an entity."""
        user_lower = user_input.lower()

        # Pattern: "rename to X" or "change to X"
        match = re.search(r"(?:rename|change|update)\s+(?:it\s+)?to\s+[\"']?([^\"']+)[\"']?", user_lower)
        if match:
            return match.group(1).strip()

        # Pattern: "new name X" or "new title X"
        match = re.search(r"new\s+(?:name|title)\s+[\"']?([^\"']+)[\"']?", user_lower)
        if match:
            return match.group(1).strip()

        return None

    def _extract_beat_create_args(self, user_input: str) -> dict[str, Any]:
        """Extract arguments for creating a beat."""
        args: dict[str, Any] = {}

        # Extract title
        title = self._extract_entity_title(user_input, "beat")
        if title:
            args["title"] = title

        # Extract act name if specified
        act_name = self._extract_act_name(user_input)
        if act_name:
            args["act_name"] = act_name

        # Extract scene name if specified
        scene_name = self._extract_scene_name(user_input)
        if scene_name:
            args["scene_name"] = scene_name

        # Extract stage if specified
        user_lower = user_input.lower()
        if "planning" in user_lower:
            args["stage"] = "planning"
        elif "in progress" in user_lower or "in_progress" in user_lower:
            args["stage"] = "in_progress"
        elif "awaiting" in user_lower or "waiting" in user_lower:
            args["stage"] = "awaiting_data"
        elif "complete" in user_lower or "done" in user_lower:
            args["stage"] = "complete"

        return args

    def _extract_beat_update_args(self, user_input: str) -> dict[str, Any]:
        """Extract arguments for updating a beat."""
        args: dict[str, Any] = {}

        # Extract beat name
        beat_name = self._extract_beat_name(user_input)
        if beat_name:
            args["beat_name"] = beat_name

        # Extract new title if renaming
        new_title = self._extract_new_title(user_input)
        if new_title:
            args["new_title"] = new_title

        # Extract new stage if changing status
        user_lower = user_input.lower()
        if any(w in user_lower for w in ["mark as", "set to", "change to", "move to"]):
            if "planning" in user_lower:
                args["stage"] = "planning"
            elif "in progress" in user_lower or "in_progress" in user_lower or "started" in user_lower:
                args["stage"] = "in_progress"
            elif "awaiting" in user_lower or "waiting" in user_lower or "blocked" in user_lower:
                args["stage"] = "awaiting_data"
            elif "complete" in user_lower or "done" in user_lower or "finished" in user_lower:
                args["stage"] = "complete"

        return args

    def _extract_beat_move_args(self, user_input: str) -> dict[str, Any]:
        """Extract beat_name and target_act_name from user input.

        Uses LLM-based extraction with Play context as the primary method.
        Falls back to regex only if LLM extraction fails.
        """
        import sys

        # PRIMARY: LLM-based extraction using Play context
        # This is the preferred method because it understands context
        if self.play_data and (self.play_data.get("acts") or self.play_data.get("all_beats")):
            print(f"[INTENT] Using LLM extraction with Play context", file=sys.stderr)
            llm_args = self._llm_extract_beat_move_args(user_input)
            if llm_args.get("beat_name") and llm_args.get("target_act_name"):
                print(f"[INTENT] LLM extracted: beat={llm_args.get('beat_name')!r}, act={llm_args.get('target_act_name')!r}", file=sys.stderr)
                return llm_args
            print(f"[INTENT] LLM extraction incomplete, trying regex fallback", file=sys.stderr)

        # FALLBACK: Regex-based extraction (only if LLM fails or no play_data)
        return self._regex_extract_beat_move_args(user_input)

    def _llm_extract_beat_move_args(self, user_input: str) -> dict[str, Any]:
        """Use LLM with Play context to extract beat and act names.

        The LLM knows about all existing acts and beats, so it can match
        user's natural language ("Career act") to actual entities ("Career").
        """
        # Build context about available acts and beats
        acts_list = self.play_data.get("acts", [])
        beats_list = self.play_data.get("all_beats", [])

        act_names = [a["title"] for a in acts_list]
        beat_info = [f"'{b['title']}' (in {b['act_title']} act)" for b in beats_list[:20]]  # Limit for context

        system = f"""You are an ENTITY EXTRACTOR. Extract the beat name and target act from the user's request.

AVAILABLE ACTS in The Play:
{json.dumps(act_names, indent=2)}

EXISTING BEATS:
{chr(10).join(beat_info) if beat_info else "No beats yet"}

The user wants to move a beat to an act. Extract:
1. beat_name: The EXACT title of the beat (match from EXISTING BEATS list if possible)
2. target_act_name: The EXACT title of the target act (match from AVAILABLE ACTS list)

Return ONLY a JSON object:
{{"beat_name": "exact beat title", "target_act_name": "exact act title"}}

IMPORTANT:
- Match to existing entities using fuzzy matching
- "Career act" → "Career"
- "Job Search Activities" → find closest match in beats list
- If you can't find an exact match, use the closest match
- Never include "act" or "beat" as part of the name"""

        user = f"USER REQUEST: {user_input}"

        try:
            raw = self.llm.chat_json(system=system, user=user, temperature=0.1, top_p=0.9)
            data = json.loads(raw)
            return {
                "beat_name": data.get("beat_name", "").strip(),
                "target_act_name": data.get("target_act_name", "").strip(),
            }
        except (json.JSONDecodeError, Exception) as e:
            import sys
            print(f"[INTENT] LLM extraction failed: {e}", file=sys.stderr)
            return {}

    def _regex_extract_beat_move_args(self, user_input: str) -> dict[str, Any]:
        """Regex-based extraction as fallback when LLM fails."""
        user_lower = user_input.lower()
        args: dict[str, Any] = {}

        # Pattern 1: "X should be in/for the Y act"
        match = re.search(
            r"(.+?)\s+(?:beat|event)?\s*(?:should be|belongs to|goes in|should go)\s+(?:in|to|for|under)?\s*(?:the\s+)?(.+?)\s*(?:act)?(?:,|\.|$|not)",
            user_lower
        )
        if match:
            args["beat_name"] = match.group(1).strip()
            args["target_act_name"] = match.group(2).strip()
            return args

        # Pattern 2: "move X to Y"
        match = re.search(
            r"(?:move|put|assign|organize)\s+(?:the\s+)?(.+?)\s+(?:beat|event)?\s*(?:to|in|into|under)\s+(?:the\s+)?(.+?)\s*(?:act)?(?:,|\.|$)",
            user_lower
        )
        if match:
            args["beat_name"] = match.group(1).strip()
            args["target_act_name"] = match.group(2).strip()
            return args

        # Pattern 3: "X beat/event for Y act"
        match = re.search(
            r"(.+?)\s+(?:beat|event)\s+(?:for|to)\s+(?:the\s+)?(.+?)\s*(?:act)?(?:,|\.|$)",
            user_lower
        )
        if match:
            args["beat_name"] = match.group(1).strip()
            args["target_act_name"] = match.group(2).strip()
            return args

        # Pattern 4: Extract capitalized phrases as last resort
        words = user_input.split()
        beat_candidates = []
        act_candidates = []

        i = 0
        while i < len(words):
            if words[i].lower() in ("the", "move", "put"):
                i += 1
                continue

            if words[i] and words[i][0].isupper():
                phrase = [words[i]]
                j = i + 1
                while j < len(words) and words[j] and words[j][0].isupper():
                    phrase.append(words[j])
                    j += 1
                if phrase:
                    full_phrase = " ".join(phrase)
                    if j < len(words) and words[j].lower() in ("act", "act,", "act."):
                        act_candidates.append(full_phrase)
                    elif j < len(words) and words[j].lower() in ("beat", "event", "beat,", "event,"):
                        beat_candidates.append(full_phrase)
                    else:
                        if not beat_candidates:
                            beat_candidates.append(full_phrase)
                        else:
                            act_candidates.append(full_phrase)
                i = j
            else:
                i += 1

        if beat_candidates:
            args["beat_name"] = beat_candidates[0]
        if act_candidates:
            args["target_act_name"] = act_candidates[0]

        return args

    def _select_play_tool(self, intent: ExtractedIntent) -> str:
        """Select the appropriate Play tool based on action and target entity.

        Analyzes the user's input to determine:
        1. The entity type: act, scene, or beat
        2. The action: create, update, delete, view/list, move

        Returns:
            Tool name (e.g., cairn_create_act, cairn_delete_beat)
        """
        user_lower = intent.raw_input.lower()

        # Determine entity type
        entity = None
        if any(w in user_lower for w in ["act ", "acts", " act", "act,"]):
            entity = "act"
        elif any(w in user_lower for w in ["scene ", "scenes", " scene", "scene,"]):
            entity = "scene"
        elif any(w in user_lower for w in ["beat ", "beats", " beat", "beat,", "event "]):
            entity = "beat"

        # Determine action from intent
        action = intent.action

        # Override action based on keywords for beat movement
        # Check for move patterns FIRST, regardless of detected entity
        # "move X to Y" pattern - if "move" is near the start, it's a move operation
        if user_lower.startswith("move ") or " move " in user_lower:
            return "cairn_move_beat_to_act"

        move_patterns = [
            "should be in", "should be for", "belongs to", "tied to",
            "put in", "wrong act", "not your story", "different act",
            "reorganize", "assign to", "assign my", "link to", "associate with",
        ]
        if any(w in user_lower for w in move_patterns):
            # This is a beat move operation
            return "cairn_move_beat_to_act"

        # Map action and entity to tool
        tool_map = {
            # Acts
            ("act", IntentAction.VIEW): "cairn_list_acts",
            ("act", IntentAction.SEARCH): "cairn_list_acts",
            ("act", IntentAction.CREATE): "cairn_create_act",
            ("act", IntentAction.UPDATE): "cairn_update_act",
            ("act", IntentAction.DELETE): "cairn_delete_act",
            # Scenes
            ("scene", IntentAction.VIEW): "cairn_list_scenes",
            ("scene", IntentAction.SEARCH): "cairn_list_scenes",
            ("scene", IntentAction.CREATE): "cairn_create_scene",
            ("scene", IntentAction.UPDATE): "cairn_update_scene",
            ("scene", IntentAction.DELETE): "cairn_delete_scene",
            # Beats
            ("beat", IntentAction.VIEW): "cairn_list_beats",
            ("beat", IntentAction.SEARCH): "cairn_list_beats",
            ("beat", IntentAction.CREATE): "cairn_create_beat",
            ("beat", IntentAction.UPDATE): "cairn_update_beat",
            ("beat", IntentAction.DELETE): "cairn_delete_beat",
        }

        # Look up the tool
        if entity and (entity, action) in tool_map:
            return tool_map[(entity, action)]

        # Default fallback based on entity
        if entity == "act":
            return "cairn_list_acts"
        elif entity == "scene":
            return "cairn_list_scenes"
        elif entity == "beat":
            return "cairn_list_beats"

        # Ultimate fallback - list acts to show The Play structure
        return "cairn_list_acts"

    def _generate_response(
        self,
        verified_intent: VerifiedIntent,
        tool_result: dict[str, Any] | None,
        persona_context: str,
        user_input: str = "",
        execute_tool: Any | None = None,
    ) -> tuple[str, list[str]]:
        """Stage 4: Generate response strictly from tool results.

        If hallucination is detected, this method will:
        1. Try to gather more data (e.g., search for beats)
        2. Ask for clarification if needed
        3. Never just give up silently
        """
        import sys

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
            print(f"[INTENT] Stage 5: Verifying response for hallucination", file=sys.stderr)

            is_valid, rejection_reason = self._verify_no_hallucination(
                response=response,
                tool_result=tool_result,
                intent=verified_intent.intent,
            )

            if not is_valid:
                print(f"[INTENT] Stage 5: REJECTED - {rejection_reason}", file=sys.stderr)

                # Stage 5.5: Recovery - try to get more data instead of giving up
                if execute_tool and verified_intent.intent.category == IntentCategory.PLAY:
                    print(f"[INTENT] Stage 5.5: Attempting recovery for PLAY category", file=sys.stderr)
                    recovery_response = self._recover_with_clarification(
                        user_input=user_input or verified_intent.intent.raw_input,
                        intent=verified_intent.intent,
                        rejection_reason=rejection_reason,
                        execute_tool=execute_tool,
                    )
                    if recovery_response:
                        return recovery_response, thinking + [f"[Recovery: {rejection_reason}]"]

                # Fallback: ask for clarification instead of generic message
                clarification = self._ask_for_clarification(
                    user_input=user_input or verified_intent.intent.raw_input,
                    intent=verified_intent.intent,
                    rejection_reason=rejection_reason,
                )
                return clarification, thinking + [f"[Clarification needed: {rejection_reason}]"]

            print(f"[INTENT] Stage 5: Response verified OK", file=sys.stderr)
            return response, thinking

        except Exception as e:
            return f"I encountered an error generating a response: {e}", []

    def _recover_with_clarification(
        self,
        user_input: str,
        intent: ExtractedIntent,
        rejection_reason: str,
        execute_tool: Any,
    ) -> str | None:
        """Try to recover by gathering more data."""
        import sys

        # For beat operations, try to list all beats to help the user
        if "beat" in user_input.lower() or intent.action == IntentAction.UPDATE:
            try:
                print(f"[INTENT] Recovery: Searching for beats...", file=sys.stderr)
                beats_result = execute_tool("cairn_list_beats", {})
                if beats_result and not beats_result.get("error"):
                    beats = beats_result.get("beats", [])
                    if beats:
                        beat_names = [b.get("title", "Unknown") for b in beats[:10]]
                        return (
                            f"I couldn't find the exact beat you mentioned. "
                            f"Here are your current beats:\n\n"
                            f"• " + "\n• ".join(beat_names) +
                            f"\n\nWhich one would you like to move? "
                            f"Please use the exact name from the list above."
                        )
            except Exception as e:
                print(f"[INTENT] Recovery search failed: {e}", file=sys.stderr)

        return None

    def _ask_for_clarification(
        self,
        user_input: str,
        intent: ExtractedIntent,
        rejection_reason: str,
    ) -> str:
        """Generate a clarification request instead of giving up."""
        # Extract what the user was trying to do
        action = intent.action.name.lower()
        category = intent.category.name.lower()

        if "not in the provided data" in rejection_reason.lower():
            # User mentioned something we don't have
            return (
                f"I want to help you {action} that, but I couldn't find it in my data. "
                f"Could you please check the exact name? You can ask me to 'list beats' "
                f"or 'list acts' to see what's available."
            )

        # Generic clarification
        return (
            f"I'm not sure I understood correctly. You wanted to {action} something "
            f"related to {category}. Could you rephrase that or provide more details?"
        )

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
