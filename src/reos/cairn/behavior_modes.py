"""Behavior Mode Registry — maps (destination, consumer, semantics, domain) to execution strategy.

Each atomic classification combo + domain maps to a BehaviorMode that defines
the full execution strategy: tool selection, argument extraction, system prompt
template, and verification requirements.

This replaces the 240+ regex patterns in intent_engine.py with a single lookup
table driven by the LLM-produced classification.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from reos.atomic_ops.models import Classification, ExecutionSemantics

logger = logging.getLogger(__name__)


@dataclass
class BehaviorModeContext:
    """Context passed to tool selectors and arg extractors."""

    user_input: str
    classification: Classification
    play_data: dict[str, Any] = field(default_factory=dict)
    persona_context: str = ""
    conversation_context: str = ""
    llm: Any = None  # LLM provider for dynamic selection
    execute_tool: Any = None  # Tool executor for recovery


# Type aliases for selector/extractor callables
ToolSelector = Callable[[BehaviorModeContext], str | None]
ArgExtractor = Callable[[BehaviorModeContext], dict[str, Any]]


def _static_tool(tool_name: str) -> ToolSelector:
    """Create a tool selector that always returns the same tool."""

    def selector(ctx: BehaviorModeContext) -> str | None:
        return tool_name

    return selector


def _no_tool(ctx: BehaviorModeContext) -> str | None:
    """Tool selector for modes that don't need a tool."""
    return None


def _no_args(ctx: BehaviorModeContext) -> dict[str, Any]:
    """Arg extractor that returns empty args."""
    return {}


def _contacts_args(ctx: BehaviorModeContext) -> dict[str, Any]:
    """Extract search query for contacts."""
    return {"query": ctx.user_input}


def _play_tool_selector(ctx: BehaviorModeContext) -> str | None:
    """Select Play tool based on action_hint and user input."""
    action = ctx.classification.action_hint
    user_lower = ctx.user_input.lower()

    # Determine entity type
    entity = None
    if any(w in user_lower for w in ["act ", "acts", " act", "act,"]):
        entity = "act"
    elif any(w in user_lower for w in ["scene ", "scenes", " scene", "scene,"]):
        entity = "scene"
    elif any(w in user_lower for w in ["beat ", "beats", " beat", "beat,", "event "]):
        entity = "beat"

    # Move operations (beat or scene)
    move_patterns = [
        "should be in",
        "should be for",
        "belongs to",
        "tied to",
        "put in",
        "wrong act",
        "not your story",
        "different act",
        "reorganize",
        "assign to",
        "assign my",
        "link to",
        "associate with",
    ]
    if user_lower.startswith("move ") or " move " in user_lower:
        if entity == "scene":
            return "cairn_update_scene"
        return "cairn_move_beat_to_act"
    if any(p in user_lower for p in move_patterns):
        return "cairn_move_beat_to_act"

    # Map action + entity to tool
    tool_map = {
        ("act", "view"): "cairn_list_acts",
        ("act", "search"): "cairn_list_acts",
        ("act", "create"): "cairn_create_act",
        ("act", "update"): "cairn_update_act",
        ("act", "delete"): "cairn_delete_act",
        ("scene", "view"): "cairn_list_scenes",
        ("scene", "search"): "cairn_list_scenes",
        ("scene", "create"): "cairn_create_scene",
        ("scene", "update"): "cairn_update_scene",
        ("scene", "delete"): "cairn_delete_scene",
        ("beat", "view"): "cairn_list_beats",
        ("beat", "search"): "cairn_list_beats",
        ("beat", "create"): "cairn_create_beat",
        ("beat", "update"): "cairn_update_beat",
        ("beat", "delete"): "cairn_delete_beat",
    }

    if entity and action and (entity, action) in tool_map:
        return tool_map[(entity, action)]

    # Fallback by entity
    if entity == "act":
        return "cairn_list_acts"
    elif entity == "scene":
        return "cairn_list_scenes"
    elif entity == "beat":
        return "cairn_list_beats"

    return "cairn_list_acts"


