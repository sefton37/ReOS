"""Request router — classify and dispatch to the appropriate agent.

The router is the main entry point for handling user requests:
1. Classify the request using LLMClassifier
2. Route to the appropriate agent (CAIRN, ReOS, or future RIVA)
3. Return the agent's response

This replaces direct AtomicOpsProcessor usage for the common case.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from reos.atomic_ops.models import Classification

from agents.base_agent import AgentResponse, BaseAgent
from classification.llm_classifier import ClassificationResult, LLMClassifier

logger = logging.getLogger(__name__)

# Domain-to-agent mapping
_CAIRN_DOMAINS = {
    "calendar", "contacts", "play", "tasks", "knowledge",
    "personal", "conversation", "feedback",
}
_REOS_DOMAINS = {"system"}
_FROZEN_AGENTS = {"riva"}


@dataclass
class RoutingResult:
    """Result of routing a request."""

    agent_name: str
    classification: ClassificationResult
    response: AgentResponse


class RequestRouter:
    """Route classified requests to the appropriate agent.

    Agents are registered by name. The router uses the classification
    domain and semantics to select the right agent.
    """

    def __init__(
        self,
        classifier: LLMClassifier,
        agents: dict[str, BaseAgent] | None = None,
    ) -> None:
        self._classifier = classifier
        self._agents: dict[str, BaseAgent] = agents or {}

    def register_agent(self, name: str, agent: BaseAgent) -> None:
        """Register an agent for routing."""
        self._agents[name] = agent

    def handle(
        self,
        request: str,
        corrections: list[dict] | None = None,
    ) -> RoutingResult:
        """Classify and route a request.

        Args:
            request: User's natural language request.
            corrections: Optional past classification corrections.

        Returns:
            RoutingResult with the chosen agent's response.
        """
        # Classify
        result = self._classifier.classify(request, corrections=corrections)
        classification = result.classification

        # Route
        agent_name = self._select_agent(classification)
        agent = self._agents.get(agent_name)

        if agent is None:
            # Fallback: try CAIRN as default
            agent = self._agents.get("cairn")
            if agent is None:
                return RoutingResult(
                    agent_name="none",
                    classification=result,
                    response=AgentResponse(
                        text="No agent available to handle this request.",
                        confidence=0.0,
                    ),
                )
            agent_name = "cairn"

        # Respond
        response = agent.respond(request, classification)

        return RoutingResult(
            agent_name=agent_name,
            classification=result,
            response=response,
        )

    def _select_agent(self, classification: Classification) -> str:
        """Select the best agent based on classification."""
        domain = classification.domain

        if domain in _CAIRN_DOMAINS:
            return "cairn"

        if domain in _REOS_DOMAINS:
            return "reos"

        if domain == "undo":
            # Undo goes to whichever agent handled the original action
            # For now, default to CAIRN
            return "cairn"

        # Unknown domain — default to CAIRN for interpret, ReOS for execute
        if classification.semantics.value == "execute":
            return "reos"

        return "cairn"
