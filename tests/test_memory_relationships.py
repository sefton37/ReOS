"""Tests for memory/relationships.py - Relationship type system.

Unit tests for:
- RelationshipType enum
- RelationshipSource enum
- Relationship categories
- Inverse relationship function
"""

from __future__ import annotations

import pytest


# =============================================================================
# RelationshipType Tests
# =============================================================================


class TestRelationshipType:
    """Test RelationshipType enum."""

    def test_relationship_type_values(self) -> None:
        """RelationshipType has expected values."""
        from reos.memory.relationships import RelationshipType

        # Logical
        assert RelationshipType.REFERENCES.value == "references"
        assert RelationshipType.FOLLOWS_FROM.value == "follows_from"
        assert RelationshipType.CONTRADICTS.value == "contradicts"
        assert RelationshipType.SUPPORTS.value == "supports"

        # Semantic
        assert RelationshipType.SIMILAR_TO.value == "similar_to"
        assert RelationshipType.RELATED_TO.value == "related_to"
        assert RelationshipType.ELABORATES.value == "elaborates"

        # Causal
        assert RelationshipType.CAUSED_BY.value == "caused_by"
        assert RelationshipType.CAUSES.value == "causes"

        # Feedback
        assert RelationshipType.CORRECTS.value == "corrects"
        assert RelationshipType.SUPERSEDES.value == "supersedes"
        assert RelationshipType.DERIVED_FROM.value == "derived_from"

        # Temporal
        assert RelationshipType.PRECEDED_BY.value == "preceded_by"
        assert RelationshipType.RESPONDS_TO.value == "responds_to"

    def test_relationship_type_from_string(self) -> None:
        """RelationshipType can be created from string value."""
        from reos.memory.relationships import RelationshipType

        assert RelationshipType("references") == RelationshipType.REFERENCES
        assert RelationshipType("follows_from") == RelationshipType.FOLLOWS_FROM
        assert RelationshipType("similar_to") == RelationshipType.SIMILAR_TO

    def test_relationship_type_is_str_subclass(self) -> None:
        """RelationshipType is a str subclass for JSON serialization."""
        from reos.memory.relationships import RelationshipType

        assert isinstance(RelationshipType.REFERENCES, str)
        # Value is the string representation for JSON
        assert RelationshipType.REFERENCES.value == "references"
        # Can be used directly as string in comparisons
        assert RelationshipType.REFERENCES == "references"

    def test_relationship_type_invalid_value(self) -> None:
        """RelationshipType raises ValueError for invalid value."""
        from reos.memory.relationships import RelationshipType

        with pytest.raises(ValueError):
            RelationshipType("invalid_type")

    def test_all_relationship_types_count(self) -> None:
        """RelationshipType has expected number of members."""
        from reos.memory.relationships import RelationshipType

        # 4 logical + 3 semantic + 2 causal + 3 feedback + 2 temporal = 14
        assert len(RelationshipType) == 14


# =============================================================================
# RelationshipSource Tests
# =============================================================================


class TestRelationshipSource:
    """Test RelationshipSource enum."""

    def test_relationship_source_values(self) -> None:
        """RelationshipSource has expected values."""
        from reos.memory.relationships import RelationshipSource

        assert RelationshipSource.USER.value == "user"
        assert RelationshipSource.CAIRN.value == "cairn"
        assert RelationshipSource.INFERRED.value == "inferred"
        assert RelationshipSource.FEEDBACK.value == "feedback"
        assert RelationshipSource.EMBEDDING.value == "embedding"

    def test_relationship_source_from_string(self) -> None:
        """RelationshipSource can be created from string value."""
        from reos.memory.relationships import RelationshipSource

        assert RelationshipSource("user") == RelationshipSource.USER
        assert RelationshipSource("cairn") == RelationshipSource.CAIRN
        assert RelationshipSource("embedding") == RelationshipSource.EMBEDDING

    def test_relationship_source_is_str_subclass(self) -> None:
        """RelationshipSource is a str subclass for JSON serialization."""
        from reos.memory.relationships import RelationshipSource

        assert isinstance(RelationshipSource.USER, str)
        # Value is the string representation for JSON
        assert RelationshipSource.USER.value == "user"
        # Can be used directly as string in comparisons
        assert RelationshipSource.USER == "user"

    def test_all_relationship_sources_count(self) -> None:
        """RelationshipSource has expected number of members."""
        from reos.memory.relationships import RelationshipSource

        assert len(RelationshipSource) == 5


# =============================================================================
# Relationship Categories Tests
# =============================================================================