def _play_arg_extractor(ctx: BehaviorModeContext) -> dict[str, Any]:
    """Extract args for Play tools using LLM when available."""
    tool = _play_tool_selector(ctx)
    args: dict[str, Any] = {}

    if tool == "cairn_move_beat_to_act":
        args = _llm_extract_beat_move_args(ctx)
    elif tool == "cairn_update_scene":
        args = _llm_extract_scene_move_args(ctx)
    elif tool == "cairn_search_contacts":
        args["query"] = ctx.user_input
    elif tool in ("cairn_list_beats", "cairn_list_scenes"):
        # Try to extract act_name for filtering
        act_name = _llm_extract_entity_name(ctx, "act")
        if act_name:
            args["act_name"] = act_name

    return args


def _llm_extract_beat_move_args(ctx: BehaviorModeContext) -> dict[str, Any]:
    """Use LLM with Play context to extract beat and act names for moves."""
    if not ctx.llm or not ctx.play_data:
        return {}

    acts_list = ctx.play_data.get("acts", [])
    beats_list = ctx.play_data.get("all_beats", [])

    act_names = [a["title"] for a in acts_list]
    beat_info = [f"'{b['title']}' (in {b['act_title']} act)" for b in beats_list[:20]]

    system = f"""You are an ENTITY EXTRACTOR. Extract the beat name \
and target act from the user's request.

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
- If you can't find an exact match, use the closest match
- Never include "act" or "beat" as part of the name"""

    user = f"USER REQUEST: {ctx.user_input}"

    try:
        raw = ctx.llm.chat_json(system=system, user=user, temperature=0.1, top_p=0.9)
        data = json.loads(raw)
        return {
            "beat_name": data.get("beat_name", "").strip(),
            "target_act_name": data.get("target_act_name", "").strip(),
        }
    except (json.JSONDecodeError, Exception) as e:
        logger.warning("LLM beat extraction failed: %s", e)
        return {}


def _llm_extract_scene_move_args(ctx: BehaviorModeContext) -> dict[str, Any]:
    """Use LLM with Play context to extract scene move arguments."""
    if not ctx.llm or not ctx.play_data:
        return {}

    acts_list = ctx.play_data.get("acts", [])
    scenes_list = ctx.play_data.get("all_scenes", [])

    act_names = [a["title"] for a in acts_list]
    scene_info = [
        f"'{s['title']}' (in {s.get('act_title', 'unknown')} act)" for s in scenes_list[:30]
    ]

    system = f"""You are an ENTITY EXTRACTOR. Extract the scene name, \
source act, and target act from the user's move request.

AVAILABLE ACTS in The Play:
{json.dumps(act_names, indent=2)}

EXISTING SCENES:
{chr(10).join(scene_info) if scene_info else "No scenes yet"}

The user wants to move a scene to a different act. Extract:
1. scene_name: The title of the scene being moved
2. act_name: The current act containing the scene (may be implicit)
3. new_act_name: The target act to move to

Return ONLY a JSON object:
{{"scene_name": "exact scene title",
  "act_name": "source act title or null",
  "new_act_name": "target act title"}}

IMPORTANT:
- Match to existing entities using fuzzy matching
- Never include "act" or "scene" as part of the name itself"""

    user = f"USER REQUEST: {ctx.user_input}"

    try:
        raw = ctx.llm.chat_json(system=system, user=user, temperature=0.1, top_p=0.9)
        data = json.loads(raw)
        result = {
            "scene_name": data.get("scene_name", "").strip() if data.get("scene_name") else None,
            "new_act_name": data.get("new_act_name", "").strip()
            if data.get("new_act_name")
            else None,
        }
        if data.get("act_name"):
            result["act_name"] = data.get("act_name", "").strip()
        return result
    except (json.JSONDecodeError, Exception) as e:
        logger.warning("LLM scene move extraction failed: %s", e)
        return {}


