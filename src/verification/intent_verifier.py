"""LLM-as-judge intent verification.

Uses the LLM to compare the user's original request against the
proposed response, checking for:
- Intent alignment (does the response match what was asked?)
- Missed aspects (did the response skip part of the request?)
- Scope creep (did the response add unrequested information?)
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from reos.providers.base import LLMError, LLMProvider

logger = logging.getLogger(__name__)

INTENT_JUDGE_PROMPT = """You are an INTENT JUDGE for an AI assistant.

Compare the user's original request against the proposed response.
Determine if the response correctly addresses what was asked.

Evaluate on these dimensions:
1. **alignment** — Does the response match the intent? (0.0-1.0)
2. **missed_aspects** — What parts of the request were ignored?
3. **scope_creep** — What was added that wasn't asked for?
4. **issues** — Any problems with the response

Return ONLY a JSON object:
{
  "alignment": 0.0 to 1.0,
  "missed_aspects": ["..."] or [],
  "scope_creep": ["..."] or [],
  "issues": ["..."] or [],
  "reasoning": "brief explanation"
}"""


@dataclass
class IntentJudgment:
    """Result of LLM intent verification."""

    aligned: bool
    alignment_score: float
    missed_aspects: list[str] = field(default_factory=list)
    scope_creep: list[str] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)
    reasoning: str = ""


class LLMIntentVerifier:
    """Verify response alignment with user intent using LLM-as-judge.

    This is a higher-level verifier that checks the final response
    against the original request. It complements the pipeline's
    IntentVerifier (which checks classification alignment).
    """

    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

    def verify(
        self,
        request: str,
        response: str,
        classification: dict[str, Any] | None = None,
    ) -> IntentJudgment:
        """Verify response aligns with user intent.

        Args:
            request: User's original request.
            response: Proposed response text.
            classification: Optional classification context.

        Returns:
            IntentJudgment with alignment analysis.
        """
        user_prompt = self._build_user_prompt(request, response, classification)

        try:
            raw = self._llm.chat_json(
                system=INTENT_JUDGE_PROMPT,
                user=user_prompt,
                temperature=0.1,
            )
            data = json.loads(raw)

            alignment_score = float(data.get("alignment", 0.0))
            return IntentJudgment(
                aligned=alignment_score >= 0.7,
                alignment_score=alignment_score,
                missed_aspects=data.get("missed_aspects", []),
                scope_creep=data.get("scope_creep", []),
                issues=data.get("issues", []),
                reasoning=data.get("reasoning", ""),
            )

        except (json.JSONDecodeError, LLMError) as e:
            logger.warning("Intent verification failed: %s", e)
            return IntentJudgment(
                aligned=True,
                alignment_score=0.5,
                issues=[f"Verification unavailable: {e}"],
                reasoning="LLM verification failed, defaulting to pass",
            )

    def _build_user_prompt(
        self,
        request: str,
        response: str,
        classification: dict[str, Any] | None = None,
    ) -> str:
        """Build the user prompt for the intent judge."""
        parts = [
            f'Original request: "{request}"',
            f'Proposed response: "{response}"',
        ]

        if classification:
            parts.append(
                f"Classification: {classification.get('destination', '?')}/"
                f"{classification.get('consumer', '?')}/"
                f"{classification.get('semantics', '?')}"
            )

        return "\n\n".join(parts)
