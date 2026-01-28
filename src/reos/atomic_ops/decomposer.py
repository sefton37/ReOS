"""Operation decomposition for complex requests.

When a request can't be classified with high confidence, or when it
contains multiple distinct actions, it should be decomposed into
atomic operations that can each be classified and verified independently.

Core principle: "If you can't verify it, decompose it."

Uses LLM-based inference for decomposition detection and splitting.
No regex patterns - pure semantic understanding.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Optional, Protocol
from uuid import uuid4

from .classifier import AtomicClassifier, ClassificationResult
from .models import AtomicOperation, OperationStatus


class LLMProvider(Protocol):
    """Protocol for LLM providers."""
    def chat_json(self, system: str, user: str, temperature: float = 0.1, top_p: float = 0.9) -> str:
        ...


@dataclass
class DecompositionResult:
    """Result of decomposing a request."""
    original_request: str
    decomposed: bool
    operations: list[AtomicOperation]
    reasoning: str
    confidence: float
    needs_clarification: bool = False
    clarification_prompt: str | None = None


class AtomicDecomposer:
    """Decompose complex requests into atomic operations.

    Uses LLM-based inference to understand:
    1. Whether a request contains multiple distinct operations
    2. How to split the request into atomic units
    3. When clarification is needed due to ambiguity

    The atomic structure is recursive - when uncertain, we decompose
    further until we reach atomic units that can be verified with
    high confidence.
    """

    def __init__(
        self,
        classifier: Optional[AtomicClassifier] = None,
        llm: Optional[LLMProvider] = None,
    ):
        """Initialize decomposer.

        Args:
            classifier: Classifier for sub-operation classification.
            llm: LLM provider for semantic decomposition.
        """
        self.classifier = classifier or AtomicClassifier()
        self.llm = llm

    def decompose(
        self,
        request: str,
        user_id: str = "",
        source_agent: str = "",
        parent_id: Optional[str] = None,
        force_decomposition: bool = False,
    ) -> DecompositionResult:
        """Decompose a request into atomic operations.

        Uses LLM to understand whether decomposition is needed and how
        to split the request. If uncertain, returns needs_clarification
        so the atomic verification pipeline can handle disambiguation.

        Args:
            request: User's natural language request.
            user_id: User identifier.
            source_agent: Source agent (cairn, reos, riva).
            parent_id: Parent operation ID if this is a sub-decomposition.
            force_decomposition: Force decomposition even if not needed.

        Returns:
            DecompositionResult with atomic operations.
        """
        # Use LLM to analyze the request
        analysis = self._analyze_request(request)

        # If LLM is uncertain, signal clarification needed
        if analysis.get("needs_clarification") and analysis.get("confidence", 1.0) < 0.7:
            # Create a placeholder operation that signals clarification needed
            op = AtomicOperation(
                id=str(uuid4()),
                user_request=request,
                user_id=user_id,
                source_agent=source_agent,
                parent_id=parent_id,
                status=OperationStatus.AWAITING_VERIFICATION,
            )

            return DecompositionResult(
                original_request=request,
                decomposed=False,
                operations=[op],
                reasoning=analysis.get("reasoning", "Uncertain decomposition"),
                confidence=analysis.get("confidence", 0.5),
                needs_clarification=True,
                clarification_prompt=analysis.get("clarification_prompt"),
            )

        needs_split = force_decomposition or analysis.get("needs_decomposition", False)
        sub_requests = analysis.get("sub_requests", [request])

        if not needs_split or len(sub_requests) <= 1:
            # Single operation - classify and return
            classification_result = self.classifier.classify(request)

            op = AtomicOperation(
                id=str(uuid4()),
                user_request=request,
                user_id=user_id,
                source_agent=source_agent,
                classification=classification_result.classification,
                parent_id=parent_id,
                status=OperationStatus.AWAITING_VERIFICATION,
            )

            return DecompositionResult(
                original_request=request,
                decomposed=False,
                operations=[op],
                reasoning=analysis.get("reasoning", "Single atomic operation"),
                confidence=classification_result.classification.confidence,
            )

        # Create parent operation for tracking
        parent_op_id = str(uuid4())

        # Classify each sub-request
        child_operations = []
        child_ids = []
        total_confidence = 0.0
        any_needs_clarification = False

        for sub_request in sub_requests:
            sub_request = sub_request.strip()
            if not sub_request:
                continue

            classification_result = self.classifier.classify(sub_request)

            # Check if this sub-operation needs further decomposition (recursive)
            if classification_result.classification.confidence < 0.6:
                # Low confidence - may need further decomposition or clarification
                any_needs_clarification = True

            child_op = AtomicOperation(
                id=str(uuid4()),
                user_request=sub_request,
                user_id=user_id,
                source_agent=source_agent,
                classification=classification_result.classification,
                parent_id=parent_op_id,
                status=OperationStatus.AWAITING_VERIFICATION,
            )

            child_operations.append(child_op)
            child_ids.append(child_op.id)
            total_confidence += classification_result.classification.confidence

        # Create parent operation
        parent_op = AtomicOperation(
            id=parent_op_id,
            user_request=request,
            user_id=user_id,
            source_agent=source_agent,
            is_decomposed=True,
            child_ids=child_ids,
            parent_id=parent_id,
            status=OperationStatus.DECOMPOSED,
        )

        # Include parent in result
        all_operations = [parent_op] + child_operations

        avg_confidence = total_confidence / len(child_operations) if child_operations else 0.5

        return DecompositionResult(
            original_request=request,
            decomposed=True,
            operations=all_operations,
            reasoning=analysis.get("reasoning", f"Split into {len(child_operations)} sub-operations"),
            confidence=min(avg_confidence, analysis.get("confidence", 1.0)),
            needs_clarification=any_needs_clarification,
            clarification_prompt=analysis.get("clarification_prompt") if any_needs_clarification else None,
        )

    def _analyze_request(self, request: str) -> dict[str, Any]:
        """Use LLM to analyze if request needs decomposition and how.

        Returns a dict with:
            - needs_decomposition: bool
            - sub_requests: list[str] (if decomposed)
            - confidence: float
            - reasoning: str
            - needs_clarification: bool
            - clarification_prompt: str | None
        """
        if not self.llm:
            # Fallback to simple heuristics if no LLM
            return {
                "needs_decomposition": False,
                "sub_requests": [request],
                "confidence": 0.5,
                "reasoning": "No LLM available for semantic analysis",
                "needs_clarification": False,
                "clarification_prompt": None,
            }

        system = """You are an OPERATION DECOMPOSER. Analyze if a user's request contains multiple distinct operations.

