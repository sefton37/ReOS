"""Tests for the Quality Commitment Framework.

Tests cover:
- ReasoningAuditor: Chain-of-thought tracking
- EngineeringStandardsChecker: Command and plan assessment
- QualityGates: Pre/mid/post flight checks
- MaintainabilityScorer: Maintainability assessment
- QualityFramework: Main interface integration
"""

import pytest
from datetime import datetime

from reos.quality import (
    # Enums and data classes
    QualityLevel,
    DecisionType,
    ReasoningStep,
    ReasoningChain,
    QualityAssessment,
    QualityGateResult,
    # Components
    ReasoningAuditor,
    EngineeringStandardsChecker,
    QualityGates,
    MaintainabilityScorer,
    QualityFramework,
    # Functions
    get_quality_framework,
    create_quality_prompt_addition,
    QUALITY_COMMITMENT_PROMPT,
)


# =============================================================================
# ReasoningChain Tests
# =============================================================================

class TestReasoningChain:
    """Tests for ReasoningChain data structure."""

    def test_create_chain(self):
        """Chain can be created with basic attributes."""
        chain = ReasoningChain(
            decision_type=DecisionType.TOOL_SELECTION,
            goal="List running containers",
            context="User wants container info",
        )
        assert chain.decision_type == DecisionType.TOOL_SELECTION
        assert chain.goal == "List running containers"
        assert chain.steps == []
        assert chain.quality_score == 0.0

    def test_add_step(self):
        """Steps can be added to chain."""
        chain = ReasoningChain(
            decision_type=DecisionType.COMMAND_CONSTRUCTION,
            goal="Stop nginx",
            context="Service management",
        )
        step = chain.add_step(
            description="Check service status",
            rationale="Need to verify service exists",
            alternatives=["Skip check", "Use different command"],
            why_chosen="Safety first",
            confidence=0.9,
        )

        assert len(chain.steps) == 1
        assert step.step_number == 1
        assert step.description == "Check service status"
        assert step.confidence == 0.9
        assert "Skip check" in step.alternatives_considered

    def test_audit_string_format(self):
        """Chain can be formatted as human-readable audit string."""
        chain = ReasoningChain(
            decision_type=DecisionType.PLAN_CREATION,
            goal="Install docker",
            context="Package management",
        )
        chain.add_step(
            description="Update package cache",
            rationale="Ensure latest package info",
        )
        chain.conclusion = "Plan created successfully"
        chain.quality_score = 0.85

        audit = chain.to_audit_string()

        assert "REASONING CHAIN: plan_creation" in audit
        assert "Goal: Install docker" in audit
        assert "Update package cache" in audit
        assert "Quality Score: 85%" in audit


# =============================================================================
# QualityAssessment Tests
# =============================================================================

class TestQualityAssessment:
    """Tests for QualityAssessment data structure."""

    def test_is_acceptable_excellent(self):
        """EXCELLENT level is acceptable."""
        assessment = QualityAssessment(
            level=QualityLevel.EXCELLENT,
            score=0.95,
        )
        assert assessment.is_acceptable() is True

    def test_is_acceptable_good(self):
        """GOOD level is acceptable."""
        assessment = QualityAssessment(
            level=QualityLevel.GOOD,
            score=0.8,
        )
        assert assessment.is_acceptable() is True

    def test_is_acceptable_acceptable(self):
        """ACCEPTABLE level is acceptable."""
        assessment = QualityAssessment(
            level=QualityLevel.ACCEPTABLE,
            score=0.6,
        )
        assert assessment.is_acceptable() is True

    def test_is_not_acceptable_needs_improvement(self):
        """NEEDS_IMPROVEMENT level is not acceptable."""
        assessment = QualityAssessment(
            level=QualityLevel.NEEDS_IMPROVEMENT,
            score=0.3,
        )
        assert assessment.is_acceptable() is False

    def test_is_not_acceptable_poor(self):
        """POOR level is not acceptable."""
        assessment = QualityAssessment(
            level=QualityLevel.POOR,
            score=0.1,
        )
        assert assessment.is_acceptable() is False


# =============================================================================
# ReasoningAuditor Tests
# =============================================================================

