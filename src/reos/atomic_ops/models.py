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
from typing import Any
from uuid import uuid4


class DestinationType(str, Enum):
    """Where the operation output goes."""

    STREAM = "stream"  # Ephemeral output, displayed once
    FILE = "file"  # Persistent storage
    PROCESS = "process"  # Spawns a system process


class ConsumerType(str, Enum):
    """Who consumes the operation result."""

    HUMAN = "human"  # Human reads and interprets
    MACHINE = "machine"  # Machine processes further


class ExecutionSemantics(str, Enum):
    """What action the operation takes."""

    READ = "read"  # Retrieve existing data
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

    CORRECTION = "correction"
    APPROVAL = "approval"
    REJECTION = "rejection"


@dataclass
class Classification:
    """Result of classifying an operation."""

    destination: DestinationType
    consumer: ConsumerType
    semantics: ExecutionSemantics
    confident: bool = True
    reasoning: str = ""
    # calendar, play, system, conversation, personal, tasks,
    # contacts, knowledge, undo, feedback
    domain: str | None = None
    action_hint: str | None = None  # view, create, update, delete, search, status


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
    exit_code: int | None = None
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
    method: str | None = None  # 'restore_backup', 'inverse_command', etc.
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
    block_id: str | None = None  # Links to blocks table

    # User input
    user_request: str = ""
    user_id: str = ""

    # Classification
    classification: Classification | None = None

    # Decomposition
    is_decomposed: bool = False
    parent_id: str | None = None
    child_ids: list[str] = field(default_factory=list)

    # Verification
    verification_results: dict[str, VerificationResult] = field(default_factory=dict)

    # Execution
    status: OperationStatus = OperationStatus.CLASSIFYING
    execution_result: ExecutionResult | None = None
    state_before: StateSnapshot | None = None
    state_after: StateSnapshot | None = None
    reversibility: ReversibilityInfo | None = None

    # Timestamps
    created_at: datetime = field(default_factory=datetime.now)
    completed_at: datetime | None = None

    # Agent source
    source_agent: str = ""  # 'cairn', 'reos', 'riva'

    @property
    def destination(self) -> DestinationType | None:
        return self.classification.destination if self.classification else None

    @property
    def consumer(self) -> ConsumerType | None:
        return self.classification.consumer if self.classification else None

    @property
    def semantics(self) -> ExecutionSemantics | None:
        return self.classification.semantics if self.classification else None

    @property
    def confidence(self) -> float:
        """Backward-compatible confidence for verification layers."""
        if not self.classification:
            return 0.0
        return 0.9 if self.classification.confident else 0.3

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

    # Correction fields
    system_classification: dict | None = None
    user_corrected_destination: str | None = None
    user_corrected_consumer: str | None = None
    user_corrected_semantics: str | None = None
    correction_reasoning: str | None = None

    # Approval fields
    approved: bool | None = None
    time_to_decision_ms: int | None = None

    # Meta
    created_at: datetime = field(default_factory=datetime.now)
