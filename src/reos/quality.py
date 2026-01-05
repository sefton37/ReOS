"""Quality Commitment Framework for ReOS.

Ensures the LLM produces high-quality, well-engineered, maintainable output
by enforcing reasoning transparency, engineering standards, and quality gates.

This module implements the "Quality Promise" - a commitment that every decision
and action will be:
- Well-reasoned with transparent justification
- Engineered to best practices
- Maintainable and documented
- Verified for correctness
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


# =============================================================================
# Core Data Structures
# =============================================================================

class QualityLevel(Enum):
    """Quality assessment levels."""
    EXCELLENT = "excellent"      # Exemplary engineering
    GOOD = "good"                # Meets all standards
    ACCEPTABLE = "acceptable"    # Meets minimum standards
    NEEDS_IMPROVEMENT = "needs_improvement"  # Below standards
    POOR = "poor"                # Significantly below standards


class DecisionType(Enum):
    """Types of decisions the LLM makes."""
    TOOL_SELECTION = "tool_selection"
    COMMAND_CONSTRUCTION = "command_construction"
    PLAN_CREATION = "plan_creation"
    ERROR_RECOVERY = "error_recovery"
    RESOURCE_IDENTIFICATION = "resource_identification"
    APPROACH_SELECTION = "approach_selection"


@dataclass
class ReasoningStep:
    """A single step in the chain of thought."""
    step_number: int
    description: str
    rationale: str
    alternatives_considered: list[str] = field(default_factory=list)
    why_chosen: str = ""
    confidence: float = 1.0


@dataclass
class ReasoningChain:
    """Complete chain of thought for a decision."""
    decision_type: DecisionType
    goal: str
    context: str
    steps: list[ReasoningStep] = field(default_factory=list)
    conclusion: str = ""
    quality_score: float = 0.0
    timestamp: datetime = field(default_factory=datetime.now)

    def add_step(
        self,
        description: str,
        rationale: str,
        alternatives: list[str] | None = None,
        why_chosen: str = "",
        confidence: float = 1.0,
    ) -> ReasoningStep:
        """Add a reasoning step to the chain."""
        step = ReasoningStep(
            step_number=len(self.steps) + 1,
            description=description,
            rationale=rationale,
            alternatives_considered=alternatives or [],
            why_chosen=why_chosen,
            confidence=confidence,
        )
        self.steps.append(step)
        return step

    def to_audit_string(self) -> str:
        """Format as human-readable audit trail."""
        lines = [
            f"=== REASONING CHAIN: {self.decision_type.value} ===",
            f"Goal: {self.goal}",
            f"Context: {self.context}",
            "",
        ]
        for step in self.steps:
            lines.append(f"Step {step.step_number}: {step.description}")
            lines.append(f"  Rationale: {step.rationale}")
            if step.alternatives_considered:
                lines.append(f"  Alternatives: {', '.join(step.alternatives_considered)}")
                lines.append(f"  Why chosen: {step.why_chosen}")
            lines.append(f"  Confidence: {step.confidence:.0%}")
            lines.append("")

        lines.append(f"Conclusion: {self.conclusion}")
        lines.append(f"Quality Score: {self.quality_score:.0%}")
        return "\n".join(lines)


@dataclass
class QualityAssessment:
    """Assessment of quality for an operation or output."""
    level: QualityLevel
    score: float  # 0.0 to 1.0
    strengths: list[str] = field(default_factory=list)
    weaknesses: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    reasoning_chain: ReasoningChain | None = None

    def is_acceptable(self) -> bool:
        """Check if quality meets minimum standards."""
        return self.level in (QualityLevel.EXCELLENT, QualityLevel.GOOD, QualityLevel.ACCEPTABLE)


@dataclass
class QualityGateResult:
    """Result of a quality gate check."""
    gate_name: str
    passed: bool
    message: str
    details: dict[str, Any] = field(default_factory=dict)
    blocking: bool = True  # If True, failure blocks execution


# =============================================================================
# Reasoning Transparency - Chain of Thought Auditing
# =============================================================================

class ReasoningAuditor:
    """Audits and logs the LLM's reasoning process.

    Ensures every significant decision has:
    - Clear goal statement
    - Step-by-step reasoning
    - Alternatives considered
    - Justification for chosen approach
    """

    def __init__(self):
        self._chains: list[ReasoningChain] = []
        self._current_chain: ReasoningChain | None = None
        self._max_chains = 100  # Bounded storage

    def start_reasoning(
        self,
        decision_type: DecisionType,
        goal: str,
        context: str,
    ) -> ReasoningChain:
        """Start a new reasoning chain for a decision."""
        chain = ReasoningChain(
            decision_type=decision_type,
            goal=goal,
            context=context,
        )
        self._current_chain = chain
        logger.debug("Started reasoning chain: %s - %s", decision_type.value, goal)
        return chain

    def add_step(
        self,
        description: str,
        rationale: str,
        alternatives: list[str] | None = None,
        why_chosen: str = "",
        confidence: float = 1.0,
    ) -> ReasoningStep | None:
        """Add a step to the current reasoning chain."""
        if self._current_chain is None:
            logger.warning("No active reasoning chain")
            return None

        return self._current_chain.add_step(
            description=description,
            rationale=rationale,
            alternatives=alternatives,
            why_chosen=why_chosen,
            confidence=confidence,
        )

    def conclude_reasoning(
        self,
        conclusion: str,
        quality_score: float = 0.0,
    ) -> ReasoningChain | None:
        """Conclude the current reasoning chain."""
        if self._current_chain is None:
            logger.warning("No active reasoning chain to conclude")
            return None

        self._current_chain.conclusion = conclusion
        self._current_chain.quality_score = quality_score

        # Store and log
        self._chains.append(self._current_chain)
        if len(self._chains) > self._max_chains:
            self._chains = self._chains[-self._max_chains:]

        logger.info(
            "REASONING: %s | goal=%s | conclusion=%s | quality=%.0f%%",
            self._current_chain.decision_type.value,
            self._current_chain.goal[:50],
            conclusion[:50],
            quality_score * 100,
        )

        chain = self._current_chain
        self._current_chain = None
        return chain

    def get_recent_chains(self, limit: int = 10) -> list[ReasoningChain]:
        """Get recent reasoning chains for audit."""
        return self._chains[-limit:]

    def explain_decision(self, chain: ReasoningChain) -> str:
        """Generate human-readable explanation of a decision."""
        return chain.to_audit_string()


# =============================================================================
# Engineering Standards
# =============================================================================

@dataclass
class EngineeringStandard:
    """A single engineering standard/best practice."""
    name: str
    description: str
    check_fn: str  # Name of method to check this standard
    severity: str  # "error", "warning", "info"
    category: str  # "security", "maintainability", "efficiency", "correctness"


class EngineeringStandardsChecker:
    """Enforces engineering best practices.

    Checks that operations follow:
    - Idempotency principles
    - Least privilege
    - Explicit over implicit
    - Fail-fast patterns
    - Documentation requirements
    """

    # Standard patterns that indicate good engineering
    GOOD_PATTERNS = {
        "idempotent": [
            r"--force",           # Allows re-running
            r"--exist-ok",        # Handles existing resources
            r"if\s+not\s+exists", # SQL idempotency
            r"CREATE\s+.*IF\s+NOT\s+EXISTS",
        ],
        "explicit": [
            r"--yes",             # Explicit confirmation bypass
            r"--no-interaction",  # Explicit non-interactive
            r"-y\b",              # Explicit yes
        ],
        "documented": [
            r"#.*TODO",           # Has TODOs marked
            r"#.*NOTE",           # Has notes
            r"--help",            # Help checked
        ],
    }

    # Patterns that indicate poor engineering
    BAD_PATTERNS = {
        "implicit_state": [
            (r"cd\s+\S+\s*&&", "Implicit directory state - prefer absolute paths"),
            (r"export\s+\S+=", "Implicit environment modification - may affect other processes"),
        ],
        "fragile": [
            (r"\|\|\s*true", "Silently ignoring errors - failures should be explicit"),
            (r"2>/dev/null", "Silently discarding errors - may hide important issues"),
            (r"set\s+\+e", "Disabling error exit - errors should stop execution"),
        ],
        "unmaintainable": [
            (r"[a-f0-9]{32,}", "Hardcoded hash/ID - should be parameterized"),
            (r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}", "Hardcoded IP - should use DNS/config"),
        ],
        "inefficient": [
            (r"cat\s+\S+\s*\|\s*grep", "Useless cat - grep can read files directly"),
            (r"echo\s+.*\|\s*cat", "Useless echo/cat pipeline"),
        ],
    }

    def __init__(self):
        self._violations: list[dict[str, Any]] = []

    def check_command(self, command: str) -> QualityAssessment:
        """Check a command against engineering standards."""
        strengths = []
        weaknesses = []
        suggestions = []
        score = 1.0

        # Check for good patterns
        for category, patterns in self.GOOD_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, command, re.IGNORECASE):
                    strengths.append(f"Uses {category} pattern")
                    break

        # Check for bad patterns
        for category, patterns in self.BAD_PATTERNS.items():
            for pattern, message in patterns:
                if re.search(pattern, command, re.IGNORECASE):
                    weaknesses.append(message)
                    score -= 0.15
                    self._violations.append({
                        "category": category,
                        "pattern": pattern,
                        "message": message,
                        "command": command[:100],
                    })

        # Check command complexity
        pipe_count = command.count("|")
        if pipe_count > 3:
            weaknesses.append(f"Complex pipeline ({pipe_count} pipes) - consider breaking into steps")
            suggestions.append("Break complex pipelines into separate commands for clarity")
            score -= 0.1

        # Check for documentation (comments in scripts)
        if len(command) > 100 and "#" not in command:
            suggestions.append("Long command could benefit from inline comments")

        # Determine level
        score = max(0.0, min(1.0, score))
        if score >= 0.9:
            level = QualityLevel.EXCELLENT
        elif score >= 0.75:
            level = QualityLevel.GOOD
        elif score >= 0.5:
            level = QualityLevel.ACCEPTABLE
        elif score >= 0.25:
            level = QualityLevel.NEEDS_IMPROVEMENT
        else:
            level = QualityLevel.POOR

        return QualityAssessment(
            level=level,
            score=score,
            strengths=strengths,
            weaknesses=weaknesses,
            suggestions=suggestions,
        )

    def check_plan(self, steps: list[dict[str, Any]]) -> QualityAssessment:
        """Check a multi-step plan against engineering standards."""
        strengths = []
        weaknesses = []
        suggestions = []
        total_score = 0.0

        # Check each step
        step_assessments = []
        for i, step in enumerate(steps):
            command = step.get("command", step.get("action", ""))
            if command:
                assessment = self.check_command(str(command))
                step_assessments.append(assessment)
                total_score += assessment.score

        if step_assessments:
            avg_score = total_score / len(step_assessments)
        else:
            avg_score = 1.0

        # Plan-level checks
        if len(steps) > 10:
            weaknesses.append(f"Plan has {len(steps)} steps - consider breaking into phases")
            suggestions.append("Large plans should be broken into logical phases with checkpoints")
            avg_score -= 0.1

        # Check for verification steps
        has_verification = any(
            "verify" in str(s).lower() or "check" in str(s).lower() or "test" in str(s).lower()
            for s in steps
        )
        if not has_verification and len(steps) > 3:
            suggestions.append("Consider adding verification steps to confirm success")
            avg_score -= 0.05

        # Check for rollback consideration
        has_rollback = any(
            "rollback" in str(s).lower() or "undo" in str(s).lower() or "backup" in str(s).lower()
            for s in steps
        )
        if not has_rollback and len(steps) > 5:
            suggestions.append("Complex plans should include rollback/backup steps")

        # Aggregate weaknesses from steps
        for assessment in step_assessments:
            weaknesses.extend(assessment.weaknesses[:2])  # Limit per step

        # Determine level
        avg_score = max(0.0, min(1.0, avg_score))
        if avg_score >= 0.9:
            level = QualityLevel.EXCELLENT
        elif avg_score >= 0.75:
            level = QualityLevel.GOOD
        elif avg_score >= 0.5:
            level = QualityLevel.ACCEPTABLE
        elif avg_score >= 0.25:
            level = QualityLevel.NEEDS_IMPROVEMENT
        else:
            level = QualityLevel.POOR

        if len(steps) <= 3 and avg_score >= 0.7:
            strengths.append("Concise plan with focused steps")
        if has_verification:
            strengths.append("Includes verification steps")
        if has_rollback:
            strengths.append("Considers rollback/recovery")

        return QualityAssessment(
            level=level,
            score=avg_score,
            strengths=strengths,
            weaknesses=weaknesses[:5],  # Limit total weaknesses
            suggestions=suggestions[:3],  # Limit suggestions
        )

    def get_violations(self) -> list[dict[str, Any]]:
        """Get recorded violations for audit."""
        return self._violations.copy()


# =============================================================================
# Quality Gates
# =============================================================================

class QualityGates:
    """Quality gates that must pass before/during/after execution.

    Pre-flight: Is this the right approach?
    Mid-flight: Is execution proceeding correctly?
    Post-flight: Did we achieve the goal?
    """

    def __init__(self):
        self._gate_results: list[QualityGateResult] = []

    def pre_flight(
        self,
        goal: str,
        plan: list[dict[str, Any]],
        context: dict[str, Any],
    ) -> list[QualityGateResult]:
        """Pre-flight quality checks before execution."""
        results = []

        # Gate 1: Goal clarity
        goal_clear = len(goal) > 10 and not goal.endswith("?")
        results.append(QualityGateResult(
            gate_name="goal_clarity",
            passed=goal_clear,
            message="Goal is clearly stated" if goal_clear else "Goal should be a clear statement, not a question",
            blocking=False,
        ))

        # Gate 2: Plan exists
        has_plan = len(plan) > 0
        results.append(QualityGateResult(
            gate_name="plan_exists",
            passed=has_plan,
            message="Execution plan defined" if has_plan else "No execution plan defined",
            blocking=True,
        ))

        # Gate 3: Reasonable scope
        reasonable_scope = len(plan) <= 25
        results.append(QualityGateResult(
            gate_name="reasonable_scope",
            passed=reasonable_scope,
            message=f"Plan has {len(plan)} steps" if reasonable_scope else f"Plan too large ({len(plan)} steps)",
            blocking=True,
        ))

        # Gate 4: Context available
        has_context = bool(context)
        results.append(QualityGateResult(
            gate_name="context_available",
            passed=has_context,
            message="System context available" if has_context else "No system context - decisions may be uninformed",
            blocking=False,
        ))

        # Gate 5: No obvious conflicts
        commands = [str(s.get("command", "")) for s in plan]
        has_conflicts = self._detect_conflicts(commands)
        results.append(QualityGateResult(
            gate_name="no_conflicts",
            passed=not has_conflicts,
            message="No conflicting operations detected" if not has_conflicts else "Potential conflicts detected in plan",
            details={"conflicts": has_conflicts} if has_conflicts else {},
            blocking=False,
        ))

        self._gate_results.extend(results)
        return results

    def mid_flight(
        self,
        step_number: int,
        step_result: dict[str, Any],
        expected_outcome: str,
    ) -> QualityGateResult:
        """Mid-flight check after each step."""
        success = step_result.get("success", step_result.get("returncode", 1) == 0)
        error = step_result.get("stderr", step_result.get("error", ""))

        # Check for unexpected warnings even on success
        has_warnings = bool(error) and success

        if not success:
            result = QualityGateResult(
                gate_name=f"step_{step_number}_success",
                passed=False,
                message=f"Step {step_number} failed: {error[:100]}",
                details={"step": step_number, "error": error},
                blocking=True,
            )
        elif has_warnings:
            result = QualityGateResult(
                gate_name=f"step_{step_number}_warnings",
                passed=True,
                message=f"Step {step_number} succeeded with warnings",
                details={"step": step_number, "warnings": error},
                blocking=False,
            )
        else:
            result = QualityGateResult(
                gate_name=f"step_{step_number}_success",
                passed=True,
                message=f"Step {step_number} completed successfully",
                details={"step": step_number},
                blocking=False,
            )

        self._gate_results.append(result)
        return result

    def post_flight(
        self,
        goal: str,
        results: list[dict[str, Any]],
        verification_fn: Any | None = None,
    ) -> list[QualityGateResult]:
        """Post-flight verification that goal was achieved."""
        gate_results = []

        # Gate 1: All steps completed
        all_success = all(
            r.get("success", r.get("returncode", 1) == 0)
            for r in results
        )
        gate_results.append(QualityGateResult(
            gate_name="all_steps_completed",
            passed=all_success,
            message="All steps completed successfully" if all_success else "Some steps failed",
            blocking=False,
        ))

        # Gate 2: No critical errors
        critical_errors = [
            r.get("stderr", "") for r in results
            if "error" in r.get("stderr", "").lower() or "fatal" in r.get("stderr", "").lower()
        ]
        gate_results.append(QualityGateResult(
            gate_name="no_critical_errors",
            passed=len(critical_errors) == 0,
            message="No critical errors" if not critical_errors else f"{len(critical_errors)} critical errors",
            details={"errors": critical_errors[:3]} if critical_errors else {},
            blocking=False,
        ))

        # Gate 3: Custom verification (if provided)
        if verification_fn:
            try:
                verified = verification_fn()
                gate_results.append(QualityGateResult(
                    gate_name="goal_verification",
                    passed=verified,
                    message="Goal achieved (verified)" if verified else "Goal verification failed",
                    blocking=False,
                ))
            except Exception as e:
                gate_results.append(QualityGateResult(
                    gate_name="goal_verification",
                    passed=False,
                    message=f"Verification error: {e}",
                    blocking=False,
                ))

        self._gate_results.extend(gate_results)
        return gate_results

    def _detect_conflicts(self, commands: list[str]) -> list[str]:
        """Detect potentially conflicting operations."""
        conflicts = []

        # Check for start/stop of same service
        services_started = set()
        services_stopped = set()
        for cmd in commands:
            if "start" in cmd:
                match = re.search(r"(?:start|restart)\s+(\S+)", cmd)
                if match:
                    services_started.add(match.group(1))
            if "stop" in cmd:
                match = re.search(r"stop\s+(\S+)", cmd)
                if match:
                    services_stopped.add(match.group(1))

        overlap = services_started & services_stopped
        if overlap:
            conflicts.append(f"Services both started and stopped: {overlap}")

        return conflicts

    def get_all_results(self) -> list[QualityGateResult]:
        """Get all gate results for audit."""
        return self._gate_results.copy()

    def all_blocking_passed(self) -> bool:
        """Check if all blocking gates passed."""
        return all(r.passed for r in self._gate_results if r.blocking)


# =============================================================================
# Maintainability Scorer
# =============================================================================

class MaintainabilityScorer:
    """Scores operations for long-term maintainability.

    Considers:
    - Documentation/comments
    - Reversibility
    - Clarity of intent
    - Future-proofing
    """

    def score_operation(
        self,
        description: str,
        command: str,
        has_rollback: bool = False,
        has_documentation: bool = False,
    ) -> QualityAssessment:
        """Score an operation for maintainability."""
        score = 0.5  # Start at baseline
        strengths = []
        weaknesses = []
        suggestions = []

        # Documentation
        if has_documentation or "#" in command:
            score += 0.15
            strengths.append("Has documentation/comments")
        else:
            suggestions.append("Add comments explaining purpose")

        # Reversibility
        if has_rollback:
            score += 0.15
            strengths.append("Reversible operation")
        elif any(kw in command.lower() for kw in ["rm", "delete", "drop", "truncate"]):
            weaknesses.append("Destructive operation without documented rollback")
            score -= 0.1

        # Clarity of intent
        if len(description) > 20:
            score += 0.1
            strengths.append("Clear description of intent")
        else:
            suggestions.append("Provide more detailed description of purpose")

        # Parameterization (no hardcoded values)
        hardcoded_patterns = [
            r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b",  # IP addresses
            r"/home/\w+/",  # Hardcoded home paths
            r"password\s*=\s*\S+",  # Hardcoded passwords
        ]
        for pattern in hardcoded_patterns:
            if re.search(pattern, command, re.IGNORECASE):
                weaknesses.append("Contains hardcoded values - consider parameterization")
                score -= 0.1
                break

        # Idempotency
        idempotent_patterns = ["--force", "--exist-ok", "if not exists", "|| true"]
        if any(p in command.lower() for p in idempotent_patterns):
            score += 0.1
            strengths.append("Idempotent operation")

        # Determine level
        score = max(0.0, min(1.0, score))
        if score >= 0.8:
            level = QualityLevel.EXCELLENT
        elif score >= 0.6:
            level = QualityLevel.GOOD
        elif score >= 0.4:
            level = QualityLevel.ACCEPTABLE
        elif score >= 0.2:
            level = QualityLevel.NEEDS_IMPROVEMENT
        else:
            level = QualityLevel.POOR

        return QualityAssessment(
            level=level,
            score=score,
            strengths=strengths,
            weaknesses=weaknesses,
            suggestions=suggestions,
        )


# =============================================================================
# Quality Commitment Prompt Engineering
# =============================================================================

QUALITY_COMMITMENT_PROMPT = """
QUALITY COMMITMENT - Engineering Excellence Standards