class TestReasoningAuditor:
    """Tests for ReasoningAuditor component."""

    def test_start_reasoning(self):
        """Can start a new reasoning chain."""
        auditor = ReasoningAuditor()
        chain = auditor.start_reasoning(
            decision_type=DecisionType.TOOL_SELECTION,
            goal="Check system info",
            context="User asked about system",
        )

        assert chain.decision_type == DecisionType.TOOL_SELECTION
        assert chain.goal == "Check system info"
        assert auditor._current_chain is chain

    def test_add_step_to_active_chain(self):
        """Can add steps to active chain."""
        auditor = ReasoningAuditor()
        auditor.start_reasoning(
            decision_type=DecisionType.COMMAND_CONSTRUCTION,
            goal="Build command",
            context="Test",
        )

        step = auditor.add_step(
            description="Step 1",
            rationale="Because reasons",
        )

        assert step is not None
        assert step.step_number == 1

    def test_add_step_without_chain_returns_none(self):
        """Adding step without active chain returns None."""
        auditor = ReasoningAuditor()
        step = auditor.add_step("No chain", "No rationale")
        assert step is None

    def test_conclude_reasoning(self):
        """Can conclude reasoning chain."""
        auditor = ReasoningAuditor()
        auditor.start_reasoning(
            decision_type=DecisionType.APPROACH_SELECTION,
            goal="Choose approach",
            context="Test",
        )
        auditor.add_step("Analyze options", "Need to compare")

        chain = auditor.conclude_reasoning("Option A selected", quality_score=0.8)

        assert chain is not None
        assert chain.conclusion == "Option A selected"
        assert chain.quality_score == 0.8
        assert auditor._current_chain is None  # No longer active

    def test_conclude_without_chain_returns_none(self):
        """Concluding without active chain returns None."""
        auditor = ReasoningAuditor()
        chain = auditor.conclude_reasoning("Nothing to conclude")
        assert chain is None

    def test_chains_stored_with_limit(self):
        """Chains are stored with bounded limit."""
        auditor = ReasoningAuditor()
        auditor._max_chains = 5

        for i in range(10):
            auditor.start_reasoning(
                decision_type=DecisionType.TOOL_SELECTION,
                goal=f"Goal {i}",
                context="Test",
            )
            auditor.conclude_reasoning(f"Done {i}")

        chains = auditor.get_recent_chains(limit=10)
        assert len(chains) == 5  # Limited to max_chains

    def test_get_recent_chains(self):
        """Can get recent chains."""
        auditor = ReasoningAuditor()

        for i in range(3):
            auditor.start_reasoning(
                decision_type=DecisionType.TOOL_SELECTION,
                goal=f"Goal {i}",
                context="Test",
            )
            auditor.conclude_reasoning(f"Done {i}")

        chains = auditor.get_recent_chains(limit=2)
        assert len(chains) == 2


# =============================================================================
# EngineeringStandardsChecker Tests
# =============================================================================

