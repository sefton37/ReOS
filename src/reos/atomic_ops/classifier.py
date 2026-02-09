"""Classification pipeline for atomic operations.

This module classifies user requests into the 3x2x3 taxonomy:
- Destination: stream | file | process
- Consumer: human | machine
- Semantics: read | interpret | execute

Uses sentence-transformers for semantic similarity matching against
canonical examples, combined with feature-based heuristics.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    import numpy as np

from .features import FeatureExtractor, cosine_similarity
from .models import (
    Classification,
    ConsumerType,
    DestinationType,
    ExecutionSemantics,
    Features,
)


@dataclass
class CanonicalExample:
    """A canonical example for classification training/matching."""
    request: str
    destination: DestinationType
    consumer: ConsumerType
    semantics: ExecutionSemantics
    embedding: Optional[bytes] = None


# Canonical examples for each category
# These are used for semantic similarity matching
CANONICAL_EXAMPLES = [
    # Stream + Human + Read (display information)
    CanonicalExample("show memory usage", DestinationType.STREAM, ConsumerType.HUMAN, ExecutionSemantics.READ),
    CanonicalExample("what's my disk space", DestinationType.STREAM, ConsumerType.HUMAN, ExecutionSemantics.READ),
    CanonicalExample("list running processes", DestinationType.STREAM, ConsumerType.HUMAN, ExecutionSemantics.READ),
    CanonicalExample("show today's calendar", DestinationType.STREAM, ConsumerType.HUMAN, ExecutionSemantics.READ),
    CanonicalExample("what should I focus on", DestinationType.STREAM, ConsumerType.HUMAN, ExecutionSemantics.READ),
    CanonicalExample("show git status", DestinationType.STREAM, ConsumerType.HUMAN, ExecutionSemantics.READ),

    # Stream + Human + Interpret (explain/analyze)
    CanonicalExample("explain this error", DestinationType.STREAM, ConsumerType.HUMAN, ExecutionSemantics.INTERPRET),
    CanonicalExample("what does this code do", DestinationType.STREAM, ConsumerType.HUMAN, ExecutionSemantics.INTERPRET),
    CanonicalExample("analyze memory usage trends", DestinationType.STREAM, ConsumerType.HUMAN, ExecutionSemantics.INTERPRET),
    CanonicalExample("why is this test failing", DestinationType.STREAM, ConsumerType.HUMAN, ExecutionSemantics.INTERPRET),
    CanonicalExample("summarize my week", DestinationType.STREAM, ConsumerType.HUMAN, ExecutionSemantics.INTERPRET),

    # Stream + Human + Interpret (conversational / greetings / small talk)
    CanonicalExample("good morning", DestinationType.STREAM, ConsumerType.HUMAN, ExecutionSemantics.INTERPRET),
    CanonicalExample("hello", DestinationType.STREAM, ConsumerType.HUMAN, ExecutionSemantics.INTERPRET),
    CanonicalExample("hi there", DestinationType.STREAM, ConsumerType.HUMAN, ExecutionSemantics.INTERPRET),
    CanonicalExample("hey", DestinationType.STREAM, ConsumerType.HUMAN, ExecutionSemantics.INTERPRET),
    CanonicalExample("good afternoon", DestinationType.STREAM, ConsumerType.HUMAN, ExecutionSemantics.INTERPRET),
    CanonicalExample("good evening", DestinationType.STREAM, ConsumerType.HUMAN, ExecutionSemantics.INTERPRET),
    CanonicalExample("how are you", DestinationType.STREAM, ConsumerType.HUMAN, ExecutionSemantics.INTERPRET),
    CanonicalExample("thanks", DestinationType.STREAM, ConsumerType.HUMAN, ExecutionSemantics.INTERPRET),
    CanonicalExample("thank you", DestinationType.STREAM, ConsumerType.HUMAN, ExecutionSemantics.INTERPRET),
    CanonicalExample("goodbye", DestinationType.STREAM, ConsumerType.HUMAN, ExecutionSemantics.INTERPRET),
    CanonicalExample("see you later", DestinationType.STREAM, ConsumerType.HUMAN, ExecutionSemantics.INTERPRET),
    CanonicalExample("nice work", DestinationType.STREAM, ConsumerType.HUMAN, ExecutionSemantics.INTERPRET),

    # Stream + Machine + Read (machine-readable output)
    CanonicalExample("get process list as json", DestinationType.STREAM, ConsumerType.MACHINE, ExecutionSemantics.READ),
    CanonicalExample("output memory stats for parsing", DestinationType.STREAM, ConsumerType.MACHINE, ExecutionSemantics.READ),
    CanonicalExample("return calendar events as structured data", DestinationType.STREAM, ConsumerType.MACHINE, ExecutionSemantics.READ),

    # File + Human + Read (read file for human)
    CanonicalExample("show me the contents of README.md", DestinationType.FILE, ConsumerType.HUMAN, ExecutionSemantics.READ),
    CanonicalExample("read my notes file", DestinationType.FILE, ConsumerType.HUMAN, ExecutionSemantics.READ),
    CanonicalExample("open config.yaml", DestinationType.FILE, ConsumerType.HUMAN, ExecutionSemantics.READ),

    # File + Human + Execute (create/modify files)
    CanonicalExample("save this to notes.txt", DestinationType.FILE, ConsumerType.HUMAN, ExecutionSemantics.EXECUTE),
    CanonicalExample("create a new todo list", DestinationType.FILE, ConsumerType.HUMAN, ExecutionSemantics.EXECUTE),
    CanonicalExample("add a reminder for tomorrow", DestinationType.FILE, ConsumerType.HUMAN, ExecutionSemantics.EXECUTE),
    CanonicalExample("create a new scene in Career act", DestinationType.FILE, ConsumerType.HUMAN, ExecutionSemantics.EXECUTE),
    CanonicalExample("update the meeting notes", DestinationType.FILE, ConsumerType.HUMAN, ExecutionSemantics.EXECUTE),

    # File + Machine + Execute (programmatic file operations)
    CanonicalExample("write test results to output.json", DestinationType.FILE, ConsumerType.MACHINE, ExecutionSemantics.EXECUTE),
    CanonicalExample("export data as csv", DestinationType.FILE, ConsumerType.MACHINE, ExecutionSemantics.EXECUTE),
    CanonicalExample("generate coverage report", DestinationType.FILE, ConsumerType.MACHINE, ExecutionSemantics.EXECUTE),

    # Process + Machine + Execute (run commands)
    CanonicalExample("run pytest", DestinationType.PROCESS, ConsumerType.MACHINE, ExecutionSemantics.EXECUTE),
    CanonicalExample("start the docker container", DestinationType.PROCESS, ConsumerType.MACHINE, ExecutionSemantics.EXECUTE),
    CanonicalExample("stop nginx service", DestinationType.PROCESS, ConsumerType.MACHINE, ExecutionSemantics.EXECUTE),
    CanonicalExample("restart postgresql", DestinationType.PROCESS, ConsumerType.MACHINE, ExecutionSemantics.EXECUTE),
    CanonicalExample("kill process 1234", DestinationType.PROCESS, ConsumerType.MACHINE, ExecutionSemantics.EXECUTE),
    CanonicalExample("install numpy package", DestinationType.PROCESS, ConsumerType.MACHINE, ExecutionSemantics.EXECUTE),
    CanonicalExample("git push to origin", DestinationType.PROCESS, ConsumerType.MACHINE, ExecutionSemantics.EXECUTE),
    CanonicalExample("build the project", DestinationType.PROCESS, ConsumerType.MACHINE, ExecutionSemantics.EXECUTE),

    # Process + Human + Execute (interactive processes)
    CanonicalExample("open firefox", DestinationType.PROCESS, ConsumerType.HUMAN, ExecutionSemantics.EXECUTE),
    CanonicalExample("launch code editor", DestinationType.PROCESS, ConsumerType.HUMAN, ExecutionSemantics.EXECUTE),
    CanonicalExample("open file manager", DestinationType.PROCESS, ConsumerType.HUMAN, ExecutionSemantics.EXECUTE),
]


@dataclass
class ClassificationConfig:
    """Configuration for classification behavior."""
    # Similarity thresholds
    high_confidence_threshold: float = 0.85
    medium_confidence_threshold: float = 0.65
    low_confidence_threshold: float = 0.45

    # Feature weights for hybrid classification
    semantic_weight: float = 0.6  # Weight for embedding similarity
    feature_weight: float = 0.4   # Weight for feature-based rules

    # When to require decomposition
    decomposition_confidence_threshold: float = 0.5


@dataclass
class ClassificationResult:
    """Extended classification result with alternatives."""
    classification: Classification
    top_matches: list[tuple[CanonicalExample, float]] = field(default_factory=list)
    feature_signals: dict[str, str] = field(default_factory=dict)


class AtomicClassifier:
    """Classify user requests into the 3x2x3 taxonomy.

    Uses hybrid approach:
    1. Semantic similarity to canonical examples (sentence-transformers)
    2. Feature-based heuristics (keywords, patterns)
    3. Combined scoring with confidence calibration
    """

    def __init__(
        self,
        config: Optional[ClassificationConfig] = None,
        feature_extractor: Optional[FeatureExtractor] = None,
    ):
        """Initialize classifier.

        Args:
            config: Classification configuration.
            feature_extractor: Feature extractor instance.
        """
        self.config = config or ClassificationConfig()
        self.feature_extractor = feature_extractor or FeatureExtractor()
        self._canonical_embeddings: dict[int, bytes] = {}
        self._embeddings_initialized = False

    def initialize_embeddings(self) -> bool:
        """Initialize embeddings for canonical examples.

        Call this once after loading the embedding model.
        Returns True if successful.
        """
        if not self.feature_extractor._model_loaded:
            if not self.feature_extractor.load_embedding_model():
                return False

        # Generate embeddings for all canonical examples
        for i, example in enumerate(CANONICAL_EXAMPLES):
            _, embedding = self.feature_extractor.extract(example.request)
            if embedding is not None:
                self._canonical_embeddings[i] = embedding
                example.embedding = embedding

        self._embeddings_initialized = len(self._canonical_embeddings) > 0
        return self._embeddings_initialized

    def classify(
        self,
        request: str,
        context: Optional[dict] = None,
    ) -> ClassificationResult:
        """Classify a user request into the 3x2x3 taxonomy.

        Args:
            request: User's natural language request.
            context: Optional context for feature extraction.

        Returns:
            ClassificationResult with classification and metadata.
        """
        # Extract features and embedding
        features, embedding = self.feature_extractor.extract(request, context)

        # Get semantic similarity scores if embeddings available
        semantic_scores = {}
        if embedding is not None and self._embeddings_initialized:
            semantic_scores = self._compute_semantic_scores(embedding)

        # Get feature-based scores
        feature_scores = self._compute_feature_scores(features)

        # Combine scores
        combined = self._combine_scores(semantic_scores, feature_scores)

        # Select best classification
        best_dest, dest_conf, dest_reasoning = self._select_best(
            combined["destination"], "destination"
        )
        best_cons, cons_conf, cons_reasoning = self._select_best(
            combined["consumer"], "consumer"
        )
        best_sem, sem_conf, sem_reasoning = self._select_best(
            combined["semantics"], "semantics"
        )

        # Overall confidence is geometric mean
        overall_confidence = (dest_conf * cons_conf * sem_conf) ** (1/3)

        # Build classification
        classification = Classification(
            destination=DestinationType(best_dest),
            consumer=ConsumerType(best_cons),
            semantics=ExecutionSemantics(best_sem),
            confidence=overall_confidence,
            reasoning={
                "destination": dest_reasoning,
                "consumer": cons_reasoning,
                "semantics": sem_reasoning,
            },
            alternatives=self._get_alternatives(combined),
        )

        # Get top matching canonical examples
        top_matches = self._get_top_matches(semantic_scores)

        # Collect feature signals for debugging
        feature_signals = self._collect_feature_signals(features)

        return ClassificationResult(
            classification=classification,
            top_matches=top_matches,
            feature_signals=feature_signals,
        )

    def _compute_semantic_scores(
        self,
        embedding: bytes,
    ) -> dict[int, float]:
        """Compute similarity scores against canonical examples."""
        scores = {}
        for i, canonical_emb in self._canonical_embeddings.items():
            scores[i] = cosine_similarity(embedding, canonical_emb)
        return scores

    def _compute_feature_scores(
        self,
        features: Features,
    ) -> dict[str, dict[str, float]]:
        """Compute feature-based classification scores."""
        scores = {
            "destination": {"stream": 0.0, "file": 0.0, "process": 0.0},
            "consumer": {"human": 0.0, "machine": 0.0},
            "semantics": {"read": 0.0, "interpret": 0.0, "execute": 0.0},
        }

        # Destination signals
        if features.has_file_extension or features.has_file_operation:
            scores["destination"]["file"] += 0.4
        if features.mentions_system_resource or features.has_immediate_verb:
            scores["destination"]["process"] += 0.3
        if features.has_interrogative:
            scores["destination"]["stream"] += 0.3
        if any(v in features.verbs for v in ["show", "display", "list", "what"]):
            scores["destination"]["stream"] += 0.3
        if any(v in features.verbs for v in ["run", "start", "stop", "kill", "restart", "install"]):
            scores["destination"]["process"] += 0.4
        if any(v in features.verbs for v in ["save", "write", "create", "add", "update"]):
            scores["destination"]["file"] += 0.3

        # Consumer signals
        if features.has_interrogative or "explain" in features.verbs:
            scores["consumer"]["human"] += 0.5
        if features.mentions_testing or features.mentions_git:
            scores["consumer"]["machine"] += 0.3
        if "json" in " ".join(features.nouns) or "csv" in " ".join(features.nouns):
            scores["consumer"]["machine"] += 0.4
        if features.mentions_code and not features.has_interrogative:
            scores["consumer"]["machine"] += 0.2
        # Default slight bias toward human
        scores["consumer"]["human"] += 0.1

        # Semantics signals
        if features.has_interrogative:
            if "why" in features.verbs or "explain" in features.verbs:
                scores["semantics"]["interpret"] += 0.5
            else:
                scores["semantics"]["read"] += 0.4
        if any(v in features.verbs for v in ["show", "list", "get", "fetch", "display"]):
            scores["semantics"]["read"] += 0.4
        if any(v in features.verbs for v in ["explain", "analyze", "summarize", "why"]):
            scores["semantics"]["interpret"] += 0.4
        if any(v in features.verbs for v in ["run", "execute", "start", "stop", "create", "save", "install", "delete"]):
            scores["semantics"]["execute"] += 0.5

        # Conversational default: when no signals fire, assume human speech
        # Principle: uncertainty → conversation, not uncertainty → action
        if sum(scores["destination"].values()) == 0.0:
            scores["destination"]["stream"] += 0.3
        if sum(scores["semantics"].values()) == 0.0:
            scores["semantics"]["interpret"] += 0.3

        # Normalize scores
        for dimension in scores:
            total = sum(scores[dimension].values())
            if total > 0:
                for key in scores[dimension]:
                    scores[dimension][key] /= total

        return scores

    def _combine_scores(
        self,
        semantic_scores: dict[int, float],
        feature_scores: dict[str, dict[str, float]],
    ) -> dict[str, dict[str, float]]:
        """Combine semantic and feature scores."""
        combined = {
            "destination": {"stream": 0.0, "file": 0.0, "process": 0.0},
            "consumer": {"human": 0.0, "machine": 0.0},
            "semantics": {"read": 0.0, "interpret": 0.0, "execute": 0.0},
        }

        # Aggregate semantic scores by category
        if semantic_scores:
            semantic_by_dim: dict[str, dict[str, list[float]]] = {
                "destination": {"stream": [], "file": [], "process": []},
                "consumer": {"human": [], "machine": []},
                "semantics": {"read": [], "interpret": [], "execute": []},
            }

            for i, score in semantic_scores.items():
                if i < len(CANONICAL_EXAMPLES):
                    example = CANONICAL_EXAMPLES[i]
                    semantic_by_dim["destination"][example.destination.value].append(score)
                    semantic_by_dim["consumer"][example.consumer.value].append(score)
                    semantic_by_dim["semantics"][example.semantics.value].append(score)

            # Use max score per category (best match)
            for dim in semantic_by_dim:
                for cat, scores_list in semantic_by_dim[dim].items():
                    if scores_list:
                        combined[dim][cat] = max(scores_list) * self.config.semantic_weight

        # Add feature scores
        for dim in feature_scores:
            for cat, score in feature_scores[dim].items():
                combined[dim][cat] += score * self.config.feature_weight

        return combined

    def _select_best(
        self,
        scores: dict[str, float],
        dimension: str,
    ) -> tuple[str, float, str]:
        """Select best category and compute confidence."""
        if not scores:
            # Default fallbacks
            defaults = {
                "destination": "stream",
                "consumer": "human",
                "semantics": "read",
            }
            return defaults[dimension], 0.5, "default (no scores)"

        # Sort by score
        sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        best, best_score = sorted_scores[0]

        # Confidence based on margin over second best
        if len(sorted_scores) > 1:
            second_score = sorted_scores[1][1]
            margin = best_score - second_score
            confidence = min(0.95, 0.5 + margin)
        else:
            confidence = min(0.95, best_score)

        # Build reasoning
        reasoning = f"{best} (score={best_score:.2f}, margin={confidence:.2f})"

        return best, confidence, reasoning

    def _get_alternatives(
        self,
        combined: dict[str, dict[str, float]],
    ) -> list[dict]:
        """Get alternative classifications."""
        alternatives = []

        for dim, scores in combined.items():
            sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
            if len(sorted_scores) > 1:
                second = sorted_scores[1]
                if second[1] > 0.2:  # Only include if score is meaningful
                    alternatives.append({
                        "dimension": dim,
                        "alternative": second[0],
                        "score": second[1],
                    })

        return alternatives

    def _get_top_matches(
        self,
        semantic_scores: dict[int, float],
    ) -> list[tuple[CanonicalExample, float]]:
        """Get top matching canonical examples."""
        if not semantic_scores:
            return []

        sorted_matches = sorted(
            semantic_scores.items(),
            key=lambda x: x[1],
            reverse=True
        )

        return [
            (CANONICAL_EXAMPLES[i], score)
            for i, score in sorted_matches[:5]
            if i < len(CANONICAL_EXAMPLES)
        ]

    def _collect_feature_signals(self, features: Features) -> dict[str, str]:
        """Collect notable feature signals for debugging."""
        signals = {}

        if features.has_interrogative:
            signals["interrogative"] = "true"
        if features.has_imperative_verb:
            signals["imperative"] = "true"
        if features.has_file_extension:
            signals["file_extension"] = features.file_extension_type or "unknown"
        if features.mentions_code:
            signals["code_related"] = "true"
        if features.mentions_system_resource:
            signals["system_related"] = "true"
        if features.mentions_git:
            signals["git_related"] = "true"
        if features.verbs:
            signals["verbs"] = ", ".join(features.verbs[:5])

        return signals

    def needs_decomposition(self, result: ClassificationResult) -> bool:
        """Check if request should be decomposed into sub-operations.

        Returns True if:
        - Confidence is below threshold
        - Multiple high-scoring alternatives exist
        """
        if result.classification.confidence < self.config.decomposition_confidence_threshold:
            return True

        # Check for competing alternatives
        high_scoring_alts = [
            alt for alt in result.classification.alternatives
            if alt["score"] > 0.4
        ]
        if len(high_scoring_alts) >= 2:
            return True

        return False
