"""Tests for CAIRN Coherence Verification Kernel.

Tests the core coherence verification functionality:
- IdentityModel and IdentityFacet
- AttentionDemand
- CoherenceCheck and CoherenceResult
- CoherenceVerifier (heuristic mode)
- Identity extraction from Play
- Anti-pattern management
"""

import json
import pytest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

from reos.cairn.coherence import (
    AttentionDemand,
    CoherenceCheck,
    CoherenceResult,
    CoherenceStatus,
    CoherenceTrace,
    CoherenceVerifier,
    IdentityFacet,
    IdentityModel,
)


# =============================================================================
# IdentityFacet Tests
# =============================================================================


class TestIdentityFacet:
    """Tests for IdentityFacet dataclass."""

    def test_create_facet(self):
        """Test creating an identity facet."""
        facet = IdentityFacet(
            name="values",
            source="me.md",
            content="I value honesty and integrity.",
            weight=2.0,
        )
        assert facet.name == "values"
        assert facet.source == "me.md"
        assert facet.weight == 2.0

    def test_facet_to_dict(self):
        """Test serialization to dict."""
        facet = IdentityFacet(
            name="goal",
            source="act:project-x",
            content="Build an AI assistant",
            weight=1.5,
        )
        data = facet.to_dict()
        assert data["name"] == "goal"
        assert data["source"] == "act:project-x"
        assert data["weight"] == 1.5

    def test_facet_from_dict(self):
        """Test deserialization from dict."""
        data = {
            "name": "skill",
            "source": "kb:skills.md",
            "content": "Python programming",
            "weight": 1.0,
        }
        facet = IdentityFacet.from_dict(data)
        assert facet.name == "skill"
        assert facet.content == "Python programming"


# =============================================================================
# IdentityModel Tests
# =============================================================================


class TestIdentityModel:
    """Tests for IdentityModel dataclass."""

    def test_create_model(self):
        """Test creating an identity model."""
        model = IdentityModel(
            core="I am a software developer focused on AI.",
            facets=[
                IdentityFacet(name="goal", source="act:1", content="Build tools"),
            ],
            anti_patterns=["spam", "marketing"],
        )
        assert "software developer" in model.core
        assert len(model.facets) == 1
        assert len(model.anti_patterns) == 2

    def test_get_facets_by_name(self):
        """Test filtering facets by name."""
        model = IdentityModel(
            core="Core identity",
            facets=[
                IdentityFacet(name="goal", source="1", content="Goal 1"),
                IdentityFacet(name="goal", source="2", content="Goal 2"),
                IdentityFacet(name="skill", source="3", content="Skill 1"),
            ],
        )
        goals = model.get_facets_by_name("goal")
        assert len(goals) == 2
        skills = model.get_facets_by_name("skill")
        assert len(skills) == 1

    def test_get_relevant_facets(self):
        """Test finding facets by keyword."""
        model = IdentityModel(
            core="Core identity",
            facets=[
                IdentityFacet(name="goal", source="1", content="Build AI assistant"),
                IdentityFacet(name="goal", source="2", content="Learn Python"),
                IdentityFacet(name="skill", source="3", content="Machine learning"),
            ],
        )
        relevant = model.get_relevant_facets(["AI", "machine"])
        assert len(relevant) == 2  # AI assistant and machine learning

    def test_model_serialization(self):
        """Test round-trip serialization."""
        model = IdentityModel(
            core="Test core",
            facets=[IdentityFacet(name="test", source="s", content="c")],
            anti_patterns=["spam"],
        )
        data = model.to_dict()
        restored = IdentityModel.from_dict(data)
        assert restored.core == model.core
        assert len(restored.facets) == len(model.facets)
        assert restored.anti_patterns == model.anti_patterns


# =============================================================================
# AttentionDemand Tests
# =============================================================================