class TestEngineeringStandardsChecker:
    """Tests for EngineeringStandardsChecker component."""

    def test_check_command_with_good_patterns(self):
        """Commands with good patterns score higher."""
        checker = EngineeringStandardsChecker()

        # Idempotent pattern
        assessment = checker.check_command("docker pull nginx --force")
        assert "idempotent" in str(assessment.strengths).lower()

    def test_check_command_with_bad_pattern_cd_and(self):
        """Implicit directory state is flagged."""
        checker = EngineeringStandardsChecker()
        assessment = checker.check_command("cd /tmp && rm file.txt")

        assert any("directory" in w.lower() for w in assessment.weaknesses)
        assert assessment.score < 1.0

    def test_check_command_with_bad_pattern_silent_errors(self):
        """Silently ignoring errors is flagged."""
        checker = EngineeringStandardsChecker()
        assessment = checker.check_command("some_command || true")

        assert any("error" in w.lower() for w in assessment.weaknesses)

    def test_check_command_useless_cat(self):
        """Useless cat is flagged as inefficient."""
        checker = EngineeringStandardsChecker()
        assessment = checker.check_command("cat file.log | grep error")

        assert any("cat" in w.lower() for w in assessment.weaknesses)

    def test_check_command_complex_pipeline(self):
        """Complex pipelines get lower scores."""
        checker = EngineeringStandardsChecker()
        assessment = checker.check_command("cat file | grep x | sort | uniq | head | tail")

        assert any("pipeline" in w.lower() for w in assessment.weaknesses)
        assert any("break" in s.lower() for s in assessment.suggestions)

    def test_check_command_simple_good_command(self):
        """Simple good command scores well."""
        checker = EngineeringStandardsChecker()
        assessment = checker.check_command("docker ps")

        assert assessment.score >= 0.75
        assert assessment.level in (QualityLevel.EXCELLENT, QualityLevel.GOOD)

    def test_check_plan_large_plan_flagged(self):
        """Large plans are flagged."""
        checker = EngineeringStandardsChecker()
        steps = [{"command": f"step {i}"} for i in range(15)]

        assessment = checker.check_plan(steps)

        assert any("steps" in w.lower() for w in assessment.weaknesses)
        assert any("phase" in s.lower() for s in assessment.suggestions)

    def test_check_plan_without_verification(self):
        """Plans without verification get suggestions."""
        checker = EngineeringStandardsChecker()
        steps = [
            {"command": "apt update"},
            {"command": "apt install nginx"},
            {"command": "systemctl start nginx"},
            {"command": "systemctl enable nginx"},
        ]

        assessment = checker.check_plan(steps)

        assert any("verification" in s.lower() for s in assessment.suggestions)

    def test_check_plan_with_verification(self):
        """Plans with verification are noted."""
        checker = EngineeringStandardsChecker()
        steps = [
            {"command": "apt install nginx"},
            {"command": "systemctl start nginx"},
            {"command": "curl localhost --fail  # verify nginx works"},
        ]

        assessment = checker.check_plan(steps)

        assert any("verification" in s.lower() for s in assessment.strengths)

    def test_check_plan_concise(self):
        """Concise plans are praised."""
        checker = EngineeringStandardsChecker()
        steps = [
            {"command": "docker stop nginx"},
            {"command": "docker rm nginx"},
        ]

        assessment = checker.check_plan(steps)

        assert any("concise" in s.lower() for s in assessment.strengths)

    def test_violations_tracked(self):
        """Violations are tracked for audit."""
        checker = EngineeringStandardsChecker()
        checker.check_command("cd /tmp && echo test")
        checker.check_command("cat log | grep error")

        violations = checker.get_violations()
        assert len(violations) >= 2


# =============================================================================
# QualityGates Tests
# =============================================================================

