"""CAIRN Coherence Verification Kernel.

Core Principle: If you can't verify coherence, decompose the demand.

This module mirrors RIVA's recursive intent verification pattern but applies
it to identity coherence and attention management. Where RIVA asks "Can I
verify this code intention?", CAIRN asks "Does this attention demand cohere
with the user's identity?"

The recursive structure:
- AttentionDemand: Something competing for attention (like RIVA's Intention)
- CoherenceCheck: One verification cycle (like RIVA's Cycle)
- CoherenceVerifier.verify(): Recursive verification (like RIVA's work())

Design principles:
1. Sovereignty-preserving: Never guilt-trips, only surfaces and recommends
2. Identity-first: User's stated values/goals are the ground truth
3. Anti-pattern fast-path: Known rejections skip LLM calls
4. Transparency: All decisions are traceable
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from reos.providers import LLMProvider

logger = logging.getLogger(__name__)


# =============================================================================
# Core Types
# =============================================================================


class CoherenceStatus(Enum):
    """Status of a coherence verification."""

    PENDING = "pending"          # Not yet checked
    CHECKING = "checking"        # Currently being verified
    COHERENT = "coherent"        # Demand aligns with identity
    INCOHERENT = "incoherent"    # Demand conflicts with identity
    UNCERTAIN = "uncertain"      # Could not determine alignment


@dataclass
class IdentityFacet:
    """A facet of the user's identity from The Play.

    Facets are extracted from various sources in The Play hierarchy:
    - me.md: Core identity (highest priority)
    - Acts: Major life projects and goals
    - Scenes: Sub-projects and contexts
    - Beats: Specific items and tasks
    - KB entries: Knowledge and notes

    Attributes:
        name: Facet category (e.g., "values", "goals", "relationships")
        source: Path in Play hierarchy where this was extracted
        content: The actual text content
        weight: Relevance weight for scoring (1.0 = normal, higher = more important)
    """

    name: str
    source: str
    content: str
    weight: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "source": self.source,
            "content": self.content,
            "weight": self.weight,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> IdentityFacet:
        return cls(
            name=data["name"],
            source=data["source"],
            content=data["content"],
            weight=data.get("weight", 1.0),
        )


@dataclass
class IdentityModel:
    """Hierarchical representation of user identity from The Play.

    Built from the Play filesystem:
    - core: me.md content (highest priority, the user's story)
    - facets: Extracted from Acts/Scenes/Beats/KB entries
    - anti_patterns: Things the user has explicitly rejected

    The identity model is rebuilt as needed from the Play, ensuring
    coherence checks always use current self-understanding.

    Attributes:
        core: The me.md content (user's core identity story)
        facets: List of extracted identity facets
        anti_patterns: Patterns/topics the user wants to reject
        built_at: When this model was constructed
    """

    core: str
    facets: list[IdentityFacet] = field(default_factory=list)
    anti_patterns: list[str] = field(default_factory=list)
    built_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        return {
            "core": self.core,
            "facets": [f.to_dict() for f in self.facets],
            "anti_patterns": self.anti_patterns,
            "built_at": self.built_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> IdentityModel:
        return cls(
            core=data["core"],
            facets=[IdentityFacet.from_dict(f) for f in data.get("facets", [])],
            anti_patterns=data.get("anti_patterns", []),
            built_at=datetime.fromisoformat(data["built_at"]) if data.get("built_at") else datetime.now(timezone.utc),
        )

    def get_facets_by_name(self, name: str) -> list[IdentityFacet]:
        """Get all facets with a given name."""
        return [f for f in self.facets if f.name == name]

    def get_relevant_facets(self, keywords: list[str]) -> list[IdentityFacet]:
        """Get facets whose content contains any of the keywords."""
        relevant = []
        for facet in self.facets:
            content_lower = facet.content.lower()
            if any(kw.lower() in content_lower for kw in keywords):
                relevant.append(facet)
        return relevant


@dataclass
class AttentionDemand:
    """Something competing for the user's attention.

    Analogous to RIVA's Intention but for attention management.
    Represents any external or internal request for the user's focus.

    Attributes:
        id: Unique identifier
        source: Where this demand came from (email, thought, calendar, etc.)
        content: What it wants (the actual request/need)
        urgency: Claimed urgency level (0-10, where 10 is most urgent)
        created_at: When this demand was registered
        coherence_score: Calculated alignment with identity (-1.0 to 1.0)
        sub_demands: Child demands if this was decomposed
    """

    id: str
    source: str
    content: str
    urgency: int = 5
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    coherence_score: float | None = None
    sub_demands: list["AttentionDemand"] = field(default_factory=list)

    @staticmethod
    def create(source: str, content: str, urgency: int = 5) -> AttentionDemand:
        """Create a new attention demand with unique ID."""
        return AttentionDemand(
            id=f"demand-{uuid.uuid4().hex[:8]}",
            source=source,
            content=content,
            urgency=max(0, min(10, urgency)),  # Clamp to 0-10
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source": self.source,
            "content": self.content,
            "urgency": self.urgency,
            "created_at": self.created_at.isoformat(),
            "coherence_score": self.coherence_score,
            "sub_demands": [d.to_dict() for d in self.sub_demands],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AttentionDemand:
        return cls(
            id=data["id"],
            source=data["source"],
            content=data["content"],
            urgency=data.get("urgency", 5),
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else datetime.now(timezone.utc),
            coherence_score=data.get("coherence_score"),
            sub_demands=[cls.from_dict(d) for d in data.get("sub_demands", [])],
        )


@dataclass
class CoherenceCheck:
    """One cycle of coherence verification.

    Analogous to RIVA's Cycle but for identity alignment checking.
    Each check examines one aspect of how a demand relates to identity.

    Attributes:
        facet_checked: Which identity facet was consulted
        demand_aspect: Which aspect of the demand was examined
        alignment: Score from -1.0 (opposed) to 1.0 (aligned)
        reasoning: Why this alignment score was assigned
    """

    facet_checked: str
    demand_aspect: str
    alignment: float
    reasoning: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "facet_checked": self.facet_checked,
            "demand_aspect": self.demand_aspect,
            "alignment": self.alignment,
            "reasoning": self.reasoning,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CoherenceCheck:
        return cls(
            facet_checked=data["facet_checked"],
            demand_aspect=data["demand_aspect"],
            alignment=data.get("alignment", 0.0),
            reasoning=data.get("reasoning", ""),
        )


# Type alias for recommendation
CoherenceRecommendation = Literal["accept", "defer", "reject", "decompose"]


@dataclass
class CoherenceResult:
    """Result of coherence verification.

    Contains the full trace of checks performed and the final recommendation.

    Attributes:
        demand: The attention demand that was checked
        checks: All coherence checks performed
        overall_score: Aggregated coherence score (-1.0 to 1.0)
        recommendation: What to do with this demand
        trace: Audit trail of decisions made
        verified_at: When verification completed
    """

    demand: AttentionDemand
    checks: list[CoherenceCheck] = field(default_factory=list)
    overall_score: float = 0.0
    recommendation: CoherenceRecommendation = "defer"
    trace: list[str] = field(default_factory=list)
    verified_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        return {
            "demand": self.demand.to_dict(),
            "checks": [c.to_dict() for c in self.checks],
            "overall_score": self.overall_score,
            "recommendation": self.recommendation,
            "trace": self.trace,
            "verified_at": self.verified_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CoherenceResult:
        return cls(
            demand=AttentionDemand.from_dict(data["demand"]),
            checks=[CoherenceCheck.from_dict(c) for c in data.get("checks", [])],
            overall_score=data.get("overall_score", 0.0),
            recommendation=data.get("recommendation", "defer"),
            trace=data.get("trace", []),
            verified_at=datetime.fromisoformat(data["verified_at"]) if data.get("verified_at") else datetime.now(timezone.utc),
        )


@dataclass
class CoherenceTrace:
    """Audit trail for coherence decisions.

    Stored for:
    - Debugging why something was surfaced/rejected
    - Learning from user overrides (if they disagreed)
    - Transparency about attention decisions

    Attributes:
        trace_id: Unique identifier
        demand_id: The demand that was verified
        timestamp: When this trace was created
        identity_hash: Hash of identity model used (for versioning)
        checks: All checks performed
        final_score: The computed coherence score
        recommendation: What was recommended
        user_override: If user disagreed, what they chose instead
    """

    trace_id: str
    demand_id: str
    timestamp: datetime
    identity_hash: str
    checks: list[CoherenceCheck]
    final_score: float
    recommendation: CoherenceRecommendation
    user_override: CoherenceRecommendation | None = None

    @staticmethod
    def create(result: CoherenceResult, identity_hash: str) -> CoherenceTrace:
        """Create a trace from a coherence result."""
        return CoherenceTrace(
            trace_id=f"trace-{uuid.uuid4().hex[:8]}",
            demand_id=result.demand.id,
            timestamp=result.verified_at,
            identity_hash=identity_hash,
            checks=result.checks,
            final_score=result.overall_score,
            recommendation=result.recommendation,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "demand_id": self.demand_id,
            "timestamp": self.timestamp.isoformat(),
            "identity_hash": self.identity_hash,
            "checks": [c.to_dict() for c in self.checks],
            "final_score": self.final_score,
            "recommendation": self.recommendation,
            "user_override": self.user_override,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CoherenceTrace:
        return cls(
            trace_id=data["trace_id"],
            demand_id=data["demand_id"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            identity_hash=data["identity_hash"],
            checks=[CoherenceCheck.from_dict(c) for c in data.get("checks", [])],
            final_score=data.get("final_score", 0.0),
            recommendation=data.get("recommendation", "defer"),
            user_override=data.get("user_override"),
        )


# =============================================================================
# Coherence Verifier
# =============================================================================


class CoherenceVerifier:
    """Recursive coherence verification engine.

    Mirrors RIVA's work() pattern but for identity coherence.
    Core algorithm:
    1. Check anti-patterns (fast rejection, no LLM)
    2. If demand is simple, verify directly against identity
    3. If demand is complex, decompose and verify sub-demands
    4. Aggregate results and recommend action

    Attributes:
        identity: The identity model to verify against
        llm: Optional LLM provider for complex verifications
        max_depth: Maximum recursion depth for decomposition
    """

    def __init__(
        self,
        identity: IdentityModel,
        llm: "LLMProvider | None" = None,
        max_depth: int = 3,
    ):
        self.identity = identity
        self.llm = llm
        self.max_depth = max_depth

    def verify(self, demand: AttentionDemand, depth: int = 0) -> CoherenceResult:
        """Recursively verify if demand coheres with identity.

        Core principle: If you can't verify coherence, decompose the demand.

        Args:
            demand: The attention demand to verify
            depth: Current recursion depth

        Returns:
            CoherenceResult with score, recommendation, and audit trace
        """
        trace = [f"Starting verification for: {demand.content[:50]}..."]

        # 1. Quick rejection via anti-patterns (no LLM needed)
        anti_match = self._matches_anti_pattern(demand)
        if anti_match:
            trace.append(f"Anti-pattern match: {anti_match}")
            logger.info("Demand rejected by anti-pattern: %s", anti_match)
            return CoherenceResult(
                demand=demand,
                checks=[],
                overall_score=-1.0,
                recommendation="reject",
                trace=trace,
            )

        # 2. Check if simple enough to verify directly
        if self._can_verify_directly(demand):
            trace.append("Demand is simple, verifying directly")
            return self._direct_verification(demand, trace)

        # 3. If complex, decompose into sub-demands and verify each
        if depth < self.max_depth:
            trace.append(f"Demand is complex, decomposing (depth={depth})")
            sub_demands = self._decompose(demand)

            if sub_demands:
                demand.sub_demands = sub_demands
                sub_results = [self.verify(sd, depth + 1) for sd in sub_demands]
                return self._aggregate_results(demand, sub_results, trace)

        # 4. At max depth or can't decompose, do best-effort verification
        trace.append("Max depth reached or cannot decompose, best-effort verification")
        return self._direct_verification(demand, trace)

    def _matches_anti_pattern(self, demand: AttentionDemand) -> str | None:
        """Check if demand matches any anti-pattern.

        Returns the matching pattern if found, None otherwise.
        This is a fast-path rejection that avoids LLM calls.
        """
        content_lower = demand.content.lower()
        source_lower = demand.source.lower()

        for pattern in self.identity.anti_patterns:
            pattern_lower = pattern.lower()
            if pattern_lower in content_lower or pattern_lower in source_lower:
                return pattern

        return None

    def _can_verify_directly(self, demand: AttentionDemand) -> bool:
        """Check if demand is simple enough to verify without decomposition.

        Heuristics (mirror RIVA's can_verify_directly):
        - Short content (single observable need)
        - No compound structures (and, also, multiple)
        - Clear, specific request
        """
        content = demand.content

        # Very short demands are directly verifiable
        if len(content) < 100:
            return True

        # Compound indicators suggest decomposition
        compound_words = ["and", "also", "additionally", "plus", "multiple", "several"]
        compound_count = sum(1 for w in compound_words if f" {w} " in content.lower())
        if compound_count >= 2:
            return False

        # Long, complex demands need decomposition
        if len(content) > 300:
            return False

        return True

    def _direct_verification(
        self,
        demand: AttentionDemand,
        trace: list[str],
    ) -> CoherenceResult:
        """Verify demand directly against identity facets.

        Uses LLM if available for nuanced checking, otherwise heuristics.
        """
        checks: list[CoherenceCheck] = []

        # Check against core identity
        core_check = self._check_against_core(demand)
        checks.append(core_check)
        trace.append(f"Core identity check: {core_check.alignment:.2f}")

        # Check against relevant facets
        keywords = self._extract_keywords(demand.content)
        relevant_facets = self.identity.get_relevant_facets(keywords)

        for facet in relevant_facets[:3]:  # Limit to top 3 relevant facets
            facet_check = self._check_against_facet(demand, facet)
            checks.append(facet_check)
            trace.append(f"Facet '{facet.name}' check: {facet_check.alignment:.2f}")

        # Aggregate scores
        if checks:
            # Weight core identity higher
            weighted_sum = checks[0].alignment * 2.0  # Core weight = 2
            total_weight = 2.0
            for check in checks[1:]:
                weighted_sum += check.alignment
                total_weight += 1.0
            overall_score = weighted_sum / total_weight
        else:
            overall_score = 0.0

        # Determine recommendation based on score
        recommendation = self._score_to_recommendation(overall_score)
        trace.append(f"Final score: {overall_score:.2f}, recommendation: {recommendation}")

        demand.coherence_score = overall_score

        return CoherenceResult(
            demand=demand,
            checks=checks,
            overall_score=overall_score,
            recommendation=recommendation,
            trace=trace,
        )

    def _check_against_core(self, demand: AttentionDemand) -> CoherenceCheck:
        """Check demand against core identity (me.md)."""
        if self.llm:
            return self._llm_coherence_check(demand, "core", self.identity.core)

        # Heuristic: keyword overlap
        return self._heuristic_coherence_check(demand, "core", self.identity.core)

    def _check_against_facet(
        self,
        demand: AttentionDemand,
        facet: IdentityFacet,
    ) -> CoherenceCheck:
        """Check demand against a specific identity facet."""
        if self.llm:
            return self._llm_coherence_check(demand, facet.name, facet.content)

        return self._heuristic_coherence_check(demand, facet.name, facet.content)

    def _llm_coherence_check(
        self,
        demand: AttentionDemand,
        facet_name: str,
        facet_content: str,
    ) -> CoherenceCheck:
        """Use LLM to assess coherence between demand and identity facet."""
        system_prompt = """You are assessing whether an attention demand aligns with a person's identity.

Score the alignment from -1.0 (directly opposes identity) to 1.0 (perfectly aligned).
- 1.0: Demand directly supports stated values/goals
- 0.5: Demand is compatible with identity
- 0.0: Demand is neutral, no clear connection
- -0.5: Demand conflicts with some aspects
- -1.0: Demand directly opposes core values

Respond with ONLY a JSON object:
{
  "alignment": <float from -1.0 to 1.0>,
  "reasoning": "<brief explanation>"
}"""

        user_prompt = f"""Assess alignment between this attention demand and identity facet:

ATTENTION DEMAND:
Source: {demand.source}
Content: {demand.content}

IDENTITY FACET ({facet_name}):
{facet_content[:1000]}

How well does this demand align with the person's identity?"""

        try:
            response = self.llm.chat_json(
                system=system_prompt,
                user=user_prompt,
                timeout_seconds=15.0,
            )

            # Parse response
            from reos.code_mode.json_utils import parse_llm_json
            data = parse_llm_json(response)

            alignment = float(data.get("alignment", 0.0))
            alignment = max(-1.0, min(1.0, alignment))  # Clamp
            reasoning = data.get("reasoning", "LLM assessment")

            return CoherenceCheck(
                facet_checked=facet_name,
                demand_aspect=demand.content[:50],
                alignment=alignment,
                reasoning=reasoning,
            )

        except Exception as e:
            logger.warning("LLM coherence check failed: %s, using heuristic", e)
            return self._heuristic_coherence_check(demand, facet_name, facet_content)

    def _heuristic_coherence_check(
        self,
        demand: AttentionDemand,
        facet_name: str,
        facet_content: str,
    ) -> CoherenceCheck:
        """Heuristic coherence check when LLM unavailable."""
        demand_lower = demand.content.lower()
        facet_lower = facet_content.lower()

        # Simple keyword overlap
        demand_words = set(demand_lower.split())
        facet_words = set(facet_lower.split())

        # Filter common words
        stopwords = {"the", "a", "an", "is", "are", "was", "were", "be", "been",
                    "being", "have", "has", "had", "do", "does", "did", "will",
                    "would", "could", "should", "may", "might", "must", "can",
                    "to", "of", "in", "for", "on", "with", "at", "by", "from",
                    "as", "into", "through", "during", "before", "after", "and",
                    "but", "or", "if", "while", "about", "against", "between"}

        demand_words = demand_words - stopwords
        facet_words = facet_words - stopwords

        if not demand_words or not facet_words:
            alignment = 0.0
            reasoning = "Insufficient content for comparison"
        else:
            overlap = len(demand_words & facet_words)
            total = len(demand_words)
            overlap_ratio = overlap / total if total > 0 else 0

            # Convert overlap to alignment score
            # 0% overlap -> 0.0, 50% overlap -> 0.5, 100% overlap -> 1.0
            alignment = min(overlap_ratio * 2, 1.0)
            reasoning = f"Keyword overlap: {overlap}/{total} words ({overlap_ratio:.0%})"

        return CoherenceCheck(
            facet_checked=facet_name,
            demand_aspect=demand.content[:50],
            alignment=alignment,
            reasoning=reasoning,
        )

    def _decompose(self, demand: AttentionDemand) -> list[AttentionDemand]:
        """Break complex demand into simpler sub-demands."""
        if self.llm:
            return self._llm_decompose(demand)
        return self._heuristic_decompose(demand)

    def _llm_decompose(self, demand: AttentionDemand) -> list[AttentionDemand]:
        """Use LLM to decompose complex demand."""
        system_prompt = """You are breaking down a complex attention demand into simpler parts.

Each part should be:
1. A single, clear request
2. Independently assessable
3. Together, covering the original demand

Respond with ONLY a JSON array of strings, each being a sub-demand.
Example: ["Check email from boss", "Review project deadline", "Update team on status"]"""

        user_prompt = f"""Break this attention demand into simpler parts:

SOURCE: {demand.source}
CONTENT: {demand.content}

What are the distinct requests or needs within this demand?"""

        try:
            response = self.llm.chat_json(
                system=system_prompt,
                user=user_prompt,
                timeout_seconds=15.0,
            )

            from reos.code_mode.json_utils import parse_llm_json
            parts = parse_llm_json(response)

            sub_demands = []
            for part in parts:
                if isinstance(part, str) and part.strip():
                    sub_demands.append(AttentionDemand.create(
                        source=demand.source,
                        content=part.strip(),
                        urgency=demand.urgency,
                    ))

            return sub_demands

        except Exception as e:
            logger.warning("LLM decomposition failed: %s, using heuristic", e)
            return self._heuristic_decompose(demand)

    def _heuristic_decompose(self, demand: AttentionDemand) -> list[AttentionDemand]:
        """Heuristic decomposition when LLM unavailable."""
        content = demand.content

        # Try splitting on common separators
        parts = []
        for sep in [" and ", ". ", "; ", " also "]:
            if sep in content.lower():
                parts = [p.strip() for p in content.split(sep) if p.strip()]
                if len(parts) > 1:
                    break

        if len(parts) > 1:
            return [
                AttentionDemand.create(
                    source=demand.source,
                    content=part,
                    urgency=demand.urgency,
                )
                for part in parts
            ]

        # Can't decompose further
        return []

    def _aggregate_results(
        self,
        demand: AttentionDemand,
        sub_results: list[CoherenceResult],
        trace: list[str],
    ) -> CoherenceResult:
        """Aggregate sub-demand results into parent result."""
        if not sub_results:
            trace.append("No sub-results to aggregate")
            return CoherenceResult(
                demand=demand,
                checks=[],
                overall_score=0.0,
                recommendation="defer",
                trace=trace,
            )

        # Collect all checks
        all_checks = []
        for result in sub_results:
            all_checks.extend(result.checks)

        # Average scores
        scores = [r.overall_score for r in sub_results]
        overall_score = sum(scores) / len(scores)

        # Recommendation based on sub-results
        # If any sub-demand should be rejected, consider rejection
        # If all are coherent, accept
        reject_count = sum(1 for r in sub_results if r.recommendation == "reject")
        accept_count = sum(1 for r in sub_results if r.recommendation == "accept")

        if reject_count > len(sub_results) / 2:
            recommendation: CoherenceRecommendation = "reject"
        elif accept_count == len(sub_results):
            recommendation = "accept"
        elif overall_score > 0.3:
            recommendation = "accept"
        elif overall_score < -0.3:
            recommendation = "reject"
        else:
            recommendation = "defer"

        trace.append(f"Aggregated {len(sub_results)} sub-results: score={overall_score:.2f}")
        demand.coherence_score = overall_score

        return CoherenceResult(
            demand=demand,
            checks=all_checks,
            overall_score=overall_score,
            recommendation=recommendation,
            trace=trace,
        )

    def _score_to_recommendation(self, score: float) -> CoherenceRecommendation:
        """Convert coherence score to recommendation."""
        if score >= 0.5:
            return "accept"
        elif score >= 0.0:
            return "defer"  # Neutral, let user decide
        elif score >= -0.5:
            return "defer"  # Slightly negative, still user choice
        else:
            return "reject"  # Strongly incoherent

    def _extract_keywords(self, text: str) -> list[str]:
        """Extract meaningful keywords from text."""
        import re

        # Common words to filter out
        stopwords = {"the", "a", "an", "is", "are", "was", "were", "be", "been",
                    "being", "have", "has", "had", "do", "does", "did", "will",
                    "would", "could", "should", "may", "might", "must", "can",
                    "to", "of", "in", "for", "on", "with", "at", "by", "from",
                    "as", "into", "through", "during", "before", "after", "and",
                    "but", "or", "if", "while", "about", "against", "between",
                    "i", "me", "my", "you", "your", "we", "our", "they", "their",
                    "this", "that", "these", "those", "it", "its"}

        words = re.findall(r'\b[a-zA-Z]{3,}\b', text.lower())
        keywords = [w for w in words if w not in stopwords]

        # Dedupe while preserving order
        seen = set()
        result = []
        for kw in keywords:
            if kw not in seen:
                seen.add(kw)
                result.append(kw)

        return result[:10]  # Limit to 10 keywords