def _llm_extract_entity_name(ctx: BehaviorModeContext, entity_type: str) -> str | None:
    """Use simple keyword extraction to get an entity name."""
    import re

    user_input = ctx.user_input

    if entity_type == "act":
        match = re.search(r"(?:the\s+)?([A-Za-z][A-Za-z\s]+?)\s+act", user_input, re.IGNORECASE)
        if match:
            return match.group(1).strip()
        match = re.search(
            r"(?:in|from|to)\s+(?:the\s+)?([A-Za-z][A-Za-z\s]+?)(?:\s+act|\s*$|,|\.)",
            user_input,
            re.IGNORECASE,
        )
        if match:
            return match.group(1).strip()
    return None


@dataclass
class BehaviorMode:
    """Defines the execution strategy for a classification combo."""

    name: str
    needs_tool: bool
    tool_selector: ToolSelector = _no_tool
    arg_extractor: ArgExtractor = _no_args
    system_prompt_template: str = ""
    needs_hallucination_check: bool = True
    verification_mode: str = "FAST"  # FAST or STANDARD


class BehaviorModeRegistry:
    """Registry that maps (destination, consumer, semantics, domain) to BehaviorMode."""

    def __init__(self) -> None:
        self._modes: dict[tuple[str, str, str, str], BehaviorMode] = {}
        self._domain_modes: dict[str, BehaviorMode] = {}

    def register(
        self,
        destination: str,
        consumer: str,
        semantics: str,
        domain: str,
        mode: BehaviorMode,
    ) -> None:
        """Register a behavior mode for a specific classification combo."""
        key = (destination, consumer, semantics, domain)
        self._modes[key] = mode

    def register_domain(self, domain: str, mode: BehaviorMode) -> None:
        """Register a default behavior mode for a domain (any classification combo)."""
        self._domain_modes[domain] = mode

    def get_mode(self, classification: Classification) -> BehaviorMode:
        """Look up behavior mode for a classification.

        Lookup order:
        1. Exact match: (destination, consumer, semantics, domain)
        2. Domain default: domain only
        3. Semantics-based fallback: read → query, interpret → conversation, execute → mutation
        """
        if classification.domain:
            # Try exact match
            key = (
                classification.destination.value,
                classification.consumer.value,
                classification.semantics.value,
                classification.domain,
            )
            if key in self._modes:
                return self._modes[key]

            # Try domain default
            if classification.domain in self._domain_modes:
                return self._domain_modes[classification.domain]

        # Semantics-based fallback
        return self._fallback_mode(classification)

    def _fallback_mode(self, classification: Classification) -> BehaviorMode:
        """Create a fallback mode based on semantics."""
        if classification.semantics == ExecutionSemantics.INTERPRET:
            return CONVERSATION_MODE
        elif classification.semantics == ExecutionSemantics.READ:
            return BehaviorMode(
                name="generic_query",
                needs_tool=False,
                system_prompt_template=(
                    "You are CAIRN, a friendly local AI assistant. "
                    "The user is asking a question. Answer helpfully and briefly."
                ),
                needs_hallucination_check=False,
                verification_mode="FAST",
            )
        else:  # EXECUTE
            return BehaviorMode(
                name="generic_mutation",
                needs_tool=True,
                system_prompt_template=(
                    "You are CAIRN, a friendly local AI assistant. "
                    "The user wants to perform an action. Confirm what you'll do."
                ),
                needs_hallucination_check=True,
                verification_mode="STANDARD",
            )


# =============================================================================
# Pre-defined behavior modes
# =============================================================================

CONVERSATION_MODE = BehaviorMode(
    name="conversation",
    needs_tool=False,
    system_prompt_template=(
        "You are CAIRN, a friendly local AI assistant. "
        "The user is making casual conversation — a greeting, acknowledgment, "
        "or social nicety. Respond warmly and briefly (1-2 sentences). "
        "You can offer to help but don't be pushy. "
        "Never mention tools, APIs, or technical internals."
    ),
    needs_hallucination_check=False,
    verification_mode="FAST",
)