class TestQualityGates:
    """Tests for QualityGates component."""

    def test_pre_flight_goal_clarity(self):
        """Pre-flight checks goal clarity."""
        gates = QualityGates()

        # Clear goal
        results = gates.pre_flight(
            goal="Install and configure nginx as a reverse proxy",
            plan=[{"command": "apt install nginx"}],
            context={"system": "ubuntu"},
        )
        goal_gate = next(r for r in results if r.gate_name == "goal_clarity")
        assert goal_gate.passed is True

        # Question as goal (less clear)
        gates2 = QualityGates()
        results2 = gates2.pre_flight(
            goal="nginx?",
            plan=[{"command": "apt install nginx"}],
            context={},
        )
        goal_gate2 = next(r for r in results2 if r.gate_name == "goal_clarity")
        assert goal_gate2.passed is False

    def test_pre_flight_plan_exists(self):
        """Pre-flight checks that plan exists."""
        gates = QualityGates()

        # No plan
        results = gates.pre_flight(
            goal="Do something",
            plan=[],
            context={},
        )
        plan_gate = next(r for r in results if r.gate_name == "plan_exists")
        assert plan_gate.passed is False
        assert plan_gate.blocking is True

    def test_pre_flight_reasonable_scope(self):
        """Pre-flight checks plan scope."""
        gates = QualityGates()

        # Too large
        large_plan = [{"command": f"cmd {i}"} for i in range(30)]
        results = gates.pre_flight(
            goal="Do many things",
            plan=large_plan,
            context={},
        )
        scope_gate = next(r for r in results if r.gate_name == "reasonable_scope")
        assert scope_gate.passed is False
        assert scope_gate.blocking is True

    def test_pre_flight_context_available(self):
        """Pre-flight checks context availability."""
        gates = QualityGates()

        # No context
        results = gates.pre_flight(
            goal="Do something",
            plan=[{"command": "cmd"}],
            context={},
        )
        ctx_gate = next(r for r in results if r.gate_name == "context_available")
        assert ctx_gate.passed is False
        assert ctx_gate.blocking is False  # Non-blocking

    def test_pre_flight_conflict_detection(self):
        """Pre-flight detects conflicting operations."""
        gates = QualityGates()

        # Start and stop same service
        results = gates.pre_flight(
            goal="Manage nginx",
            plan=[
                {"command": "systemctl start nginx"},
                {"command": "systemctl stop nginx"},
            ],
            context={},
        )
        conflict_gate = next(r for r in results if r.gate_name == "no_conflicts")
        assert conflict_gate.passed is False

    def test_mid_flight_success(self):
        """Mid-flight passes on success."""
        gates = QualityGates()

        result = gates.mid_flight(
            step_number=1,
            step_result={"returncode": 0, "stdout": "OK", "stderr": ""},
            expected_outcome="Success",
        )

        assert result.passed is True
        assert "successfully" in result.message.lower()

    def test_mid_flight_failure(self):
        """Mid-flight fails on error."""
        gates = QualityGates()

        result = gates.mid_flight(
            step_number=2,
            step_result={"returncode": 1, "stderr": "Command not found"},
            expected_outcome="Success",
        )

        assert result.passed is False
        assert result.blocking is True
        assert "failed" in result.message.lower()

    def test_mid_flight_warnings(self):
        """Mid-flight notes warnings even on success."""
        gates = QualityGates()

        result = gates.mid_flight(
            step_number=1,
            step_result={"returncode": 0, "stderr": "Warning: deprecated"},
            expected_outcome="Success",
        )

        assert result.passed is True
        assert "warning" in result.message.lower()

    def test_post_flight_all_success(self):
        """Post-flight passes when all steps succeeded."""
        gates = QualityGates()

        results_list = gates.post_flight(
            goal="Install nginx",
            results=[
                {"returncode": 0, "stderr": ""},
                {"returncode": 0, "stderr": ""},
            ],
        )

        completion_gate = next(r for r in results_list if r.gate_name == "all_steps_completed")
        assert completion_gate.passed is True

    def test_post_flight_some_failures(self):
        """Post-flight notes when some steps failed."""
        gates = QualityGates()

        results_list = gates.post_flight(
            goal="Install nginx",
            results=[
                {"returncode": 0, "stderr": ""},
                {"returncode": 1, "stderr": "error: failed"},
            ],
        )

        completion_gate = next(r for r in results_list if r.gate_name == "all_steps_completed")
        assert completion_gate.passed is False

    def test_post_flight_critical_errors(self):
        """Post-flight detects critical errors."""
        gates = QualityGates()

        results_list = gates.post_flight(
            goal="Install nginx",
            results=[
                {"returncode": 0, "stderr": "fatal error occurred"},
            ],
        )

        error_gate = next(r for r in results_list if r.gate_name == "no_critical_errors")
        assert error_gate.passed is False

    def test_post_flight_custom_verification(self):
        """Post-flight can use custom verification function."""
        gates = QualityGates()

        # Verification passes
        results_list = gates.post_flight(
            goal="Install nginx",
            results=[{"returncode": 0}],
            verification_fn=lambda: True,
        )
        verify_gate = next(r for r in results_list if r.gate_name == "goal_verification")
        assert verify_gate.passed is True

        # Verification fails
        gates2 = QualityGates()
        results_list2 = gates2.post_flight(
            goal="Install nginx",
            results=[{"returncode": 0}],
            verification_fn=lambda: False,
        )
        verify_gate2 = next(r for r in results_list2 if r.gate_name == "goal_verification")
        assert verify_gate2.passed is False

    def test_all_blocking_passed(self):
        """Can check if all blocking gates passed."""
        gates = QualityGates()
        gates.pre_flight(
            goal="Install nginx service",
            plan=[{"command": "apt install nginx"}],
            context={"system": "ubuntu"},
        )

        assert gates.all_blocking_passed() is True

    def test_all_blocking_failed(self):
        """Detects when blocking gates failed."""
        gates = QualityGates()
        gates.pre_flight(
            goal="Do something",
            plan=[],  # Empty plan fails blocking gate
            context={},
        )

        assert gates.all_blocking_passed() is False


# =============================================================================
# MaintainabilityScorer Tests
# =============================================================================

