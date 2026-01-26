"""Operation decomposition for complex requests.

When a request can't be classified with high confidence, or when it
contains multiple distinct actions, it should be decomposed into
atomic operations that can each be classified and verified independently.

Core principle: "If you can't verify it, decompose it."
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional
from uuid import uuid4

from .classifier import AtomicClassifier, ClassificationResult
from .models import AtomicOperation, OperationStatus


@dataclass
class DecompositionResult:
    """Result of decomposing a request."""
    original_request: str
    decomposed: bool
    operations: list[AtomicOperation]
    reasoning: str
    confidence: float


# Patterns that suggest multiple operations
MULTI_OP_PATTERNS = [
    r'\bthen\b',           # "do X then Y"
    r'\band\s+(?:then\s+)?', # "X and Y" or "X and then Y"
    r'\bafter\s+that\b',    # "do X, after that Y"
    r'\bfirst\b.*\bthen\b', # "first X, then Y"
    r'\balso\b',            # "X, also Y"
    r'[;]',                 # semicolon separator
    r'\d+\.\s+',            # numbered list "1. X 2. Y"
]

# Conjunctions that connect independent clauses
CLAUSE_SEPARATORS = [
    ", then ", " then ", " and then ",
    "; ", " after that ", " also ",
    " followed by ", " next ",
]


class AtomicDecomposer:
    """Decompose complex requests into atomic operations.

    Strategies:
    1. Pattern-based splitting (conjunctions, numbered lists)
    2. Semantic analysis for implicit multi-step requests
    3. Confidence-based decomposition triggers
    """

    def __init__(self, classifier: Optional[AtomicClassifier] = None):
        """Initialize decomposer.

        Args:
            classifier: Classifier for sub-operation classification.
        """
        self.classifier = classifier or AtomicClassifier()

    def decompose(
        self,
        request: str,
        user_id: str = "",
        source_agent: str = "",
        parent_id: Optional[str] = None,
        force_decomposition: bool = False,
    ) -> DecompositionResult:
        """Decompose a request into atomic operations.

        Args:
            request: User's natural language request.
            user_id: User identifier.
            source_agent: Source agent (cairn, reos, riva).
            parent_id: Parent operation ID if this is a sub-decomposition.
            force_decomposition: Force decomposition even if not needed.

        Returns:
            DecompositionResult with atomic operations.
        """
        # Check if decomposition is needed
        needs_split = force_decomposition or self._needs_decomposition(request)

        if not needs_split:
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
                reasoning="Single atomic operation",
                confidence=classification_result.classification.confidence,
            )

        # Split into sub-requests
        sub_requests = self._split_request(request)

        if len(sub_requests) <= 1:
            # Splitting didn't produce multiple operations
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
                reasoning="Could not split into sub-operations",
                confidence=classification_result.classification.confidence,
            )

        # Create parent operation for tracking
        parent_op_id = str(uuid4())

        # Classify each sub-request
        child_operations = []
        child_ids = []
        total_confidence = 0.0

        for sub_request in sub_requests:
            sub_request = sub_request.strip()
            if not sub_request:
                continue

            classification_result = self.classifier.classify(sub_request)

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
            reasoning=f"Split into {len(child_operations)} sub-operations",
            confidence=avg_confidence,
        )

    def _needs_decomposition(self, request: str) -> bool:
        """Check if request needs decomposition."""
        # Check for multi-operation patterns
        for pattern in MULTI_OP_PATTERNS:
            if re.search(pattern, request, re.IGNORECASE):
                return True

        # Check for clause separators
        request_lower = request.lower()
        for sep in CLAUSE_SEPARATORS:
            if sep in request_lower:
                return True

        # Check request length (very long requests often need decomposition)
        if len(request.split()) > 30:
            return True

        return False

    def _split_request(self, request: str) -> list[str]:
        """Split request into sub-requests."""
        parts = []

        # Try numbered list first
        numbered_match = re.findall(r'(?:^|\s)(\d+)\.\s*([^0-9]+?)(?=(?:\s*\d+\.)|$)', request, re.DOTALL)
        if len(numbered_match) >= 2:
            return [part[1].strip() for part in numbered_match]

        # Try clause separators
        current = request
        for sep in CLAUSE_SEPARATORS:
            if sep in current.lower():
                # Split on this separator
                idx = current.lower().find(sep)
                before = current[:idx].strip()
                after = current[idx + len(sep):].strip()

                if before:
                    parts.append(before)
                if after:
                    # Recursively split the remainder
                    parts.extend(self._split_request(after))
                return parts

        # Fallback: try splitting on " and " if it looks like independent clauses
        if " and " in request.lower():
            and_parts = re.split(r'\s+and\s+', request, flags=re.IGNORECASE)
            # Only split if both parts look like complete requests
            if len(and_parts) == 2:
                # Check if both have verbs (simple heuristic)
                if self._looks_like_action(and_parts[0]) and self._looks_like_action(and_parts[1]):
                    return [p.strip() for p in and_parts]

        # No split found
        return [request]

    def _looks_like_action(self, text: str) -> bool:
        """Check if text looks like an actionable request."""
        action_words = {
            "show", "display", "list", "get", "find", "search",
            "create", "make", "add", "write", "save",
            "run", "execute", "start", "stop", "kill",
            "delete", "remove", "update", "modify",
            "install", "open", "close", "restart",
        }
        words = set(text.lower().split())
        return bool(words & action_words)


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