PERSONAL_QUERY_MODE = BehaviorMode(
    name="personal_query",
    needs_tool=False,
    system_prompt_template=(
        "You are CAIRN, the Attention Minder. "
        "Answer the user's personal question using ONLY the knowledge provided about them. "
        "If no knowledge is available, explain they can fill out 'Your Story' in The Play."
    ),
    needs_hallucination_check=False,
    verification_mode="FAST",
)

FEEDBACK_MODE = BehaviorMode(
    name="feedback",
    needs_tool=False,
    system_prompt_template="",  # Handled by dedicated _handle_feedback logic
    needs_hallucination_check=False,
    verification_mode="FAST",
)

CALENDAR_QUERY_MODE = BehaviorMode(
    name="calendar_query",
    needs_tool=True,
    tool_selector=_static_tool("cairn_get_calendar"),
    arg_extractor=_no_args,
    system_prompt_template=(
        "You are CAIRN, the Attention Minder. "
        "Respond based STRICTLY on the data provided.\n"
        "CRITICAL RULES:\n"
        "1. Use ONLY the DATA PROVIDED - do NOT make up information\n"
        "2. If data shows empty results, say so clearly\n"
        "3. Do NOT mention tools, APIs, or technical details\n"
        "4. This is a Linux desktop application\n"
        "FORMAT: Use human-readable dates ('Tuesday, January 14' not '2026-01-14') "
        "and times ('10:00 AM' not '10:00:00')."
    ),
    needs_hallucination_check=True,
    verification_mode="FAST",
)

CONTACTS_QUERY_MODE = BehaviorMode(
    name="contacts_query",
    needs_tool=True,
    tool_selector=_static_tool("cairn_search_contacts"),
    arg_extractor=_contacts_args,
    system_prompt_template=(
        "You are CAIRN, the Attention Minder. " "Respond based STRICTLY on the data provided."
    ),
    needs_hallucination_check=True,
    verification_mode="FAST",
)

SYSTEM_QUERY_MODE = BehaviorMode(
    name="system_query",
    needs_tool=True,
    tool_selector=_static_tool("linux_system_info"),
    arg_extractor=_no_args,
    system_prompt_template=(
        "You are CAIRN, the Attention Minder. "
        "Respond based STRICTLY on the data provided.\n"
        "This is a Linux desktop application - NEVER mention macOS, Windows, or other platforms."
    ),
    needs_hallucination_check=True,
    verification_mode="FAST",
)

TASKS_QUERY_MODE = BehaviorMode(
    name="tasks_query",
    needs_tool=True,
    tool_selector=_static_tool("cairn_get_todos"),
    arg_extractor=_no_args,
    system_prompt_template=(
        "You are CAIRN, the Attention Minder. " "Respond based STRICTLY on the data provided."
    ),
    needs_hallucination_check=True,
    verification_mode="FAST",
)

KNOWLEDGE_QUERY_MODE = BehaviorMode(
    name="knowledge_query",
    needs_tool=True,
    tool_selector=_static_tool("cairn_list_items"),
    arg_extractor=_no_args,
    system_prompt_template=(
        "You are CAIRN, the Attention Minder. " "Respond based STRICTLY on the data provided."
    ),
    needs_hallucination_check=True,
    verification_mode="FAST",
)

PLAY_QUERY_MODE = BehaviorMode(
    name="play_query",
    needs_tool=True,
    tool_selector=_play_tool_selector,
    arg_extractor=_play_arg_extractor,
    system_prompt_template=(
        "You are CAIRN, the Attention Minder. "
        "Respond based STRICTLY on the data provided.\n"
        "Present The Play structure clearly - Acts are life narratives, Scenes are tasks/events."
    ),
    needs_hallucination_check=True,
    verification_mode="FAST",
)

