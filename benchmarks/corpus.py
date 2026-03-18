"""Corpus loader for the ReOS benchmark framework.

Loads test cases from corpus.json into typed TestCase dataclasses.
Supports filtering by category, difficulty, safety level, and case IDs.
"""

import json
from dataclasses import dataclass
from pathlib import Path

CORPUS_PATH = Path(__file__).parent / "corpus.json"
TOP50_CORPUS_PATH = Path(__file__).parent / "corpus_top50.json"

# Frequency weights: how often real users perform tasks in each category.
# Scale 1-5: 1=rare, 2=weekly, 3=daily, 4=multiple-times-daily, 5=constant
CATEGORY_WEIGHTS: dict[str, float] = {
    "files": 5.0,              # ls, cp, mv, rm — constant use
    "text": 4.0,               # grep, cat, head, tail — very frequent
    "process": 4.0,            # ps, kill, top — very frequent
    "system_monitoring": 3.0,  # df, free, uptime — daily
    "services": 3.0,           # systemctl — daily
    "package_management": 2.5, # apt install — a few times a week
    "network": 2.5,            # ping, curl, ip — a few times a week
    "disk": 2.0,               # mount, fdisk — weekly
    "users": 1.5,              # useradd, passwd — occasional
    "scheduling": 1.5,         # cron — occasional
    "terminal": 2.0,           # clear, history — daily but simple
    "pipeline": 3.0,           # pipes, redirection — daily
    "natural_variants": 3.0,   # natural phrasing — represents real usage
    "dangerous": 1.0,          # rm -rf / — should be rare!
    "edge_cases": 1.0,         # misspellings, vague — happens but low priority
    "ssh": 2.5,                # ssh, scp, rsync — a few times a week
    "compression": 2.0,        # tar, zip — weekly
}


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


def get_case_weight(case: "TestCase") -> float:
    """Return the frequency weight for a test case based on its category.

    Args:
        case: A TestCase whose category is used to look up its weight.

    Returns:
        A float weight from CATEGORY_WEIGHTS, or 1.0 if category is unknown.
    """
    return CATEGORY_WEIGHTS.get(case.category, 1.0)


def load_corpus(
    category: str | None = None,
    difficulty: str | None = None,
    safety_level: str | None = None,
    case_ids: list[str] | None = None,
    corpus_file: Path | None = None,
) -> list[TestCase]:
    """Load test cases from corpus.json (or an alternate file) with optional filtering.

    Args:
        category: Filter to a specific category (e.g. "files", "network").
        difficulty: Filter to a specific difficulty ("simple", "moderate", "complex", "expert").
        safety_level: Filter to a specific safety level ("safe", "soft_risky", "hard_blocked").
        case_ids: Filter to a specific list of case IDs.
        corpus_file: Path to the corpus JSON file.  Defaults to corpus.json.
            Pass TOP50_CORPUS_PATH (or any Path) to load an alternate corpus.

    Returns:
        List of TestCase dataclasses matching all supplied filters.
    """
    source = corpus_file if corpus_file is not None else CORPUS_PATH
    raw: list[dict] = json.loads(source.read_text(encoding="utf-8"))

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


def summarize_corpus(corpus_file: Path | None = None) -> dict[str, int]:
    """Return a dict mapping category name → case count for the given corpus.

    Args:
        corpus_file: Path to the corpus JSON file.  Defaults to corpus.json.
    """
    cases = load_corpus(corpus_file=corpus_file)
    counts: dict[str, int] = {}
    for c in cases:
        counts[c.category] = counts.get(c.category, 0) + 1
    return dict(sorted(counts.items()))