class TestMaintainabilityScorer:
    """Tests for MaintainabilityScorer component."""

    def test_score_documented_operation(self):
        """Documented operations score higher."""
        scorer = MaintainabilityScorer()

        assessment = scorer.score_operation(
            description="Install nginx for reverse proxy",
            command="apt install nginx  # Main web server",
            has_documentation=True,
        )

        assert any("documentation" in s.lower() for s in assessment.strengths)
        assert assessment.score > 0.5

    def test_score_reversible_operation(self):
        """Reversible operations score higher."""
        scorer = MaintainabilityScorer()

        assessment = scorer.score_operation(
            description="Install nginx",
            command="apt install nginx",
            has_rollback=True,
        )

        assert any("reversible" in s.lower() for s in assessment.strengths)

    def test_score_destructive_without_rollback(self):
        """Destructive operations without rollback score lower."""
        scorer = MaintainabilityScorer()

        assessment = scorer.score_operation(
            description="Remove",
            command="rm -rf /tmp/old_files",
            has_rollback=False,
        )

        assert any("destructive" in w.lower() for w in assessment.weaknesses)

    def test_score_clear_description(self):
        """Clear descriptions score higher."""
        scorer = MaintainabilityScorer()

        assessment = scorer.score_operation(
            description="Install nginx web server and configure as reverse proxy",
            command="apt install nginx",
        )

        assert any("description" in s.lower() or "intent" in s.lower() for s in assessment.strengths)

    def test_score_hardcoded_ip(self):
        """Hardcoded IPs are flagged."""
        scorer = MaintainabilityScorer()

        assessment = scorer.score_operation(
            description="Connect to server",
            command="ssh 192.168.1.100",
        )

        assert any("hardcoded" in w.lower() for w in assessment.weaknesses)

    def test_score_hardcoded_home_path(self):
        """Hardcoded home paths are flagged."""
        scorer = MaintainabilityScorer()

        assessment = scorer.score_operation(
            description="Copy config",
            command="cp /home/john/.config/app /etc/app",
        )

        assert any("hardcoded" in w.lower() for w in assessment.weaknesses)

    def test_score_idempotent_operation(self):
        """Idempotent operations score higher."""
        scorer = MaintainabilityScorer()

        assessment = scorer.score_operation(
            description="Create directory",
            command="mkdir -p /tmp/app --exist-ok",
        )

        assert any("idempotent" in s.lower() for s in assessment.strengths)


# =============================================================================
# QualityFramework Integration Tests
# =============================================================================

class TestQualityFramework:
    """Tests for main QualityFramework interface."""

    def test_assess_command(self):
        """Framework can assess commands."""
        framework = QualityFramework()
        assessment = framework.assess_command("docker ps")

        assert isinstance(assessment, QualityAssessment)
        assert assessment.level in QualityLevel

    def test_assess_plan(self):
        """Framework can assess plans."""
        framework = QualityFramework()
        steps = [
            {"command": "apt update"},
            {"command": "apt install nginx"},
        ]
        assessment = framework.assess_plan(steps)

        assert isinstance(assessment, QualityAssessment)

    def test_full_reasoning_flow(self):
        """Framework supports full reasoning flow."""
        framework = QualityFramework()

        # Start decision
        chain = framework.start_decision(
            decision_type=DecisionType.TOOL_SELECTION,
            goal="Get system info",
            context="User asked about system",
        )
        assert chain is not None

        # Record steps
        framework.record_reasoning_step(
            description="Analyze request",
            rationale="Need to understand what info is needed",
            alternatives=["Use generic info", "Ask for clarification"],
            why_chosen="Request is clear enough",
        )

        # Conclude
        result = framework.conclude_decision("Selected linux_system_info tool")

        assert result is not None
        assert result.quality_score > 0

    def test_pre_flight_gates(self):
        """Framework can run pre-flight gates."""
        framework = QualityFramework()

        passed, results = framework.run_pre_flight(
            goal="Install and configure nginx",
            plan=[{"command": "apt install nginx"}],
            context={"os": "ubuntu"},
        )

        assert isinstance(passed, bool)
        assert len(results) > 0
        assert all(isinstance(r, QualityGateResult) for r in results)

    def test_post_flight_gates(self):
        """Framework can run post-flight gates."""
        framework = QualityFramework()

        passed, results = framework.run_post_flight(
            goal="Install nginx",
            results=[{"returncode": 0, "stderr": ""}],
        )

        assert isinstance(passed, bool)
        assert len(results) > 0

    def test_quality_summary(self):
        """Framework provides quality summary."""
        framework = QualityFramework()

        # Do some operations
        framework.assess_command("docker ps")
        framework.start_decision(
            decision_type=DecisionType.TOOL_SELECTION,
            goal="Test",
            context="Test",
        )
        framework.conclude_decision("Done")
        framework.run_pre_flight(
            goal="Test goal here",
            plan=[{"command": "test"}],
            context={"test": True},
        )

        summary = framework.get_quality_summary()

        assert "reasoning_chains" in summary
        assert "gates_passed" in summary
        assert "gate_pass_rate" in summary

    def test_reasoning_quality_scoring(self):
        """Reasoning with alternatives scores higher."""
        framework = QualityFramework()

        # Good reasoning with alternatives
        framework.start_decision(
            decision_type=DecisionType.APPROACH_SELECTION,
            goal="Choose approach",
            context="Test",
        )
        framework.record_reasoning_step(
            description="Analyze",
            rationale="Need analysis",
            alternatives=["Option A", "Option B"],
            why_chosen="A is better because X",
        )
        framework.record_reasoning_step(
            description="Verify",
            rationale="Need verification",
        )
        chain = framework.conclude_decision("Chose Option A")

        assert chain.quality_score >= 0.7  # Good score with alternatives


