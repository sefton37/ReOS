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
- Classification uses the LLM already loaded for CAIRN/ReOS
- Operations pass through 5-layer verification before execution
- User feedback (corrections) is fed back as few-shot examples

Usage:
    from reos.atomic_ops import AtomicOpsProcessor

    processor = AtomicOpsProcessor(db_connection, llm=llm_provider)
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
    FeedbackType,
    OperationStatus,
    ReversibilityInfo,
    StateSnapshot,
    UserFeedback,
    VerificationLayer,
    VerificationResult,
)
from .schema import AtomicOpsStore, init_atomic_ops_schema

# Classification (LLM-native)
from .classifier import (
    AtomicClassifier,
    ClassificationResult,
)
from .classification_context import ClassificationContext
from .decomposer import AtomicDecomposer, DecompositionResult, create_operation_tree
from .processor import AtomicOpsProcessor, ProcessingResult, create_processor

# Verification pipeline
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

# Execution engine
from .executor import (
    ExecutionConfig,
    ExecutionContext,
    OperationExecutor,
    StateCapture,
    create_executor,
)

# Feedback
from .feedback import (
    FeedbackCollector,
    FeedbackSession,
    LearningAggregator,
    create_feedback_collector,
    create_learning_aggregator,
)

# CAIRN Integration
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
    "FeedbackType",
    "OperationStatus",
    "ReversibilityInfo",
    "StateSnapshot",
    "UserFeedback",
    "VerificationLayer",
    "VerificationResult",
    # Storage
    "AtomicOpsStore",
    "init_atomic_ops_schema",
    # Classification (LLM-native)
    "AtomicClassifier",
    "ClassificationResult",
    "ClassificationContext",
    # Decomposition
    "AtomicDecomposer",
    "DecompositionResult",
    "create_operation_tree",
    # Processor
    "AtomicOpsProcessor",
    "ProcessingResult",
    "create_processor",
    # Verification
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
    # Execution Engine
    "ExecutionConfig",
    "ExecutionContext",
    "OperationExecutor",
    "StateCapture",
    "create_executor",
    # Feedback
    "FeedbackCollector",
    "FeedbackSession",
    "LearningAggregator",
    "create_feedback_collector",
    "create_learning_aggregator",
    # CAIRN Integration
    "CairnAtomicBridge",
    "CairnOperationResult",
    "create_cairn_bridge",
]
