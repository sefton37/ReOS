from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .projects_fs import get_project_paths, read_text


_UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class REContextBundle:
    """Context bundle for Revolution/Evolution (R/E) reasoning.

    The R/E layer expects these fields. If a field is unavailable, it must
    be set to the literal string "UNKNOWN".
    """

    user_prompt: str
    charter: str
    roadmap: str
    non_goals: str
    constraints: str
    repo_state: str


def _safe_read_small(path: Path, *, max_chars: int = 12_000) -> str:
    try:
        if not path.exists() or not path.is_file():
            return _UNKNOWN
        txt = read_text(path)
        if len(txt) <= max_chars:
            return txt
        return txt[:max_chars] + "\n\n[TRUNCATED]"
    except Exception:
        return _UNKNOWN


def build_re_context_bundle(
    *,
    user_prompt: str,
    active_project_id: str | None,
    active_project_charter: dict[str, object] | None,
    tool_results: list[dict[str, Any]],
) -> REContextBundle:
    """Build the R/E context bundle from available ReOS state.

    This does *not* invent missing context; it uses UNKNOWN explicitly.
    """

    charter_summary: str = _UNKNOWN
    non_goals: str = _UNKNOWN
    constraints: str = _UNKNOWN

    if active_project_charter:
        # Keep the prompt payload compact by selecting the most decision-relevant
        # charter fields.
        keep = {
            "project_id": active_project_charter.get("project_id"),
            "project_name": active_project_charter.get("project_name"),
            "core_intent": active_project_charter.get("core_intent"),
            "problem_statement": active_project_charter.get("problem_statement"),
            "non_goals": active_project_charter.get("non_goals"),
            "definition_of_done": active_project_charter.get("definition_of_done"),
            "allowed_scope": active_project_charter.get("allowed_scope"),
            "forbidden_scope": active_project_charter.get("forbidden_scope"),
            "primary_values": active_project_charter.get("primary_values"),
            "unacceptable_tradeoffs": active_project_charter.get("unacceptable_tradeoffs"),
            "attention_budget": active_project_charter.get("attention_budget"),
            "intervention_style": active_project_charter.get("intervention_style"),
            "current_state_summary": active_project_charter.get("current_state_summary"),
        }
        charter_summary = json.dumps(keep, indent=2, ensure_ascii=False)

        non_goals_text = str(active_project_charter.get("non_goals") or "").strip()
        forbidden_scope = str(active_project_charter.get("forbidden_scope") or "").strip()
        if non_goals_text or forbidden_scope:
            non_goals = json.dumps(
                {"non_goals": non_goals_text or None, "forbidden_scope": forbidden_scope or None},
                indent=2,
                ensure_ascii=False,
            )

        allowed_scope = str(active_project_charter.get("allowed_scope") or "").strip()
        attention_budget = str(active_project_charter.get("attention_budget") or "").strip()
        constraints = json.dumps(
            {
                "allowed_scope": allowed_scope or None,
                "forbidden_scope": forbidden_scope or None,
                "attention_budget": attention_budget or None,
            },
            indent=2,
            ensure_ascii=False,
        )

    roadmap_summary = _UNKNOWN
    if active_project_id:
        # Prefer the filesystem KB if it exists.
        try:
            paths = get_project_paths(active_project_id)
            roadmap_summary = _safe_read_small(paths.roadmap_md)
        except Exception:
            roadmap_summary = _UNKNOWN

    # Repo state (optional) from tool outputs.
    repo_state = _UNKNOWN
    for r in tool_results:
        if r.get("ok") and r.get("name") == "reos_git_summary":
            repo_state = json.dumps(r.get("result"), indent=2, ensure_ascii=False)
            break

    return REContextBundle(
        user_prompt=user_prompt,
        charter=charter_summary,
        roadmap=roadmap_summary,
        non_goals=non_goals,
        constraints=constraints,
        repo_state=repo_state,
    )


