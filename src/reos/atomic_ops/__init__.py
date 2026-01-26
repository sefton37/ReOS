"""Atomic Operations Module - V2 Architecture Foundation.

This module implements the atomic operations architecture that unifies
all Talking Rock agents (CAIRN, ReOS, RIVA) under a common classification,
verification, execution, and learning framework.

Core Concepts:
- Every user request is decomposed into atomic operations
- Operations are classified by the 3x2x3 taxonomy:
  - Destination: stream | file | process
  - Consumer: human | machine
  - Semantics: read | interpret | execute
- Operations pass through 5-layer verification before execution
- User feedback is collected for continuous learning (RLHF)

Usage:
    from reos.atomic_ops import AtomicOpsProcessor

    processor = AtomicOpsProcessor(db_connection)
    operation = processor.process_request(
        request="show memory usage",
        user_id="user-123",
        source_agent="cairn"
    )
"""

from .models import (
    AtomicOperation,
    Classification,
    ConsumerType,
    DestinationType,
    ExecutionResult,
    ExecutionSemantics,
    Features,
    FeedbackType,
    LearningMetrics,
    OperationStatus,
    ReversibilityInfo,
    StateSnapshot,
    UserFeedback,
    VerificationLayer,
    VerificationResult,
)
from .schema import AtomicOpsStore, init_atomic_ops_schema

# Classification pipeline (Phase 2)
from .features import FeatureExtractor, cosine_similarity, embeddings_to_array
from .classifier import (
    AtomicClassifier,
    CanonicalExample,
    ClassificationConfig,
    ClassificationResult,
)
from .decomposer import AtomicDecomposer, DecompositionResult, create_operation_tree
from .processor import AtomicOpsProcessor, ProcessingResult, create_processor

# Verification pipeline (Phase 3)
from .verifiers import (
    BaseVerifier,
    VerificationContext,
    SyntaxVerifier,
    SemanticVerifier,
    BehavioralVerifier,
    SafetyVerifier,
    IntentVerifier,
    VerificationPipeline,
)
from .verifiers.pipeline import VerificationMode, PipelineResult

# Execution engine (Phase 4)
from .executor import (
    ExecutionConfig,
    ExecutionContext,
    OperationExecutor,
    StateCapture,
    create_executor,
)

# RLHF Feedback (Phase 5)
from .feedback import (
    FeedbackCollector,
    FeedbackSession,
    LearningAggregator,
    create_feedback_collector,
    create_learning_aggregator,
)

# CAIRN Integration (Phase 6)
from .cairn_integration import (
    CairnAtomicBridge,
    CairnOperationResult,
    create_cairn_bridge,
)

__all__ = [
    # Models
    "AtomicOperation",
    "Classification",
    "ConsumerType",
    "DestinationType",
    "ExecutionResult",
    "ExecutionSemantics",
    "Features",
    "FeedbackType",
    "LearningMetrics",
    "OperationStatus",
    "ReversibilityInfo",
    "StateSnapshot",
    "UserFeedback",
    "VerificationLayer",
    "VerificationResult",
    # Storage
    "AtomicOpsStore",
    "init_atomic_ops_schema",
    # Feature Extraction (Phase 2)
    "FeatureExtractor",
    "cosine_similarity",
    "embeddings_to_array",
    # Classification (Phase 2)
    "AtomicClassifier",
    "CanonicalExample",
    "ClassificationConfig",
    "ClassificationResult",
    # Decomposition (Phase 2)
    "AtomicDecomposer",
    "DecompositionResult",
    "create_operation_tree",
    # Processor (Phase 2)
    "AtomicOpsProcessor",
    "ProcessingResult",
    "create_processor",
    # Verification (Phase 3)
    "BaseVerifier",
    "VerificationContext",
    "SyntaxVerifier",
    "SemanticVerifier",
    "BehavioralVerifier",
    "SafetyVerifier",
    "IntentVerifier",
    "VerificationPipeline",
    "VerificationMode",
    "PipelineResult",
    # Execution Engine (Phase 4)
    "ExecutionConfig",
    "ExecutionContext",
    "OperationExecutor",
    "StateCapture",
    "create_executor",
    # RLHF Feedback (Phase 5)
    "FeedbackCollector",
    "FeedbackSession",
    "LearningAggregator",
    "create_feedback_collector",
    "create_learning_aggregator",
    # CAIRN Integration (Phase 6)
    "CairnAtomicBridge",
    "CairnOperationResult",
    "create_cairn_bridge",
]
