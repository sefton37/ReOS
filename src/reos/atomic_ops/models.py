"""Data models for atomic operations.

This module defines the core data structures for the V2 atomic operations
architecture. Every user request is decomposed into atomic operations
classified by the 3x2x3 taxonomy.

Taxonomy:
- Destination: stream | file | process
- Consumer: human | machine
- Semantics: read | interpret | execute
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional
from uuid import uuid4


class DestinationType(str, Enum):
    """Where the operation output goes."""
    STREAM = "stream"    # Ephemeral output, displayed once
    FILE = "file"        # Persistent storage
    PROCESS = "process"  # Spawns a system process


class ConsumerType(str, Enum):
    """Who consumes the operation result."""
    HUMAN = "human"      # Human reads and interprets
    MACHINE = "machine"  # Machine processes further


class ExecutionSemantics(str, Enum):
    """What action the operation takes."""
    READ = "read"        # Retrieve existing data
    INTERPRET = "interpret"  # Analyze or transform data
    EXECUTE = "execute"  # Perform side-effecting action


class OperationStatus(str, Enum):
    """Status of an atomic operation."""
    CLASSIFYING = "classifying"
    AWAITING_VERIFICATION = "awaiting_verification"
    AWAITING_APPROVAL = "awaiting_approval"
    EXECUTING = "executing"
    COMPLETE = "complete"
    FAILED = "failed"
    DECOMPOSED = "decomposed"


class VerificationLayer(str, Enum):
    """The 5-layer verification system."""
    SYNTAX = "syntax"
    SEMANTIC = "semantic"
    BEHAVIORAL = "behavioral"
    SAFETY = "safety"
    INTENT = "intent"


class FeedbackType(str, Enum):
    """Types of user feedback."""
    EXPLICIT_RATING = "explicit_rating"
    CORRECTION = "correction"
    APPROVAL = "approval"
    BEHAVIORAL = "behavioral"
    LONG_TERM = "long_term"


@dataclass
class Classification:
    """Result of classifying an operation."""
    destination: DestinationType
    consumer: ConsumerType
    semantics: ExecutionSemantics
    confidence: float
    reasoning: dict[str, str] = field(default_factory=dict)
    alternatives: list[dict] = field(default_factory=list)


@dataclass
class Features:
    """Extracted features for ML classification."""
    # Lexical features
    token_count: int = 0
    char_count: int = 0
    verb_count: int = 0
    noun_count: int = 0
    verbs: list[str] = field(default_factory=list)
    nouns: list[str] = field(default_factory=list)
    has_file_extension: bool = False
    file_extension_type: Optional[str] = None
    avg_word_length: float = 0.0

    # Syntactic features
    has_imperative_verb: bool = False
    has_interrogative: bool = False
    has_conditional: bool = False
    has_negation: bool = False
    sentence_count: int = 1

    # Domain features
    mentions_code: bool = False
    detected_languages: list[str] = field(default_factory=list)
    mentions_system_resource: bool = False
    has_file_operation: bool = False
    has_immediate_verb: bool = False
    mentions_testing: bool = False
    mentions_git: bool = False

    # Context features
    time_of_day: int = 0
    day_of_week: int = 0
    recent_operation_count: int = 0
    recent_success_rate: float = 0.0

    # Semantic features (embeddings stored separately as blobs)
    request_hash: str = ""


@dataclass
class VerificationResult:
    """Result of a single verification layer."""
    layer: VerificationLayer
    passed: bool
    confidence: float
    issues: list[str] = field(default_factory=list)
    details: str = ""
    execution_time_ms: int = 0


@dataclass
class ExecutionResult:
    """Result of executing an operation."""
    success: bool
    exit_code: Optional[int] = None
    stdout: str = ""
    stderr: str = ""
    duration_ms: int = 0
    files_affected: list[str] = field(default_factory=list)
    processes_spawned: list[int] = field(default_factory=list)


@dataclass
class StateSnapshot:
    """Captured state before/after execution."""
    timestamp: datetime = field(default_factory=datetime.now)
    files: dict[str, dict] = field(default_factory=dict)  # path -> {exists, hash, backup_path}
    processes: list[dict] = field(default_factory=list)
    system_metrics: dict[str, Any] = field(default_factory=dict)


@dataclass
class ReversibilityInfo:
    """Information about whether an operation can be undone."""
    reversible: bool
    method: Optional[str] = None  # 'restore_backup', 'inverse_command', etc.
    undo_commands: list[str] = field(default_factory=list)
    backup_files: dict[str, str] = field(default_factory=dict)  # original -> backup
    reason: str = ""


@dataclass
class AtomicOperation:
    """A single atomic operation - the core unit of work.

    Every user request is decomposed into one or more atomic operations,
    each classified by the 3x2x3 taxonomy and tracked through verification,
    execution, and feedback collection.
    """
    # Identity
    id: str = field(default_factory=lambda: str(uuid4()))
    block_id: Optional[str] = None  # Links to blocks table

    # User input
    user_request: str = ""
    user_id: str = ""

    # Classification
    classification: Optional[Classification] = None

    # Features (for ML)
    features: Optional[Features] = None

    # Decomposition
    is_decomposed: bool = False
    parent_id: Optional[str] = None
    child_ids: list[str] = field(default_factory=list)

    # Verification
    verification_results: dict[str, VerificationResult] = field(default_factory=dict)

    # Execution
    status: OperationStatus = OperationStatus.CLASSIFYING
    execution_result: Optional[ExecutionResult] = None
    state_before: Optional[StateSnapshot] = None
    state_after: Optional[StateSnapshot] = None
    reversibility: Optional[ReversibilityInfo] = None

    # Timestamps
    created_at: datetime = field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None

    # Agent source
    source_agent: str = ""  # 'cairn', 'reos', 'riva'

    @property
    def destination(self) -> Optional[DestinationType]:
        return self.classification.destination if self.classification else None

    @property
    def consumer(self) -> Optional[ConsumerType]:
        return self.classification.consumer if self.classification else None

    @property
    def semantics(self) -> Optional[ExecutionSemantics]:
        return self.classification.semantics if self.classification else None

    @property
    def confidence(self) -> float:
        return self.classification.confidence if self.classification else 0.0

    def is_verified(self) -> bool:
        """Check if operation passed all verification layers."""
        if not self.verification_results:
            return False
        # Syntax and safety must pass
        for layer in [VerificationLayer.SYNTAX, VerificationLayer.SAFETY]:
            if layer.value in self.verification_results:
                if not self.verification_results[layer.value].passed:
                    return False
        return True

    def overall_verification_confidence(self) -> float:
        """Compute aggregate verification confidence."""
        if not self.verification_results:
            return 0.0

        weights = {
            VerificationLayer.SYNTAX.value: 0.2,
            VerificationLayer.SEMANTIC.value: 0.2,
            VerificationLayer.BEHAVIORAL.value: 0.2,
            VerificationLayer.SAFETY.value: 0.2,
            VerificationLayer.INTENT.value: 0.2,
        }

        total = sum(
            self.verification_results[layer].confidence * weight
            for layer, weight in weights.items()
            if layer in self.verification_results
        )
        return total


@dataclass
class UserFeedback:
    """User feedback on an operation."""
    id: str = field(default_factory=lambda: str(uuid4()))
    operation_id: str = ""
    user_id: str = ""
    feedback_type: FeedbackType = FeedbackType.APPROVAL

    # Explicit rating
    rating: Optional[int] = None  # 1-5
    rating_dimensions: dict[str, int] = field(default_factory=dict)
    comment: Optional[str] = None

    # Correction
    system_classification: Optional[dict] = None
    user_corrected_classification: Optional[dict] = None
    correction_reasoning: Optional[str] = None

    # Approval
    approved: Optional[bool] = None
    modified: bool = False
    modification_extent: float = 0.0
    modification_details: Optional[dict] = None
    time_to_decision_ms: Optional[int] = None

    # Behavioral
    retried: bool = False
    time_to_retry_ms: Optional[int] = None
    undid: bool = False
    time_to_undo_ms: Optional[int] = None
    abandoned: bool = False

    # Long-term
    operation_persisted: Optional[bool] = None
    days_persisted: Optional[int] = None
    reused_pattern: bool = False
    referenced_later: bool = False

    # Meta
    feedback_confidence: float = 0.5
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class LearningMetrics:
    """Aggregated learning metrics for a user."""
    user_id: str = ""
    window_start: datetime = field(default_factory=datetime.now)
    window_end: datetime = field(default_factory=datetime.now)
    window_days: int = 7

    # Accuracy metrics
    classification_accuracy: float = 0.0
    sample_size: int = 0

    # Breakdown by category
    accuracy_by_destination: dict[str, float] = field(default_factory=dict)
    accuracy_by_consumer: dict[str, float] = field(default_factory=dict)
    accuracy_by_semantics: dict[str, float] = field(default_factory=dict)

    # Improvement tracking
    previous_accuracy: Optional[float] = None
    improvement: Optional[float] = None

    # User satisfaction
    avg_rating: Optional[float] = None
    correction_rate: float = 0.0
