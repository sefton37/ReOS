"""Corpus loader for the ReOS benchmark framework.

Loads test cases from corpus.json into typed TestCase dataclasses.
Supports filtering by category, difficulty, safety level, and case IDs.
"""

import json
from dataclasses import dataclass
from pathlib import Path

CORPUS_PATH = Path(__file__).parent / "corpus.json"


@dataclass
class TestCase:
    """A single benchmark test case from corpus.json."""

    case_id: str
    prompt: str
    category: str
    subcategory: str | None
    difficulty: str  # simple | moderate | complex | expert
    expected_behavior: str  # command | explanation_only | refuse | clarify
    expected_command: str | None
    expected_command_alts: list[str] | None
    safety_level: str  # safe | soft_risky | hard_blocked
    soft_risky_reason: str | None
    notes: str | None


def load_corpus(
    category: str | None = None,
    difficulty: str | None = None,
    safety_level: str | None = None,
    case_ids: list[str] | None = None,
) -> list[TestCase]:
    """Load test cases from corpus.json with optional filtering.

    Args:
        category: Filter to a specific category (e.g. "files", "network").
        difficulty: Filter to a specific difficulty ("simple", "moderate", "complex", "expert").
        safety_level: Filter to a specific safety level ("safe", "soft_risky", "hard_blocked").
        case_ids: Filter to a specific list of case IDs.

    Returns:
        List of TestCase dataclasses matching all supplied filters.
    """
    raw: list[dict] = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))

    cases: list[TestCase] = []
    for item in raw:
        tc = TestCase(
            case_id=item["case_id"],
            prompt=item["prompt"],
            category=item["category"],
            subcategory=item.get("subcategory"),
            difficulty=item["difficulty"],
            expected_behavior=item["expected_behavior"],
            expected_command=item.get("expected_command"),
            expected_command_alts=item.get("expected_command_alts"),
            safety_level=item["safety_level"],
            soft_risky_reason=item.get("soft_risky_reason"),
            notes=item.get("notes"),
        )
        cases.append(tc)

    if category is not None:
        cases = [c for c in cases if c.category == category]
    if difficulty is not None:
        cases = [c for c in cases if c.difficulty == difficulty]
    if safety_level is not None:
        cases = [c for c in cases if c.safety_level == safety_level]
    if case_ids is not None:
        id_set = set(case_ids)
        cases = [c for c in cases if c.case_id in id_set]

    return cases


def summarize_corpus() -> dict[str, int]:
    """Return a dict mapping category name → case count for the full corpus."""
    cases = load_corpus()
    counts: dict[str, int] = {}
    for c in cases:
        counts[c.category] = counts.get(c.category, 0) + 1
    return dict(sorted(counts.items()))
