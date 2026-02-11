"""LLM-native request classification.

Uses the local LLM to classify user requests into the 3x2x3 taxonomy
(destination x consumer x semantics) plus domain and action_hint.
Falls back to keyword heuristics when the LLM is unavailable.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from reos.atomic_ops.classifier import CLASSIFICATION_SYSTEM_PROMPT
from reos.atomic_ops.models import (
    Classification,
    ConsumerType,
    DestinationType,
    ExecutionSemantics,
)
from reos.providers.base import LLMError

logger = logging.getLogger(__name__)


@dataclass
class ClassificationResult:
    """Result of classifying a user request."""

    classification: Classification
    model: str = ""
    raw_response: dict[str, Any] | None = None


class LLMClassifier:
    """Classify user requests using the LLM with keyword fallback.

    Wraps the existing AtomicClassifier with a cleaner interface that
    separates prompt building from LLM invocation.
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

    def _build_classification_prompt(
        self,
        corrections: list[dict] | None = None,
    ) -> str:
        """Build the system prompt with optional corrections context."""
        corrections_block = ""
        if corrections:
            lines = ["\nPAST CORRECTIONS (learn from these):"]
            for c in corrections[:5]:
                sys_cls = (
                    f'{c["system_destination"]}/{c["system_consumer"]}'
                    f'/{c["system_semantics"]}'
                )
                cor_cls = (
                    f'{c["corrected_destination"]}/{c["corrected_consumer"]}'
                    f'/{c["corrected_semantics"]}'
                )
                lines.append(
                    f'- "{c["request"]}" was misclassified as '
                    f"{sys_cls}, correct is {cor_cls}"
                )
            corrections_block = "\n".join(lines)

        return CLASSIFICATION_SYSTEM_PROMPT.replace("{corrections_block}", corrections_block)

    def _classify_with_llm(
        self,
        request: str,
        corrections: list[dict] | None = None,
    ) -> ClassificationResult:
        """Classify using the LLM."""
        system = self._build_classification_prompt(corrections)
        user = f'Classify this request: "{request}"'

        raw = self.llm.chat_json(system=system, user=user, temperature=0.1, top_p=0.9)
        data = json.loads(raw)

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
            raw_response=data,
        )

    def _fallback_classify(self, request: str) -> Classification:
        """Keyword-based fallback when LLM is unavailable.

        Always returns confident=False since keyword matching is unreliable.
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
        semantics = ExecutionSemantics.INTERPRET
        if words & {"show", "list", "get", "what", "display", "status", "check"}:
            semantics = ExecutionSemantics.READ
        elif words & {
            "run", "start", "stop", "kill", "create", "save", "delete", "install", "build",
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
        elif words & {"act", "scene", "play"}:
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
