"""LLM-native classification for atomic operations.

Classifies user requests into the 3x2x3 taxonomy using the same LLM
already loaded for CAIRN/ReOS. Falls back to keyword heuristics when
the LLM is unavailable.

Taxonomy:
- Destination: stream | file | process
- Consumer: human | machine
- Semantics: read | interpret | execute
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from .models import (
    Classification,
    ConsumerType,
    DestinationType,
    ExecutionSemantics,
)

logger = logging.getLogger(__name__)

CLASSIFICATION_SYSTEM_PROMPT = """You are a REQUEST CLASSIFIER for a local AI assistant.

Classify the user's request into five dimensions:

1. **destination** — Where does the output go?
   - "stream": ephemeral display (conversations, answers, greetings, status info)
   - "file": persistent storage (save, create, update notes/scenes/documents)
   - "process": spawns/controls a system process (run, start, stop, install, kill)

2. **consumer** — Who consumes the result?
   - "human": a person reads or interacts with it
   - "machine": another program processes it (JSON output, test runners, CI)

3. **semantics** — What action does it take?
   - "read": retrieve or display existing data without side effects
   - "interpret": analyze, explain, summarize, or converse (including greetings and small talk)
   - "execute": perform a side-effecting action (create, delete, run, install)

4. **domain** — What subject area does this relate to?
   - "calendar": schedule, events, appointments, meetings
   - "contacts": people, email addresses, phone numbers
   - "system": CPU, memory, disk, processes, packages, services
   - "play": acts, scenes, beats (life organization hierarchy)
   - "tasks": todos, reminders, deadlines
   - "knowledge": stored notes, knowledge base
   - "personal": questions about the user (identity, goals, values, preferences)
   - "conversation": greetings, small talk, acknowledgments, social niceties
   - "feedback": meta-commentary about the assistant's responses or behavior
   - "undo": reverting or undoing a previous action
   - null: cannot determine

5. **action_hint** — What specific action does the user want?
   - "view": view, list, show, display
   - "search": find, search, look for
   - "create": create, add, new, make
   - "update": update, change, modify, move, rename
   - "delete": delete, remove, cancel
   - "status": check status
   - null: not applicable (e.g., greetings) or cannot determine

CRITICAL RULES:
- Greetings ("good morning", "hello", "hi", "thanks"):
  stream/human/interpret, domain="conversation"
- Questions ("what's X?", "show me Y") → stream/human/read
- Conversational / small talk:
  stream/human/interpret, domain="conversation"
- "Save X to file" → file/human/execute
- "Run pytest" → process/machine/execute, domain="system"
- "create a new scene in Career":
  file/human/execute, domain="play", action_hint="create"
- When uncertain, bias toward stream/human/interpret

EXAMPLES (showing input → output JSON):
"good morning":
  {"destination":"stream","consumer":"human","semantics":"interpret",
    "confident":true,"domain":"conversation","action_hint":null}
"show memory usage":
  {"destination":"stream","consumer":"human","semantics":"read",
    "confident":true,"domain":"system","action_hint":"view"}
"run pytest":
  {"destination":"process","consumer":"machine",
    "semantics":"execute","confident":true,
    "domain":"system","action_hint":null}
"what's on my calendar?":
  {"destination":"stream","consumer":"human","semantics":"read",
    "confident":true,"domain":"calendar","action_hint":"view"}
"move Job Search to Career":
  {"destination":"file","consumer":"human","semantics":"execute",
    "confident":true,"domain":"play","action_hint":"update"}
"undo that":
  {"destination":"file","consumer":"human","semantics":"execute",
    "confident":true,"domain":"undo","action_hint":null}
"you're repeating yourself":
  {"destination":"stream","consumer":"human",
    "semantics":"interpret","confident":true,
    "domain":"feedback","action_hint":null}
"tell me about my goals":
  {"destination":"stream","consumer":"human",
    "semantics":"interpret","confident":true,
    "domain":"personal","action_hint":"view"}
{corrections_block}
Return ONLY a JSON object:
{"destination":"...","consumer":"...","semantics":"...",
  "confident":true/false,"reasoning":"...",
  "domain":"...or null","action_hint":"...or null"}