WHAT COUNTS AS MULTIPLE OPERATIONS:
- "Move X and Y to Z" = TWO operations (move X to Z, move Y to Z)
- "Delete the file and restart the service" = TWO operations
- "Show me X" = ONE operation
- "Create a scene about X" = ONE operation
- "Move those two scenes to Career" = MAY BE multiple (depends on which scenes)

WHAT DOES NOT COUNT:
- "Move the X and Y scene" where "X and Y" is part of a single entity name = ONE operation
- Compound nouns or multi-word entity names should not be split

IMPORTANT:
- If you're uncertain which entities the user refers to, signal needs_clarification
- Only decompose when you're CONFIDENT there are multiple distinct operations
- Preserve entity references exactly as stated by the user

Return ONLY a JSON object:
{
    "needs_decomposition": true/false,
    "operation_count": number,
    "sub_requests": ["first operation", "second operation", ...],
    "confidence": 0.0-1.0,
    "reasoning": "why you made this decision",
    "needs_clarification": true if uncertain about entity references,
    "clarification_prompt": "question to ask if clarification needed"
}"""

        user = f"""USER REQUEST: "{request}"

Analyze: Does this contain multiple distinct operations? If yes, what are they?"""

        try:
            raw = self.llm.chat_json(system=system, user=user, temperature=0.1, top_p=0.9)
            data = json.loads(raw)

            return {
                "needs_decomposition": data.get("needs_decomposition", False),
                "sub_requests": data.get("sub_requests", [request]),
                "confidence": float(data.get("confidence", 0.5)),
                "reasoning": data.get("reasoning", ""),
                "needs_clarification": data.get("needs_clarification", False),
                "clarification_prompt": data.get("clarification_prompt"),
            }

        except Exception as e:
            return {
                "needs_decomposition": False,
                "sub_requests": [request],
                "confidence": 0.3,
                "reasoning": f"LLM analysis failed: {e}",
                "needs_clarification": True,
                "clarification_prompt": "Could you rephrase your request more specifically?",
            }

    def _needs_decomposition(self, request: str) -> bool:
        """Check if request needs decomposition using LLM.

        This is kept for backward compatibility with create_operation_tree.
        """
        analysis = self._analyze_request(request)
        return analysis["needs_decomposition"]

    def _split_request(self, request: str) -> list[str]:
        """Split request into sub-requests using LLM.

        This is kept for backward compatibility.
        """
        analysis = self._analyze_request(request)
        return analysis.get("sub_requests", [request])


def create_operation_tree(
    decomposer: AtomicDecomposer,
    request: str,
    user_id: str = "",
    source_agent: str = "",
    max_depth: int = 3,
) -> list[AtomicOperation]:
    """Recursively decompose a request into an operation tree.

    Args:
        decomposer: Decomposer instance.
        request: User request.
        user_id: User identifier.
        source_agent: Source agent.
        max_depth: Maximum recursion depth.

    Returns:
        Flat list of all operations (parents and children).
    """
    all_ops = []

    def _decompose_recursive(req: str, parent_id: Optional[str], depth: int) -> list[str]:
        if depth >= max_depth:
            # Max depth reached, classify without further decomposition
            result = decomposer.classifier.classify(req)
            op = AtomicOperation(
                id=str(uuid4()),
                user_request=req,
                user_id=user_id,
                source_agent=source_agent,
                classification=result.classification,
                parent_id=parent_id,
                status=OperationStatus.AWAITING_VERIFICATION,
            )
            all_ops.append(op)
            return [op.id]

        result = decomposer.decompose(
            request=req,
            user_id=user_id,
            source_agent=source_agent,
            parent_id=parent_id,
        )

        if not result.decomposed:
            # Single operation
            all_ops.extend(result.operations)
            return [op.id for op in result.operations]

        # Decomposed - add parent and recurse for children
        parent_op = result.operations[0]  # First is always parent when decomposed
        all_ops.append(parent_op)

        child_ids = []
        for child_op in result.operations[1:]:
            # Check if child needs further decomposition
            if decomposer._needs_decomposition(child_op.user_request):
                sub_ids = _decompose_recursive(
                    child_op.user_request,
                    parent_op.id,
                    depth + 1
                )
                child_ids.extend(sub_ids)
            else:
                all_ops.append(child_op)
                child_ids.append(child_op.id)

        # Update parent's child_ids
        parent_op.child_ids = child_ids
        return [parent_op.id]

    _decompose_recursive(request, None, 0)
    return all_ops