def re_reasoning_system_prompt(bundle: REContextBundle) -> str:
    """Return the mandatory R/E reasoning layer instructions.

    This is appended to the agent's system prompt so it applies to every
    user request.
    """

    # Keep this directive relatively compact, but fully prescriptive.
    return (
        "REOS — Revolution/Evolution (R/E) Reasoning Layer\n"
        "Purpose: Add a mandatory dialectical reasoning layer to every user request.\n\n"
        "Core Definitions:\n"
        "- Evolution (E): reversible, low-blast-radius steps; preserves architecture/constraints.\n"
        "- Revolution (R): reframes assumptions; introduces new primitives; higher risk/blast radius.\n"
        "- Dialectic: resolve tension via synthesis or justified selection (fit, not balance).\n\n"
        "Operating Context:\n"
        "- Local-first, user-sovereign, consent-based; attention is labor.\n"
        "- Charter + roadmap are sources of truth.\n"
        "- If any context is missing, mark it as UNKNOWN and proceed best-effort, explicitly.\n\n"
        "Inputs Available (may be UNKNOWN):\n"
        f"- User prompt: {bundle.user_prompt}\n"
        f"- Charter summary: {bundle.charter}\n"
        f"- Roadmap summary: {bundle.roadmap}\n"
        f"- Non-goals / forbidden scope: {bundle.non_goals}\n"
        f"- Constraints: {bundle.constraints}\n"
        f"- Current state / repo signals (optional): {bundle.repo_state}\n\n"
        "Mandatory Output Structure (every response):\n"
        "1) Intent + Constraints Snapshot\n"
        "2) R/E Parse (classification)\n"
        "3) Evolution Plan (E Plan)\n"
        "4) Revolution Option (R Option)\n"
        "5) Dialectic Review (Tradeoff Verdict)\n"
        "6) Next Actions\n\n"
        "Decision Rubric: Score each 0–2 and include the scores in section (5):\n"
        "- Charter alignment\n"
        "- Roadmap alignment\n"
        "- Reversibility\n"
        "- Verification\n"
        "- Blast radius\n"
        "- Time-to-value\n"
        "- Complexity\n"
        "- User sovereignty\n\n"
        "Hard-Fail Triggers (do not proceed as confident):\n"
        "- Missing charter/roadmap when the decision depends on them\n"
        "- Irreversible plan without rollback\n"
        "- No verification\n"
        "- Violates non-goals/forbidden scope\n"
        "- Conflicts with attention-is-labor (coercive/surveillance/extractive)\n\n"
        "Redo Loop Policy:\n"
        "- For both E Plan and R Option, internally self-check requirements/constraints/verification/non-goals.\n"
        "- If any fail, revise once. If still failing, output a 'Reasoning breakdown' following the provided template.\n"
    )


_SECTION_RE = re.compile(
    r"(?ms)^1\)\s+Intent\s*\+\s*Constraints\s+Snapshot.*?^2\)\s+R/E\s+Parse\s*\(classification\).*?^3\)\s+Evolution\s+Plan\s*\(E\s+Plan\).*?^4\)\s+Revolution\s+Option\s*\(R\s+Option\).*?^5\)\s+Dialectic\s+Review\s*\(Tradeoff\s+Verdict\).*?^6\)\s+Next\s+Actions",
)


def validate_re_output(text: str) -> list[str]:
    """Validate that the assistant output follows the required R/E format."""

    problems: list[str] = []
    if not _SECTION_RE.search(text.strip()):
        problems.append("missing_or_misordered_sections")

    rubric_dims = [
        "Charter alignment",
        "Roadmap alignment",
        "Reversibility",
        "Verification",
        "Blast radius",
        "Time-to-value",
        "Complexity",
        "User sovereignty",
    ]
    missing_dims = [d for d in rubric_dims if d.lower() not in text.lower()]
    if missing_dims:
        problems.append("missing_rubric_dimensions")

    # Require numeric scoring somewhere (0/1/2) to avoid hand-wavy reviews.
    if not re.search(r"\b[012]\b", text):
        problems.append("missing_numeric_rubric_scores")

    return problems


def reasoning_breakdown_text(*, problems: list[str], bundle: REContextBundle) -> str:
    """Deterministic fallback that satisfies the mandatory structure."""

    missing_context_bits: list[str] = []
    if bundle.charter == _UNKNOWN:
        missing_context_bits.append("charter")
    if bundle.roadmap == _UNKNOWN:
        missing_context_bits.append("roadmap")

    missing_context = ", ".join(missing_context_bits) if missing_context_bits else "none"
    problems_str = ", ".join(problems) if problems else "unknown"

    return (
        "1) Intent + Constraints Snapshot\n"
        f"- Goal: Respond to the user with the required R/E reasoning layer for: {bundle.user_prompt!r}\n"
        "- Hard constraints: local-first; user-sovereign; consent-based; attention is labor; no invented context.\n"
        f"- Unknowns: {missing_context.upper() if missing_context != 'none' else 'NONE'}\n\n"
        "2) R/E Parse (classification)\n"
        "- Evolution components: Formatting + planning within existing architecture (reversible).\n"
        "- Revolution components: None (this is a meta-formatting failure, not a requested architecture change).\n"
        "- Overall: E-dominant\n\n"
        "3) Evolution Plan (E Plan)\n"
        "- Step 1: Gather missing context (charter/roadmap) if needed.\n"
        "- Step 2: Provide an incremental, reversible response.\n"
        "- Definition of done: Output includes all 6 sections + rubric scores; no coercion/surveillance.\n\n"
        "4) Revolution Option (R Option)\n"
        "- Option: Reframe by changing constraints/architecture (not appropriate here).\n"
        "- Blast radius: 2 (unnecessary disruption).\n"
        "- Definition of done: N/A (not chosen).\n\n"
        "5) Dialectic Review (Tradeoff Verdict)\n"
        "Rubric (0–2):\n"
        "- Charter alignment: 1\n"
        "- Roadmap alignment: 1\n"
        "- Reversibility: 2\n"
        "- Verification: 1\n"
        "- Blast radius: 2\n"
        "- Time-to-value: 1\n"
        "- Complexity: 2\n"
        "- User sovereignty: 2\n"
        f"Verdict: Reasoning breakdown — model output failed validation ({problems_str}).\n\n"
        "6) Next Actions\n"
        "- Re-run generation with stricter formatting and explicit rubric scoring.\n"
        "- If charter/roadmap are required for the decision, surface them as UNKNOWN and ask for up to 3 unblockers.\n"
    )