PLAY_MUTATION_MODE = BehaviorMode(
    name="play_mutation",
    needs_tool=True,
    tool_selector=_play_tool_selector,
    arg_extractor=_play_arg_extractor,
    system_prompt_template=(
        "You are CAIRN, the Attention Minder. "
        "Respond based STRICTLY on the data provided.\n"
        "Confirm the mutation result to the user."
    ),
    needs_hallucination_check=True,
    verification_mode="STANDARD",
)

UNDO_MODE = BehaviorMode(
    name="undo",
    needs_tool=True,
    tool_selector=_static_tool("cairn_undo_last"),
    arg_extractor=_no_args,
    system_prompt_template=(
        "You are CAIRN, the Attention Minder. Report the undo result to the user."
    ),
    needs_hallucination_check=False,
    verification_mode="STANDARD",
)

SYSTEM_EXECUTE_MODE = BehaviorMode(
    name="system_execute",
    needs_tool=True,
    tool_selector=_static_tool("linux_run_command"),
    arg_extractor=_no_args,
    system_prompt_template=("You are CAIRN, the Attention Minder. Report the command result."),
    needs_hallucination_check=True,
    verification_mode="STANDARD",
)


def create_default_registry() -> BehaviorModeRegistry:
    """Create a registry with all known behavior modes registered."""
    reg = BehaviorModeRegistry()

    # Conversation (greetings, small talk)
    reg.register("stream", "human", "interpret", "conversation", CONVERSATION_MODE)

    # Personal queries
    reg.register("stream", "human", "interpret", "personal", PERSONAL_QUERY_MODE)
    reg.register("stream", "human", "read", "personal", PERSONAL_QUERY_MODE)

    # Feedback
    reg.register("stream", "human", "interpret", "feedback", FEEDBACK_MODE)

    # Calendar
    reg.register("stream", "human", "read", "calendar", CALENDAR_QUERY_MODE)
    reg.register("stream", "human", "interpret", "calendar", CALENDAR_QUERY_MODE)

    # Contacts
    reg.register("stream", "human", "read", "contacts", CONTACTS_QUERY_MODE)

    # System
    reg.register("stream", "human", "read", "system", SYSTEM_QUERY_MODE)
    reg.register("process", "machine", "execute", "system", SYSTEM_EXECUTE_MODE)

    # Tasks
    reg.register("stream", "human", "read", "tasks", TASKS_QUERY_MODE)
    reg.register("file", "human", "read", "tasks", TASKS_QUERY_MODE)

    # Knowledge
    reg.register("file", "human", "read", "knowledge", KNOWLEDGE_QUERY_MODE)
    reg.register("stream", "human", "read", "knowledge", KNOWLEDGE_QUERY_MODE)

    # Play — queries
    reg.register("stream", "human", "read", "play", PLAY_QUERY_MODE)
    reg.register("file", "human", "read", "play", PLAY_QUERY_MODE)

    # Play — mutations
    reg.register("file", "human", "execute", "play", PLAY_MUTATION_MODE)
    reg.register("stream", "human", "execute", "play", PLAY_MUTATION_MODE)

    # Undo
    reg.register("file", "human", "execute", "undo", UNDO_MODE)
    reg.register("stream", "human", "execute", "undo", UNDO_MODE)
    reg.register("stream", "human", "interpret", "undo", UNDO_MODE)

    # Domain-level defaults (catch-all for unregistered combos within a domain)
    reg.register_domain("conversation", CONVERSATION_MODE)
    reg.register_domain("personal", PERSONAL_QUERY_MODE)
    reg.register_domain("feedback", FEEDBACK_MODE)
    reg.register_domain("calendar", CALENDAR_QUERY_MODE)
    reg.register_domain("contacts", CONTACTS_QUERY_MODE)
    reg.register_domain("system", SYSTEM_QUERY_MODE)
    reg.register_domain("tasks", TASKS_QUERY_MODE)
    reg.register_domain("knowledge", KNOWLEDGE_QUERY_MODE)
    reg.register_domain("play", PLAY_QUERY_MODE)
    reg.register_domain("undo", UNDO_MODE)

    return reg