class TestAttentionDemand:
    """Tests for AttentionDemand dataclass."""

    def test_create_demand(self):
        """Test creating a demand via factory method."""
        demand = AttentionDemand.create(
            source="email",
            content="Review pull request",
            urgency=7,
        )
        assert demand.id.startswith("demand-")
        assert demand.source == "email"
        assert demand.urgency == 7

    def test_urgency_clamping(self):
        """Test that urgency is clamped to 0-10."""
        demand = AttentionDemand.create(source="test", content="test", urgency=15)
        assert demand.urgency == 10

        demand = AttentionDemand.create(source="test", content="test", urgency=-5)
        assert demand.urgency == 0

    def test_demand_serialization(self):
        """Test round-trip serialization."""
        demand = AttentionDemand.create(
            source="calendar",
            content="Meeting at 3pm",
            urgency=8,
        )
        data = demand.to_dict()
        restored = AttentionDemand.from_dict(data)
        assert restored.id == demand.id
        assert restored.source == demand.source
        assert restored.urgency == demand.urgency


# =============================================================================
# CoherenceCheck Tests
# =============================================================================


class TestCoherenceCheck:
    """Tests for CoherenceCheck dataclass."""

    def test_create_check(self):
        """Test creating a coherence check."""
        check = CoherenceCheck(
            facet_checked="values",
            demand_aspect="Review pull request",
            alignment=0.8,
            reasoning="Aligns with work values",
        )
        assert check.alignment == 0.8
        assert "work values" in check.reasoning

    def test_check_serialization(self):
        """Test round-trip serialization."""
        check = CoherenceCheck(
            facet_checked="goal",
            demand_aspect="Build feature",
            alignment=0.5,
            reasoning="Neutral",
        )
        data = check.to_dict()
        restored = CoherenceCheck.from_dict(data)
        assert restored.alignment == check.alignment


# =============================================================================
# CoherenceVerifier Tests (Heuristic Mode)
# =============================================================================


class TestCoherenceVerifier:
    """Tests for CoherenceVerifier class."""

    @pytest.fixture
    def simple_identity(self):
        """Create a simple identity model for testing."""
        return IdentityModel(
            core="I am a software developer working on AI tools. I value clean code and testing.",
            facets=[
                IdentityFacet(
                    name="goal",
                    source="act:1",
                    content="Build an AI assistant that helps developers",
                    weight=2.0,
                ),
                IdentityFacet(
                    name="value",
                    source="me.md",
                    content="I believe in test-driven development",
                    weight=1.5,
                ),
            ],
            anti_patterns=["spam", "marketing email", "newsletter"],
        )

    def test_anti_pattern_rejection(self, simple_identity):
        """Test that anti-patterns cause immediate rejection."""
        verifier = CoherenceVerifier(simple_identity, llm=None)

        demand = AttentionDemand.create(
            source="marketing email",
            content="Subscribe to our newsletter!",
            urgency=5,
        )

        result = verifier.verify(demand)
        assert result.recommendation == "reject"
        assert result.overall_score == -1.0
        assert any("anti-pattern" in t.lower() for t in result.trace)

    def test_coherent_demand(self, simple_identity):
        """Test a demand that coheres with identity."""
        verifier = CoherenceVerifier(simple_identity, llm=None)

        demand = AttentionDemand.create(
            source="github",
            content="Review AI assistant code with tests",
            urgency=5,
        )

        result = verifier.verify(demand)
        # Should be positive since it matches keywords
        assert result.overall_score > 0
        assert result.recommendation in ("accept", "defer")
        assert len(result.checks) > 0

    def test_neutral_demand(self, simple_identity):
        """Test a demand with no clear connection."""
        verifier = CoherenceVerifier(simple_identity, llm=None)

        demand = AttentionDemand.create(
            source="random",
            content="Buy groceries tomorrow morning",
            urgency=3,
        )

        result = verifier.verify(demand)
        # Score should be neutral (around 0)
        assert -0.3 <= result.overall_score <= 0.3
        assert result.recommendation == "defer"

    def test_can_verify_directly_simple(self, simple_identity):
        """Test that short demands can be verified directly."""
        verifier = CoherenceVerifier(simple_identity, llm=None)

        demand = AttentionDemand.create(
            source="test",
            content="Fix bug",
            urgency=5,
        )

        assert verifier._can_verify_directly(demand) is True

    def test_can_verify_directly_complex(self, simple_identity):
        """Test that complex demands require decomposition."""
        verifier = CoherenceVerifier(simple_identity, llm=None)

        # Long content with multiple compound words triggers decomposition
        demand = AttentionDemand.create(
            source="test",
            content="Fix the critical bug in the authentication module and also update the documentation for the API endpoints and additionally run the entire test suite to verify no regressions and finally review the pending pull request from the team",
            urgency=5,
        )

        assert verifier._can_verify_directly(demand) is False

    def test_heuristic_decompose(self, simple_identity):
        """Test heuristic decomposition of complex demands."""
        verifier = CoherenceVerifier(simple_identity, llm=None)

        demand = AttentionDemand.create(
            source="test",
            content="Fix bug and update tests",
            urgency=5,
        )

        sub_demands = verifier._heuristic_decompose(demand)
        assert len(sub_demands) == 2
        assert any("Fix bug" in d.content for d in sub_demands)
        assert any("update tests" in d.content for d in sub_demands)

    def test_depth_limiting(self, simple_identity):
        """Test that recursion is limited by max_depth."""
        verifier = CoherenceVerifier(simple_identity, llm=None, max_depth=1)

        # Complex demand that would normally decompose
        demand = AttentionDemand.create(
            source="test",
            content="A and B and C and D",
            urgency=5,
        )

        result = verifier.verify(demand)
        # Should complete without infinite recursion
        assert result is not None
        assert "depth" in " ".join(result.trace).lower() or len(result.checks) > 0

    def test_extract_keywords(self, simple_identity):
        """Test keyword extraction."""
        verifier = CoherenceVerifier(simple_identity, llm=None)

        keywords = verifier._extract_keywords("Build an AI assistant for Python developers")

        assert "build" in keywords
        assert "assistant" in keywords
        assert "python" in keywords
        # Common words should be filtered
        assert "an" not in keywords
        assert "for" not in keywords

    def test_score_to_recommendation(self, simple_identity):
        """Test score to recommendation mapping."""
        verifier = CoherenceVerifier(simple_identity, llm=None)

        assert verifier._score_to_recommendation(0.7) == "accept"
        assert verifier._score_to_recommendation(0.3) == "defer"
        assert verifier._score_to_recommendation(-0.3) == "defer"
        assert verifier._score_to_recommendation(-0.7) == "reject"


