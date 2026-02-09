"""Classification context for few-shot learning.

Queries past user corrections and formats them as few-shot examples
for the LLM classifier prompt.
"""

from __future__ import annotations

from .schema import AtomicOpsStore


class ClassificationContext:
    """Builds few-shot context from past corrections.

    When the user corrects a classification, that correction is stored
    in the database. This module retrieves recent corrections and
    formats them for the classifier prompt.
    """

    def __init__(self, store: AtomicOpsStore):
        self.store = store

    def get_corrections(
        self,
        user_id: str | None = None,
        limit: int = 5,
    ) -> list[dict]:
        """Get recent corrections formatted for the classifier.

        Returns list of dicts with:
            request, system_destination, system_consumer, system_semantics,
            corrected_destination, corrected_consumer, corrected_semantics
        """
        return self.store.get_recent_corrections(user_id=user_id, limit=limit)

    def has_corrections(self, user_id: str | None = None) -> bool:
        """Check if there are any corrections available."""
        corrections = self.store.get_recent_corrections(user_id=user_id, limit=1)
        return len(corrections) > 0