class TestRelationshipCategories:
    """Test relationship category sets."""

    def test_logical_relationships(self) -> None:
        """LOGICAL_RELATIONSHIPS contains correct types."""
        from reos.memory.relationships import (
            LOGICAL_RELATIONSHIPS,
            RelationshipType,
        )

        expected = {
            RelationshipType.REFERENCES,
            RelationshipType.FOLLOWS_FROM,
            RelationshipType.CONTRADICTS,
            RelationshipType.SUPPORTS,
        }
        assert LOGICAL_RELATIONSHIPS == expected

    def test_semantic_relationships(self) -> None:
        """SEMANTIC_RELATIONSHIPS contains correct types."""
        from reos.memory.relationships import (
            SEMANTIC_RELATIONSHIPS,
            RelationshipType,
        )

        expected = {
            RelationshipType.SIMILAR_TO,
            RelationshipType.RELATED_TO,
            RelationshipType.ELABORATES,
        }
        assert SEMANTIC_RELATIONSHIPS == expected

    def test_causal_relationships(self) -> None:
        """CAUSAL_RELATIONSHIPS contains correct types."""
        from reos.memory.relationships import (
            CAUSAL_RELATIONSHIPS,
            RelationshipType,
        )

        expected = {
            RelationshipType.CAUSED_BY,
            RelationshipType.CAUSES,
        }
        assert CAUSAL_RELATIONSHIPS == expected

    def test_feedback_relationships(self) -> None:
        """FEEDBACK_RELATIONSHIPS contains correct types."""
        from reos.memory.relationships import (
            FEEDBACK_RELATIONSHIPS,
            RelationshipType,
        )

        expected = {
            RelationshipType.CORRECTS,
            RelationshipType.SUPERSEDES,
            RelationshipType.DERIVED_FROM,
        }
        assert FEEDBACK_RELATIONSHIPS == expected

    def test_temporal_relationships(self) -> None:
        """TEMPORAL_RELATIONSHIPS contains correct types."""
        from reos.memory.relationships import (
            TEMPORAL_RELATIONSHIPS,
            RelationshipType,
        )

        expected = {
            RelationshipType.PRECEDED_BY,
            RelationshipType.RESPONDS_TO,
        }
        assert TEMPORAL_RELATIONSHIPS == expected

    def test_categories_cover_all_types(self) -> None:
        """All relationship types are covered by categories."""
        from reos.memory.relationships import (
            RelationshipType,
            LOGICAL_RELATIONSHIPS,
            SEMANTIC_RELATIONSHIPS,
            CAUSAL_RELATIONSHIPS,
            FEEDBACK_RELATIONSHIPS,
            TEMPORAL_RELATIONSHIPS,
        )

        all_categorized = (
            LOGICAL_RELATIONSHIPS
            | SEMANTIC_RELATIONSHIPS
            | CAUSAL_RELATIONSHIPS
            | FEEDBACK_RELATIONSHIPS
            | TEMPORAL_RELATIONSHIPS
        )

        all_types = set(RelationshipType)
        assert all_categorized == all_types

    def test_categories_are_disjoint(self) -> None:
        """Relationship categories don't overlap."""
        from reos.memory.relationships import (
            LOGICAL_RELATIONSHIPS,
            SEMANTIC_RELATIONSHIPS,
            CAUSAL_RELATIONSHIPS,
            FEEDBACK_RELATIONSHIPS,
            TEMPORAL_RELATIONSHIPS,
        )

        categories = [
            LOGICAL_RELATIONSHIPS,
            SEMANTIC_RELATIONSHIPS,
            CAUSAL_RELATIONSHIPS,
            FEEDBACK_RELATIONSHIPS,
            TEMPORAL_RELATIONSHIPS,
        ]

        for i, cat1 in enumerate(categories):
            for cat2 in categories[i + 1:]:
                assert cat1.isdisjoint(cat2), f"Categories overlap: {cat1 & cat2}"


# =============================================================================
# Inverse Relationship Tests
# =============================================================================


class TestGetInverseRelationship:
    """Test get_inverse_relationship function."""

    def test_causes_caused_by_inverse(self) -> None:
        """CAUSES and CAUSED_BY are inverses."""
        from reos.memory.relationships import (
            get_inverse_relationship,
            RelationshipType,
        )

        assert get_inverse_relationship(RelationshipType.CAUSES) == RelationshipType.CAUSED_BY
        assert get_inverse_relationship(RelationshipType.CAUSED_BY) == RelationshipType.CAUSES

    def test_follows_from_supports_inverse(self) -> None:
        """FOLLOWS_FROM and SUPPORTS are inverses."""
        from reos.memory.relationships import (
            get_inverse_relationship,
            RelationshipType,
        )

        assert get_inverse_relationship(RelationshipType.FOLLOWS_FROM) == RelationshipType.SUPPORTS
        assert get_inverse_relationship(RelationshipType.SUPPORTS) == RelationshipType.FOLLOWS_FROM

    def test_responds_to_preceded_by_inverse(self) -> None:
        """RESPONDS_TO and PRECEDED_BY are inverses."""
        from reos.memory.relationships import (
            get_inverse_relationship,
            RelationshipType,
        )

        assert get_inverse_relationship(RelationshipType.RESPONDS_TO) == RelationshipType.PRECEDED_BY
        assert get_inverse_relationship(RelationshipType.PRECEDED_BY) == RelationshipType.RESPONDS_TO

    def test_no_inverse_returns_none(self) -> None:
        """Types without inverses return None."""
        from reos.memory.relationships import (
            get_inverse_relationship,
            RelationshipType,
        )

        # These don't have defined inverses
        assert get_inverse_relationship(RelationshipType.REFERENCES) is None
        assert get_inverse_relationship(RelationshipType.SIMILAR_TO) is None
        assert get_inverse_relationship(RelationshipType.CONTRADICTS) is None
        assert get_inverse_relationship(RelationshipType.CORRECTS) is None

    def test_inverse_is_symmetric(self) -> None:
        """Inverse relationship is symmetric."""
        from reos.memory.relationships import (
            get_inverse_relationship,
            RelationshipType,
        )

        for rel_type in RelationshipType:
            inverse = get_inverse_relationship(rel_type)
            if inverse is not None:
                # Inverse of inverse should be original
                assert get_inverse_relationship(inverse) == rel_type