# =============================================================================
# CoherenceTrace Tests
# =============================================================================


class TestCoherenceTrace:
    """Tests for CoherenceTrace dataclass."""

    def test_create_from_result(self):
        """Test creating a trace from a coherence result."""
        demand = AttentionDemand.create(source="test", content="Test", urgency=5)
        result = CoherenceResult(
            demand=demand,
            checks=[
                CoherenceCheck(
                    facet_checked="core",
                    demand_aspect="Test",
                    alignment=0.5,
                    reasoning="Neutral",
                )
            ],
            overall_score=0.5,
            recommendation="defer",
            trace=["test trace"],
        )

        trace = CoherenceTrace.create(result, identity_hash="abc123")

        assert trace.trace_id.startswith("trace-")
        assert trace.demand_id == demand.id
        assert trace.identity_hash == "abc123"
        assert trace.final_score == 0.5
        assert trace.recommendation == "defer"

    def test_trace_serialization(self):
        """Test round-trip serialization."""
        demand = AttentionDemand.create(source="test", content="Test", urgency=5)
        result = CoherenceResult(
            demand=demand,
            checks=[],
            overall_score=0.0,
            recommendation="defer",
        )
        trace = CoherenceTrace.create(result, "hash123")

        data = trace.to_dict()
        restored = CoherenceTrace.from_dict(data)

        assert restored.trace_id == trace.trace_id
        assert restored.identity_hash == trace.identity_hash


# =============================================================================
# Identity Extraction Tests
# =============================================================================