You are committed to producing the highest quality work. For every decision and action:

1. REASONING TRANSPARENCY
   - Explain WHY you chose this approach
   - List alternatives you considered
   - State your confidence level
   - Acknowledge uncertainties

2. ENGINEERING BEST PRACTICES
   - Prefer idempotent operations (can be safely re-run)
   - Use explicit over implicit (no hidden state changes)
   - Fail fast and loud (don't silently ignore errors)
   - Keep it simple (minimum viable solution first)

3. MAINTAINABILITY
   - Write self-documenting commands
   - Consider who will maintain this later
   - Document any non-obvious decisions
   - Ensure reversibility where possible

4. VERIFICATION
   - How will you verify success?
   - What could go wrong?
   - What's the rollback plan?

5. QUALITY CHECKLIST (ask yourself)
   □ Is this the simplest solution that works?
   □ Can this be safely re-run?
   □ Will someone understand this in 6 months?
   □ What's the blast radius if it fails?
   □ Is there a way to verify it worked?

When presenting plans or commands, include:
- GOAL: What we're trying to achieve
- APPROACH: Why this method
- RISKS: What could go wrong
- VERIFICATION: How to confirm success
"""


def create_quality_prompt_addition() -> str:
    """Get the quality commitment prompt addition."""
    return QUALITY_COMMITMENT_PROMPT


# =============================================================================
# Quality Framework - Main Interface
# =============================================================================

class QualityFramework:
    """Main interface for the Quality Commitment Framework.

    Combines all quality components into a unified API.
    """

    def __init__(self):
        self.reasoning_auditor = ReasoningAuditor()
        self.standards_checker = EngineeringStandardsChecker()
        self.quality_gates = QualityGates()
        self.maintainability_scorer = MaintainabilityScorer()

    def assess_command(self, command: str) -> QualityAssessment:
        """Assess quality of a single command."""
        return self.standards_checker.check_command(command)

    def assess_plan(self, steps: list[dict[str, Any]]) -> QualityAssessment:
        """Assess quality of a multi-step plan."""
        return self.standards_checker.check_plan(steps)

    def start_decision(
        self,
        decision_type: DecisionType,
        goal: str,
        context: str,
    ) -> ReasoningChain:
        """Start tracking a decision's reasoning."""
        return self.reasoning_auditor.start_reasoning(decision_type, goal, context)

    def record_reasoning_step(
        self,
        description: str,
        rationale: str,
        alternatives: list[str] | None = None,
        why_chosen: str = "",
    ) -> None:
        """Record a reasoning step."""
        self.reasoning_auditor.add_step(
            description=description,
            rationale=rationale,
            alternatives=alternatives,
            why_chosen=why_chosen,
        )

    def conclude_decision(self, conclusion: str) -> ReasoningChain | None:
        """Conclude and score a decision."""
        chain = self.reasoning_auditor.conclude_reasoning(conclusion)
        if chain:
            # Score based on reasoning quality
            score = self._score_reasoning_quality(chain)
            chain.quality_score = score
        return chain

    def _score_reasoning_quality(self, chain: ReasoningChain) -> float:
        """Score the quality of reasoning."""
        score = 0.5  # Baseline

        # Has multiple steps
        if len(chain.steps) >= 2:
            score += 0.1

        # Considered alternatives
        has_alternatives = any(s.alternatives_considered for s in chain.steps)
        if has_alternatives:
            score += 0.15

        # Has justifications
        has_justifications = any(s.why_chosen for s in chain.steps)
        if has_justifications:
            score += 0.15

        # Has conclusion
        if chain.conclusion:
            score += 0.1

        return min(1.0, score)

    def run_pre_flight(
        self,
        goal: str,
        plan: list[dict[str, Any]],
        context: dict[str, Any],
    ) -> tuple[bool, list[QualityGateResult]]:
        """Run pre-flight quality gates."""
        results = self.quality_gates.pre_flight(goal, plan, context)
        passed = all(r.passed for r in results if r.blocking)
        return passed, results

    def run_post_flight(
        self,
        goal: str,
        results: list[dict[str, Any]],
    ) -> tuple[bool, list[QualityGateResult]]:
        """Run post-flight quality gates."""
        gate_results = self.quality_gates.post_flight(goal, results)
        passed = all(r.passed for r in gate_results if r.blocking)
        return passed, gate_results

    def get_quality_summary(self) -> dict[str, Any]:
        """Get summary of quality metrics."""
        reasoning_chains = self.reasoning_auditor.get_recent_chains()
        gate_results = self.quality_gates.get_all_results()
        violations = self.standards_checker.get_violations()

        avg_reasoning_quality = (
            sum(c.quality_score for c in reasoning_chains) / len(reasoning_chains)
            if reasoning_chains else 0.0
        )

        gates_passed = sum(1 for r in gate_results if r.passed)
        gates_total = len(gate_results)

        return {
            "reasoning_chains": len(reasoning_chains),
            "avg_reasoning_quality": avg_reasoning_quality,
            "gates_passed": gates_passed,
            "gates_total": gates_total,
            "gate_pass_rate": gates_passed / gates_total if gates_total else 1.0,
            "standards_violations": len(violations),
            "recent_violations": violations[-5:],
        }


# Global framework instance
_framework = QualityFramework()


def get_quality_framework() -> QualityFramework:
    """Get the global quality framework instance."""
    return _framework