# =============================================================================
# Module-Level Function Tests
# =============================================================================

class TestModuleFunctions:
    """Tests for module-level functions."""

    def test_get_quality_framework_singleton(self):
        """get_quality_framework returns singleton."""
        framework1 = get_quality_framework()
        framework2 = get_quality_framework()

        assert framework1 is framework2

    def test_create_quality_prompt_addition(self):
        """Quality prompt addition is available."""
        prompt = create_quality_prompt_addition()

        assert "QUALITY COMMITMENT" in prompt
        assert "REASONING TRANSPARENCY" in prompt
        assert "ENGINEERING BEST PRACTICES" in prompt
        assert "MAINTAINABILITY" in prompt
        assert "VERIFICATION" in prompt

    def test_quality_commitment_prompt_content(self):
        """Quality commitment prompt has required sections."""
        assert "idempotent" in QUALITY_COMMITMENT_PROMPT.lower()
        assert "rollback" in QUALITY_COMMITMENT_PROMPT.lower()
        assert "verify" in QUALITY_COMMITMENT_PROMPT.lower()


# =============================================================================
# Edge Cases and Boundary Tests
# =============================================================================

class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_empty_command_assessment(self):
        """Empty command can be assessed."""
        checker = EngineeringStandardsChecker()
        assessment = checker.check_command("")

        assert assessment.level is not None

    def test_empty_plan_assessment(self):
        """Empty plan can be assessed."""
        checker = EngineeringStandardsChecker()
        assessment = checker.check_plan([])

        assert assessment.score == 1.0  # No issues found

    def test_very_long_command(self):
        """Very long commands get suggestions."""
        checker = EngineeringStandardsChecker()
        long_command = "echo " + "x" * 200
        assessment = checker.check_command(long_command)

        # Should suggest adding comments
        assert len(assessment.suggestions) > 0 or assessment.score < 1.0

    def test_multiple_bad_patterns(self):
        """Multiple bad patterns accumulate."""
        checker = EngineeringStandardsChecker()
        command = "cd /tmp && cat file | grep x || true"
        assessment = checker.check_command(command)

        assert len(assessment.weaknesses) >= 2
        assert assessment.score < 0.8

    def test_quality_gate_results_accumulate(self):
        """Gate results accumulate across calls."""
        gates = QualityGates()

        gates.pre_flight("Goal 1", [{"command": "a"}], {"x": 1})
        gates.mid_flight(1, {"returncode": 0}, "ok")
        gates.post_flight("Goal 1", [{"returncode": 0}])

        all_results = gates.get_all_results()
        assert len(all_results) > 5  # Multiple gates checked

    def test_reasoning_chain_timestamp(self):
        """Reasoning chains have timestamps."""
        auditor = ReasoningAuditor()
        chain = auditor.start_reasoning(
            decision_type=DecisionType.TOOL_SELECTION,
            goal="Test",
            context="Test",
        )

        assert isinstance(chain.timestamp, datetime)
