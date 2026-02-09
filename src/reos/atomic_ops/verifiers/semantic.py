"""Semantic verification layer.

Verifies that the operation makes sense in the current context.
Uses classification and features to check semantic coherence.

Checks:
- Classification is consistent with request content
- Referenced resources could plausibly exist
- Action makes sense for the target
"""

from __future__ import annotations

from ..models import (
    AtomicOperation,
    ConsumerType,
    DestinationType,
    ExecutionSemantics,
    VerificationLayer,
    VerificationResult,
)
from .base import BaseVerifier, VerificationContext


# Action-to-semantics coherence rules
ACTION_SEMANTICS_MAP = {
    # Read actions
    "show": ExecutionSemantics.READ,
    "display": ExecutionSemantics.READ,
    "list": ExecutionSemantics.READ,
    "get": ExecutionSemantics.READ,
    "find": ExecutionSemantics.READ,
    "search": ExecutionSemantics.READ,
    "check": ExecutionSemantics.READ,
    # Interpret actions
    "explain": ExecutionSemantics.INTERPRET,
    "analyze": ExecutionSemantics.INTERPRET,
    "summarize": ExecutionSemantics.INTERPRET,
    "describe": ExecutionSemantics.INTERPRET,
    "what": ExecutionSemantics.INTERPRET,
    "why": ExecutionSemantics.INTERPRET,
    "how": ExecutionSemantics.INTERPRET,
    # Execute actions
    "create": ExecutionSemantics.EXECUTE,
    "make": ExecutionSemantics.EXECUTE,
    "add": ExecutionSemantics.EXECUTE,
    "write": ExecutionSemantics.EXECUTE,
    "save": ExecutionSemantics.EXECUTE,
    "run": ExecutionSemantics.EXECUTE,
    "execute": ExecutionSemantics.EXECUTE,
    "start": ExecutionSemantics.EXECUTE,
    "stop": ExecutionSemantics.EXECUTE,
    "kill": ExecutionSemantics.EXECUTE,
    "delete": ExecutionSemantics.EXECUTE,
    "remove": ExecutionSemantics.EXECUTE,
    "update": ExecutionSemantics.EXECUTE,
    "install": ExecutionSemantics.EXECUTE,
}

# Object-to-destination coherence rules
OBJECT_DESTINATION_MAP = {
    # Stream destinations
    "memory": DestinationType.STREAM,
    "cpu": DestinationType.STREAM,
    "status": DestinationType.STREAM,
    "info": DestinationType.STREAM,
    "calendar": DestinationType.STREAM,
    # File destinations
    "file": DestinationType.FILE,
    "document": DestinationType.FILE,
    "notes": DestinationType.FILE,
    "config": DestinationType.FILE,
    "scene": DestinationType.FILE,
    "act": DestinationType.FILE,
    # Process destinations
    "process": DestinationType.PROCESS,
    "service": DestinationType.PROCESS,
    "container": DestinationType.PROCESS,
    "docker": DestinationType.PROCESS,
    "test": DestinationType.PROCESS,
    "pytest": DestinationType.PROCESS,
}


class SemanticVerifier(BaseVerifier):
    """Verify semantic coherence of operations.

    Checks that the operation classification makes sense
    given the content of the request and context.
    """

    @property
    def layer(self) -> VerificationLayer:
        return VerificationLayer.SEMANTIC

    def verify(
        self,
        operation: AtomicOperation,
        context: VerificationContext,
    ) -> VerificationResult:
        """Verify semantic coherence."""
        issues = []

        # Skip if no classification
        if not operation.classification:
            return self._warn(
                ["No classification available for semantic check"],
                confidence=0.5,
            )

        request_lower = operation.user_request.lower()
        words = set(request_lower.split())

        # Check action-semantics coherence
        semantics_issue = self._check_semantics_coherence(
            words, operation.classification.semantics
        )
        if semantics_issue:
            issues.append(semantics_issue)

        # Check object-destination coherence
        destination_issue = self._check_destination_coherence(
            words, operation.classification.destination
        )
        if destination_issue:
            issues.append(destination_issue)

        # Check consumer coherence
        consumer_issue = self._check_consumer_coherence(
            request_lower, operation.classification.consumer
        )
        if consumer_issue:
            issues.append(consumer_issue)

        # Check agent-operation coherence
        agent_issue = self._check_agent_coherence(
            operation.source_agent, operation.classification
        )
        if agent_issue:
            issues.append(agent_issue)

        # Check classification confidence
        if not operation.classification.confident:
            issues.append("Classification not confident")

        # Calculate overall confidence
        confidence = operation.confidence  # 0.9 if confident, 0.3 if not
        if issues:
            confidence *= 0.7  # Reduce confidence if issues found

        if issues:
            return self._warn(issues, confidence=confidence)

        return self._pass(
            confidence=confidence,
            details=f"Semantically coherent ({operation.semantics.value if operation.semantics else 'unknown'})",
        )

    def _check_semantics_coherence(
        self,
        words: set[str],
        semantics: ExecutionSemantics,
    ) -> str | None:
        """Check if detected actions match classified semantics."""
        expected_semantics = set()

        for word in words:
            if word in ACTION_SEMANTICS_MAP:
                expected_semantics.add(ACTION_SEMANTICS_MAP[word])

        if expected_semantics and semantics not in expected_semantics:
            expected_str = ", ".join(s.value for s in expected_semantics)
            return f"Action words suggest {expected_str}, but classified as {semantics.value}"

        return None

    def _check_destination_coherence(
        self,
        words: set[str],
        destination: DestinationType,
    ) -> str | None:
        """Check if target objects match classified destination."""
        expected_destinations = set()

        for word in words:
            if word in OBJECT_DESTINATION_MAP:
                expected_destinations.add(OBJECT_DESTINATION_MAP[word])

        if expected_destinations and destination not in expected_destinations:
            expected_str = ", ".join(d.value for d in expected_destinations)
            return f"Target objects suggest {expected_str}, but classified as {destination.value}"

        return None

    def _check_consumer_coherence(
        self,
        request: str,
        consumer: ConsumerType,
    ) -> str | None:
        """Check if request style matches consumer type."""
        # Machine consumers usually want structured output
        machine_indicators = ["json", "csv", "xml", "structured", "for parsing", "output format"]
        has_machine_indicator = any(ind in request for ind in machine_indicators)

        # Human consumers usually ask questions or want explanations
        human_indicators = ["?", "explain", "tell me", "show me", "what is", "why"]
        has_human_indicator = any(ind in request for ind in human_indicators)

        if has_machine_indicator and consumer == ConsumerType.HUMAN:
            return "Request suggests machine consumer but classified as human"

        if has_human_indicator and consumer == ConsumerType.MACHINE and not has_machine_indicator:
            return "Request suggests human consumer but classified as machine"

        return None

    def _check_agent_coherence(
        self,
        source_agent: str,
        classification: object,
    ) -> str | None:
        """Check if classification matches typical agent operations."""
        if not source_agent:
            return None

        # CAIRN typically does read/interpret operations on files/streams
        if source_agent == "cairn":
            if classification.semantics == ExecutionSemantics.EXECUTE:
                if classification.destination == DestinationType.PROCESS:
                    return "CAIRN typically doesn't execute processes (consider routing to ReOS)"

        # ReOS typically does process operations
        if source_agent == "reos":
            if classification.destination == DestinationType.FILE:
                if classification.semantics == ExecutionSemantics.INTERPRET:
                    return "ReOS typically doesn't interpret files (consider routing to CAIRN)"

        return None