class TestIdentityExtraction:
    """Tests for identity extraction from Play."""

    @pytest.fixture
    def temp_play(self, tmp_path):
        """Create a temporary Play structure."""
        play_path = tmp_path / "play"
        play_path.mkdir()

        # Create me.md
        me_md = play_path / "me.md"
        me_md.write_text("# My Story\n\nI am a test user who loves coding.")

        # Create acts directory
        acts_path = play_path / "acts"
        acts_path.mkdir()

        # Create an act
        act_path = acts_path / "test-act"
        act_path.mkdir()
        (act_path / "act.json").write_text(json.dumps({
            "act_id": "test-act",
            "title": "Test Project",
            "notes": "A test project for coherence testing",
            "active": True,
        }))

        return play_path

    def test_load_anti_patterns(self, tmp_path):
        """Test loading anti-patterns from file."""
        from reos.cairn.identity import load_anti_patterns, _anti_patterns_path

        with patch("reos.cairn.identity._anti_patterns_path") as mock_path:
            mock_path.return_value = tmp_path / "anti_patterns.json"

            # No file - empty list
            patterns = load_anti_patterns()
            assert patterns == []

            # Create file
            (tmp_path / "anti_patterns.json").write_text(json.dumps({
                "anti_patterns": ["spam", "marketing"],
            }))

            patterns = load_anti_patterns()
            assert patterns == ["spam", "marketing"]

    def test_add_anti_pattern(self, tmp_path):
        """Test adding an anti-pattern."""
        from reos.cairn.identity import add_anti_pattern, load_anti_patterns

        with patch("reos.cairn.identity._anti_patterns_path") as mock_path:
            mock_path.return_value = tmp_path / "anti_patterns.json"

            patterns = add_anti_pattern("spam", "I don't want spam")
            assert "spam" in patterns

            # Adding same pattern again should not duplicate
            patterns = add_anti_pattern("spam", "duplicate")
            assert patterns.count("spam") == 1

    def test_remove_anti_pattern(self, tmp_path):
        """Test removing an anti-pattern."""
        from reos.cairn.identity import add_anti_pattern, remove_anti_pattern

        with patch("reos.cairn.identity._anti_patterns_path") as mock_path:
            mock_path.return_value = tmp_path / "anti_patterns.json"

            add_anti_pattern("spam")
            add_anti_pattern("marketing")

            patterns = remove_anti_pattern("spam")
            assert "spam" not in patterns
            assert "marketing" in patterns


# =============================================================================
# Integration Tests
# =============================================================================


class TestCoherenceIntegration:
    """Integration tests for the coherence system."""

    def test_full_verification_flow(self):
        """Test complete verification flow."""
        # Create identity
        identity = IdentityModel(
            core="I am a software engineer focused on building productivity tools for developers.",
            facets=[
                IdentityFacet(
                    name="goal",
                    source="act:tooling",
                    content="Build developer productivity tools to help engineers",
                    weight=2.0,
                ),
            ],
            anti_patterns=["crypto", "nft"],
        )

        verifier = CoherenceVerifier(identity, llm=None)

        # Test coherent demand - uses keywords that overlap with identity
        dev_demand = AttentionDemand.create(
            source="work",
            content="Build new productivity tools for developers",
            urgency=6,
        )
        result = verifier.verify(dev_demand)
        # Heuristic mode uses keyword overlap - should find "build", "productivity", "tools", "developers"
        assert result.overall_score > 0
        assert result.recommendation in ("accept", "defer")

        # Test anti-pattern rejection
        crypto_demand = AttentionDemand.create(
            source="email",
            content="Check out this new crypto opportunity!",
            urgency=5,
        )
        result = verifier.verify(crypto_demand)
        assert result.recommendation == "reject"
        assert result.overall_score == -1.0

    def test_trace_creation_and_storage(self):
        """Test that traces are correctly created."""
        from reos.cairn.identity import get_identity_hash

        identity = IdentityModel(
            core="Test identity",
            facets=[],
            anti_patterns=[],
        )

        demand = AttentionDemand.create(
            source="test",
            content="Test demand",
            urgency=5,
        )

        verifier = CoherenceVerifier(identity, llm=None)
        result = verifier.verify(demand)

        # Create trace
        trace = CoherenceTrace.create(result, get_identity_hash(identity))

        assert trace.demand_id == demand.id
        assert trace.final_score == result.overall_score
        assert trace.recommendation == result.recommendation
        assert trace.identity_hash == get_identity_hash(identity)