Set confident=false if you are genuinely unsure which category fits best."""


@dataclass
class ClassificationResult:
    """Result of classifying a user request."""

    classification: Classification
    model: str = ""


class AtomicClassifier:
    """Classify user requests using the LLM with keyword fallback.

    The LLM already loaded for CAIRN/ReOS does the classification.
    When the LLM is unavailable, a simple keyword-based fallback
    classifies conservatively (always confident=False).
    """

    def __init__(self, llm: Any = None):
        """Initialize classifier.

        Args:
            llm: LLM provider implementing chat_json(). None for fallback-only.
        """
        self.llm = llm

    def classify(
        self,
        request: str,
        corrections: list[dict] | None = None,
    ) -> ClassificationResult:
        """Classify a user request into the 3x2x3 taxonomy.

        Args:
            request: User's natural language request.
            corrections: Optional list of past corrections for few-shot context.

        Returns:
            ClassificationResult with classification and model info.
        """
        if self.llm:
            try:
                return self._classify_with_llm(request, corrections)
            except Exception as e:
                logger.warning("LLM classification failed, using fallback: %s", e)

        return ClassificationResult(
            classification=self._fallback_classify(request),
            model="keyword_fallback",
        )

    def _classify_with_llm(
        self,
        request: str,
        corrections: list[dict] | None = None,
    ) -> ClassificationResult:
        """Classify using the LLM."""
        # Build corrections block for few-shot learning
        corrections_block = ""
        if corrections:
            lines = ["\nPAST CORRECTIONS (learn from these):"]
            for c in corrections[:5]:  # Limit to 5 most recent
                sys_cls = (
                    f'{c["system_destination"]}/{c["system_consumer"]}' f'/{c["system_semantics"]}'
                )
                cor_cls = (
                    f'{c["corrected_destination"]}/{c["corrected_consumer"]}'
                    f'/{c["corrected_semantics"]}'
                )
                lines.append(
                    f'- "{c["request"]}" was misclassified as ' f"{sys_cls}, correct is {cor_cls}"
                )
            corrections_block = "\n".join(lines)

        system = CLASSIFICATION_SYSTEM_PROMPT.replace(
            "{corrections_block}", corrections_block
        )
        user = f'Classify this request: "{request}"'

        raw = self.llm.chat_json(system=system, user=user, temperature=0.1, top_p=0.9)
        data = json.loads(raw)

        # Validate and extract
        destination = DestinationType(data["destination"])
        consumer = ConsumerType(data["consumer"])
        semantics = ExecutionSemantics(data["semantics"])
        confident = bool(data.get("confident", False))
        reasoning = str(data.get("reasoning", ""))
        domain = data.get("domain") or None
        action_hint = data.get("action_hint") or None

        model_name = ""
        if hasattr(self.llm, "current_model"):
            model_name = self.llm.current_model or ""

        return ClassificationResult(
            classification=Classification(
                destination=destination,
                consumer=consumer,
                semantics=semantics,
                confident=confident,
                reasoning=reasoning,
                domain=domain,
                action_hint=action_hint,
            ),
            model=model_name,
        )

    def _fallback_classify(self, request: str) -> Classification:
        """Keyword-based fallback when LLM is unavailable.

        Always returns confident=False since keyword matching is unreliable.
        Biases toward stream/human/interpret (conversation) when uncertain.
        """
        lower = request.lower().strip()
        words = set(lower.split())

        # Destination
        destination = DestinationType.STREAM
        if words & {"save", "write", "create", "update", "add", "note", "scene"}:
            destination = DestinationType.FILE
        elif words & {"run", "start", "stop", "kill", "restart", "install", "build", "push"}:
            destination = DestinationType.PROCESS

        # Consumer
        consumer = ConsumerType.HUMAN
        if words & {"json", "csv", "parse", "pytest", "test", "build", "docker"}:
            consumer = ConsumerType.MACHINE

        # Semantics
        semantics = ExecutionSemantics.INTERPRET  # Default to conversation
        if words & {"show", "list", "get", "what", "display", "status", "check"}:
            semantics = ExecutionSemantics.READ
        elif words & {
            "run",
            "start",
            "stop",
            "kill",
            "create",
            "save",
            "delete",
            "install",
            "build",
        }:
            semantics = ExecutionSemantics.EXECUTE

        # Domain
        domain: str | None = None
        if words & {"calendar", "schedule", "event", "meeting", "appointment"}:
            domain = "calendar"
        elif words & {"contact", "person", "people", "email", "phone"}:
            domain = "contacts"
        elif words & {"cpu", "memory", "ram", "disk", "process", "system", "uptime", "docker"}:
            domain = "system"
        elif words & {"act", "scene", "beat", "play"}:
            domain = "play"
        elif words & {"todo", "task", "reminder", "deadline"}:
            domain = "tasks"
        elif words & {"undo", "revert", "reverse"}:
            domain = "undo"
        elif words & {"hi", "hello", "hey", "morning", "afternoon", "evening", "thanks", "bye"}:
            domain = "conversation"

        # Action hint
        action_hint: str | None = None
        if words & {"show", "list", "display", "view", "what"}:
            action_hint = "view"
        elif words & {"find", "search", "where", "look"}:
            action_hint = "search"
        elif words & {"create", "add", "new", "make"}:
            action_hint = "create"
        elif words & {"update", "change", "modify", "move", "rename", "fix"}:
            action_hint = "update"
        elif words & {"delete", "remove", "cancel"}:
            action_hint = "delete"
        elif words & {"status", "check"}:
            action_hint = "status"

        return Classification(
            destination=destination,
            consumer=consumer,
            semantics=semantics,
            confident=False,
            reasoning="keyword fallback (LLM unavailable)",
            domain=domain,
            action_hint=action_hint,
        )
