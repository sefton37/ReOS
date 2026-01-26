"""Database schema for atomic operations.

This module defines the v11 schema extension for atomic operations.
Operations are stored as blocks (type='atomic_operation') with additional
data in specialized tables.

Schema v11 adds:
- atomic_operations: Core operation data linked to blocks
- classification_log: Classification reasoning and alternatives
- ml_features: Extracted features for ML training
- user_feedback: Multi-type feedback collection
- operation_execution: Execution records with state/undo
- learning_metrics: Aggregated learning data
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    import numpy as np

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

logger = logging.getLogger(__name__)

# Schema version for atomic operations tables
ATOMIC_OPS_SCHEMA_VERSION = 1

# SQL to create atomic operations tables
ATOMIC_OPS_SCHEMA = """
-- Atomic operations table (linked to blocks via block_id)
CREATE TABLE IF NOT EXISTS atomic_operations (
    id TEXT PRIMARY KEY,
    block_id TEXT UNIQUE,  -- Links to blocks table (type='atomic_operation')

    -- User input
    user_request TEXT NOT NULL,
    user_id TEXT NOT NULL,

    -- Classification (3x2x3 taxonomy)
    destination_type TEXT,  -- 'stream', 'file', 'process'
    consumer_type TEXT,     -- 'human', 'machine'
    execution_semantics TEXT,  -- 'read', 'interpret', 'execute'
    classification_confidence REAL,

    -- Decomposition
    is_decomposed INTEGER DEFAULT 0,
    parent_id TEXT,
    child_ids TEXT,  -- JSON array of child operation IDs

    -- Status
    status TEXT NOT NULL DEFAULT 'classifying',

    -- Agent source
    source_agent TEXT,  -- 'cairn', 'reos', 'riva'

    -- Timestamps
    created_at TEXT NOT NULL,
    completed_at TEXT,

    FOREIGN KEY (parent_id) REFERENCES atomic_operations(id),
    CHECK (destination_type IN ('stream', 'file', 'process') OR destination_type IS NULL),
    CHECK (consumer_type IN ('human', 'machine') OR consumer_type IS NULL),
    CHECK (execution_semantics IN ('read', 'interpret', 'execute') OR execution_semantics IS NULL),
    CHECK (status IN ('classifying', 'awaiting_verification', 'awaiting_approval',
                      'executing', 'complete', 'failed', 'decomposed'))
);

CREATE INDEX IF NOT EXISTS idx_atomic_ops_user ON atomic_operations(user_id);
CREATE INDEX IF NOT EXISTS idx_atomic_ops_status ON atomic_operations(status);
CREATE INDEX IF NOT EXISTS idx_atomic_ops_created ON atomic_operations(created_at);
CREATE INDEX IF NOT EXISTS idx_atomic_ops_parent ON atomic_operations(parent_id);
CREATE INDEX IF NOT EXISTS idx_atomic_ops_block ON atomic_operations(block_id);

-- Classification reasoning log
CREATE TABLE IF NOT EXISTS classification_log (
    id TEXT PRIMARY KEY,
    operation_id TEXT NOT NULL,

    -- Classification result
    destination_type TEXT,
    consumer_type TEXT,
    execution_semantics TEXT,
    confidence REAL NOT NULL,

    -- Reasoning
    reasoning_json TEXT NOT NULL,  -- {dimension: explanation}

    -- Alternatives considered (for ML training)
    alternatives_json TEXT,  -- [{destination, consumer, semantics, confidence, rejected_reason}]

    -- Timestamps
    created_at TEXT NOT NULL,

    FOREIGN KEY (operation_id) REFERENCES atomic_operations(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_classification_log_op ON classification_log(operation_id);

-- ML features for training
CREATE TABLE IF NOT EXISTS ml_features (
    operation_id TEXT PRIMARY KEY,

    -- Raw features as JSON (for flexibility)
    features_json TEXT NOT NULL,

    -- Embeddings (binary blobs, float32 arrays)
    request_embedding BLOB,
    verb_embeddings BLOB,
    object_embeddings BLOB,

    -- Scalar features (for fast querying)
    token_count INTEGER,
    verb_count INTEGER,
    noun_count INTEGER,
    has_file_extension INTEGER,
    file_extension_type TEXT,
    mentions_code INTEGER,
    mentions_system_resource INTEGER,
    has_imperative_verb INTEGER,
    has_interrogative INTEGER,

    -- Request hash for deduplication
    request_hash TEXT,

    -- Timestamps
    extracted_at TEXT NOT NULL,

    FOREIGN KEY (operation_id) REFERENCES atomic_operations(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_ml_features_hash ON ml_features(request_hash);

-- User feedback collection
CREATE TABLE IF NOT EXISTS user_feedback (
    id TEXT PRIMARY KEY,
    operation_id TEXT NOT NULL,
    user_id TEXT NOT NULL,

    -- Feedback type
    feedback_type TEXT NOT NULL,  -- 'explicit_rating', 'correction', 'approval', 'behavioral', 'long_term'

    -- Explicit rating
    rating INTEGER,  -- 1-5
    rating_dimensions TEXT,  -- JSON {dimension: score}
    comment TEXT,

    -- Correction
    system_classification TEXT,  -- JSON
    user_corrected_classification TEXT,  -- JSON
    correction_reasoning TEXT,

    -- Approval
    approved INTEGER,
    modified INTEGER DEFAULT 0,
    modification_extent REAL,  -- 0.0-1.0
    modification_details TEXT,  -- JSON
    time_to_decision_ms INTEGER,

    -- Behavioral signals
    retried INTEGER DEFAULT 0,
    time_to_retry_ms INTEGER,
    undid INTEGER DEFAULT 0,
    time_to_undo_ms INTEGER,
    abandoned INTEGER DEFAULT 0,

    -- Long-term outcome
    operation_persisted INTEGER,
    days_persisted INTEGER,
    reused_pattern INTEGER DEFAULT 0,
    referenced_later INTEGER DEFAULT 0,

    -- Meta
    feedback_confidence REAL,
    created_at TEXT NOT NULL,

    FOREIGN KEY (operation_id) REFERENCES atomic_operations(id) ON DELETE CASCADE,
    CHECK (feedback_type IN ('explicit_rating', 'correction', 'approval', 'behavioral', 'long_term'))
);

CREATE INDEX IF NOT EXISTS idx_feedback_operation ON user_feedback(operation_id);
CREATE INDEX IF NOT EXISTS idx_feedback_user ON user_feedback(user_id);
CREATE INDEX IF NOT EXISTS idx_feedback_type ON user_feedback(feedback_type);

-- Operation verification results
CREATE TABLE IF NOT EXISTS operation_verification (
    id TEXT PRIMARY KEY,
    operation_id TEXT NOT NULL,

    -- Verification layer
    layer TEXT NOT NULL,  -- 'syntax', 'semantic', 'behavioral', 'safety', 'intent'

    -- Results
    passed INTEGER NOT NULL,
    confidence REAL NOT NULL,
    issues_json TEXT,  -- JSON array of issues
    details TEXT,
    execution_time_ms INTEGER,

    -- Timestamps
    verified_at TEXT NOT NULL,

    FOREIGN KEY (operation_id) REFERENCES atomic_operations(id) ON DELETE CASCADE,
    CHECK (layer IN ('syntax', 'semantic', 'behavioral', 'safety', 'intent'))
);

CREATE INDEX IF NOT EXISTS idx_verification_operation ON operation_verification(operation_id);
CREATE INDEX IF NOT EXISTS idx_verification_layer ON operation_verification(layer);

-- Operation execution records
CREATE TABLE IF NOT EXISTS operation_execution (
    id TEXT PRIMARY KEY,
    operation_id TEXT NOT NULL,

    -- Execution result
    success INTEGER NOT NULL,
    exit_code INTEGER,
    stdout TEXT,
    stderr TEXT,
    duration_ms INTEGER,

    -- Affected resources
    files_affected TEXT,  -- JSON array
    processes_spawned TEXT,  -- JSON array

    -- State snapshots
    state_before TEXT,  -- JSON
    state_after TEXT,  -- JSON

    -- Reversibility
    reversible INTEGER,
    undo_method TEXT,
    undo_commands TEXT,  -- JSON array
    backup_files TEXT,  -- JSON {original: backup}
    reversibility_reason TEXT,

    -- Timestamps
    executed_at TEXT NOT NULL,

    FOREIGN KEY (operation_id) REFERENCES atomic_operations(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_execution_operation ON operation_execution(operation_id);

-- Learning metrics (aggregated)
CREATE TABLE IF NOT EXISTS learning_metrics (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,

    -- Time window
    window_start TEXT NOT NULL,
    window_end TEXT NOT NULL,
    window_days INTEGER NOT NULL,

    -- Accuracy metrics
    classification_accuracy REAL NOT NULL,
    sample_size INTEGER NOT NULL,

    -- Breakdown by category
    accuracy_by_destination TEXT,  -- JSON
    accuracy_by_consumer TEXT,  -- JSON
    accuracy_by_semantics TEXT,  -- JSON

    -- Improvement tracking
    previous_accuracy REAL,
    improvement REAL,

    -- User satisfaction
    avg_rating REAL,
    correction_rate REAL,

    -- Timestamps
    computed_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_learning_user ON learning_metrics(user_id);
CREATE INDEX IF NOT EXISTS idx_learning_window ON learning_metrics(window_end);

-- Schema version tracking for atomic ops
CREATE TABLE IF NOT EXISTS atomic_ops_schema_version (
    version INTEGER PRIMARY KEY
);

-- Training data view (joins operations with features and feedback)
CREATE VIEW IF NOT EXISTS training_data AS
SELECT
    ao.id AS operation_id,
    ao.user_request,
    ao.destination_type AS system_destination,
    ao.consumer_type AS system_consumer,
    ao.execution_semantics AS system_semantics,
    ao.classification_confidence,
    ao.source_agent,

    mlf.features_json,
    mlf.request_embedding,
    mlf.token_count,
    mlf.verb_count,
    mlf.noun_count,

    uf.feedback_type,
    uf.approved,
    uf.user_corrected_classification,
    uf.rating,
    uf.feedback_confidence,

    -- True labels from feedback
    CASE
        WHEN uf.approved = 1 THEN ao.destination_type
        WHEN uf.user_corrected_classification IS NOT NULL
            THEN json_extract(uf.user_corrected_classification, '$.destination')
        ELSE NULL
    END AS true_destination,
    CASE
        WHEN uf.approved = 1 THEN ao.consumer_type
        WHEN uf.user_corrected_classification IS NOT NULL
            THEN json_extract(uf.user_corrected_classification, '$.consumer')
        ELSE NULL
    END AS true_consumer,
    CASE
        WHEN uf.approved = 1 THEN ao.execution_semantics
        WHEN uf.user_corrected_classification IS NOT NULL
            THEN json_extract(uf.user_corrected_classification, '$.semantics')
        ELSE NULL
    END AS true_semantics,

    ao.created_at,
    uf.created_at AS feedback_at

FROM atomic_operations ao
LEFT JOIN ml_features mlf ON ao.id = mlf.operation_id
LEFT JOIN user_feedback uf ON ao.id = uf.operation_id
WHERE uf.feedback_type IN ('correction', 'approval')
  AND (uf.approved = 1 OR uf.user_corrected_classification IS NOT NULL);
"""


def init_atomic_ops_schema(conn: sqlite3.Connection) -> None:
    """Initialize atomic operations schema.

    This creates all tables for the V2 atomic operations architecture.
    Safe to call multiple times - uses IF NOT EXISTS.
    """
    # Check if already initialized
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='atomic_ops_schema_version'"
    )
    if cursor.fetchone() is not None:
        # Check version
        cursor = conn.execute("SELECT version FROM atomic_ops_schema_version LIMIT 1")
        row = cursor.fetchone()
        if row and row[0] >= ATOMIC_OPS_SCHEMA_VERSION:
            return  # Already at current version

    logger.info(f"Initializing atomic operations schema v{ATOMIC_OPS_SCHEMA_VERSION}")
    conn.executescript(ATOMIC_OPS_SCHEMA)
    conn.execute(
        "INSERT OR REPLACE INTO atomic_ops_schema_version (version) VALUES (?)",
        (ATOMIC_OPS_SCHEMA_VERSION,)
    )
    conn.commit()
    logger.info("Atomic operations schema initialized")


class AtomicOpsStore:
    """Storage operations for atomic operations.

    This class handles all database interactions for the atomic operations
    system, including CRUD operations, feature storage, and feedback collection.
    """

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        init_atomic_ops_schema(conn)

    # =========================================================================
    # ATOMIC OPERATIONS CRUD
    # =========================================================================

    def create_operation(self, op: AtomicOperation) -> str:
        """Create a new atomic operation."""
        now = datetime.now().isoformat()

        self.conn.execute("""
            INSERT INTO atomic_operations (
                id, block_id, user_request, user_id,
                destination_type, consumer_type, execution_semantics,
                classification_confidence, is_decomposed, parent_id, child_ids,
                status, source_agent, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            op.id,
            op.block_id,
            op.user_request,
            op.user_id,
            op.classification.destination.value if op.classification else None,
            op.classification.consumer.value if op.classification else None,
            op.classification.semantics.value if op.classification else None,
            op.classification.confidence if op.classification else None,
            1 if op.is_decomposed else 0,
            op.parent_id,
            json.dumps(op.child_ids) if op.child_ids else None,
            op.status.value,
            op.source_agent,
            now,
        ))
        self.conn.commit()
        return op.id

    def get_operation(self, operation_id: str) -> Optional[AtomicOperation]:
        """Get an atomic operation by ID."""
        cursor = self.conn.execute(
            "SELECT * FROM atomic_operations WHERE id = ?",
            (operation_id,)
        )
        row = cursor.fetchone()
        if not row:
            return None
        return self._row_to_operation(row)

    def update_operation_status(self, operation_id: str, status: OperationStatus) -> None:
        """Update operation status."""
        now = datetime.now().isoformat()
        completed_at = now if status in (OperationStatus.COMPLETE, OperationStatus.FAILED) else None

        self.conn.execute("""
            UPDATE atomic_operations
            SET status = ?, completed_at = ?
            WHERE id = ?
        """, (status.value, completed_at, operation_id))
        self.conn.commit()

    def update_operation_classification(
        self,
        operation_id: str,
        classification: Classification
    ) -> None:
        """Update operation classification."""
        self.conn.execute("""
            UPDATE atomic_operations
            SET destination_type = ?, consumer_type = ?, execution_semantics = ?,
                classification_confidence = ?
            WHERE id = ?
        """, (
            classification.destination.value,
            classification.consumer.value,
            classification.semantics.value,
            classification.confidence,
            operation_id,
        ))
        self.conn.commit()

    def list_operations(
        self,
        user_id: Optional[str] = None,
        status: Optional[OperationStatus] = None,
        source_agent: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[AtomicOperation]:
        """List operations with optional filters."""
        query = "SELECT * FROM atomic_operations WHERE 1=1"
        params: list[Any] = []

        if user_id:
            query += " AND user_id = ?"
            params.append(user_id)
        if status:
            query += " AND status = ?"
            params.append(status.value)
        if source_agent:
            query += " AND source_agent = ?"
            params.append(source_agent)

        query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        cursor = self.conn.execute(query, params)
        return [self._row_to_operation(row) for row in cursor.fetchall()]

    def _row_to_operation(self, row: sqlite3.Row) -> AtomicOperation:
        """Convert a database row to an AtomicOperation."""
        classification = None
        if row["destination_type"]:
            classification = Classification(
                destination=DestinationType(row["destination_type"]),
                consumer=ConsumerType(row["consumer_type"]),
                semantics=ExecutionSemantics(row["execution_semantics"]),
                confidence=row["classification_confidence"] or 0.0,
            )

        return AtomicOperation(
            id=row["id"],
            block_id=row["block_id"],
            user_request=row["user_request"],
            user_id=row["user_id"],
            classification=classification,
            is_decomposed=bool(row["is_decomposed"]),
            parent_id=row["parent_id"],
            child_ids=json.loads(row["child_ids"]) if row["child_ids"] else [],
            status=OperationStatus(row["status"]),
            source_agent=row["source_agent"] or "",
            created_at=datetime.fromisoformat(row["created_at"]),
            completed_at=datetime.fromisoformat(row["completed_at"]) if row["completed_at"] else None,
        )

    # =========================================================================
    # CLASSIFICATION LOG
    # =========================================================================

    def log_classification(
        self,
        operation_id: str,
        classification: Classification,
    ) -> str:
        """Log classification reasoning."""
        from uuid import uuid4
        log_id = str(uuid4())
        now = datetime.now().isoformat()

        self.conn.execute("""
            INSERT INTO classification_log (
                id, operation_id, destination_type, consumer_type, execution_semantics,
                confidence, reasoning_json, alternatives_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            log_id,
            operation_id,
            classification.destination.value,
            classification.consumer.value,
            classification.semantics.value,
            classification.confidence,
            json.dumps(classification.reasoning),
            json.dumps(classification.alternatives),
            now,
        ))
        self.conn.commit()
        return log_id

    # =========================================================================
    # ML FEATURES
    # =========================================================================

    def store_features(
        self,
        operation_id: str,
        features: Features,
        request_embedding: Optional[bytes] = None,
        verb_embeddings: Optional[bytes] = None,
        object_embeddings: Optional[bytes] = None,
    ) -> None:
        """Store ML features for an operation.

        Args:
            operation_id: Operation ID.
            features: Extracted features.
            request_embedding: Request embedding as bytes (float32).
            verb_embeddings: Verb embeddings as bytes (float32).
            object_embeddings: Object embeddings as bytes (float32).
        """
        now = datetime.now().isoformat()

        # Convert features to JSON (excluding embeddings)
        features_dict = {
            "lexical": {
                "token_count": features.token_count,
                "char_count": features.char_count,
                "verb_count": features.verb_count,
                "noun_count": features.noun_count,
                "verbs": features.verbs,
                "nouns": features.nouns,
                "has_file_extension": features.has_file_extension,
                "file_extension_type": features.file_extension_type,
                "avg_word_length": features.avg_word_length,
            },
            "syntactic": {
                "has_imperative_verb": features.has_imperative_verb,
                "has_interrogative": features.has_interrogative,
                "has_conditional": features.has_conditional,
                "has_negation": features.has_negation,
                "sentence_count": features.sentence_count,
            },
            "domain": {
                "mentions_code": features.mentions_code,
                "detected_languages": features.detected_languages,
                "mentions_system_resource": features.mentions_system_resource,
                "has_file_operation": features.has_file_operation,
                "has_immediate_verb": features.has_immediate_verb,
                "mentions_testing": features.mentions_testing,
                "mentions_git": features.mentions_git,
            },
            "context": {
                "time_of_day": features.time_of_day,
                "day_of_week": features.day_of_week,
                "recent_operation_count": features.recent_operation_count,
                "recent_success_rate": features.recent_success_rate,
            },
        }

        self.conn.execute("""
            INSERT OR REPLACE INTO ml_features (
                operation_id, features_json,
                request_embedding, verb_embeddings, object_embeddings,
                token_count, verb_count, noun_count,
                has_file_extension, file_extension_type,
                mentions_code, mentions_system_resource,
                has_imperative_verb, has_interrogative,
                request_hash, extracted_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            operation_id,
            json.dumps(features_dict),
            request_embedding,
            verb_embeddings,
            object_embeddings,
            features.token_count,
            features.verb_count,
            features.noun_count,
            1 if features.has_file_extension else 0,
            features.file_extension_type,
            1 if features.mentions_code else 0,
            1 if features.mentions_system_resource else 0,
            1 if features.has_imperative_verb else 0,
            1 if features.has_interrogative else 0,
            features.request_hash,
            now,
        ))
        self.conn.commit()

    # =========================================================================
    # VERIFICATION RESULTS
    # =========================================================================

    def store_verification(
        self,
        operation_id: str,
        result: VerificationResult,
    ) -> str:
        """Store verification result for an operation."""
        from uuid import uuid4
        ver_id = str(uuid4())
        now = datetime.now().isoformat()

        self.conn.execute("""
            INSERT INTO operation_verification (
                id, operation_id, layer, passed, confidence,
                issues_json, details, execution_time_ms, verified_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            ver_id,
            operation_id,
            result.layer.value,
            1 if result.passed else 0,
            result.confidence,
            json.dumps(result.issues),
            result.details,
            result.execution_time_ms,
            now,
        ))
        self.conn.commit()
        return ver_id

    def get_verification_results(self, operation_id: str) -> dict[str, VerificationResult]:
        """Get all verification results for an operation."""
        cursor = self.conn.execute(
            "SELECT * FROM operation_verification WHERE operation_id = ?",
            (operation_id,)
        )
        results = {}
        for row in cursor.fetchall():
            results[row["layer"]] = VerificationResult(
                layer=VerificationLayer(row["layer"]),
                passed=bool(row["passed"]),
                confidence=row["confidence"],
                issues=json.loads(row["issues_json"]) if row["issues_json"] else [],
                details=row["details"] or "",
                execution_time_ms=row["execution_time_ms"] or 0,
            )
        return results

    # =========================================================================
    # EXECUTION RECORDS
    # =========================================================================

    def store_execution(
        self,
        operation_id: str,
        result: ExecutionResult,
        state_before: Optional[StateSnapshot] = None,
        state_after: Optional[StateSnapshot] = None,
        reversibility: Optional[ReversibilityInfo] = None,
    ) -> str:
        """Store execution record for an operation."""
        from uuid import uuid4
        exec_id = str(uuid4())
        now = datetime.now().isoformat()

        self.conn.execute("""
            INSERT INTO operation_execution (
                id, operation_id, success, exit_code, stdout, stderr, duration_ms,
                files_affected, processes_spawned,
                state_before, state_after,
                reversible, undo_method, undo_commands, backup_files, reversibility_reason,
                executed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            exec_id,
            operation_id,
            1 if result.success else 0,
            result.exit_code,
            result.stdout,
            result.stderr,
            result.duration_ms,
            json.dumps(result.files_affected),
            json.dumps(result.processes_spawned),
            json.dumps(self._snapshot_to_dict(state_before)) if state_before else None,
            json.dumps(self._snapshot_to_dict(state_after)) if state_after else None,
            1 if (reversibility and reversibility.reversible) else 0,
            reversibility.method if reversibility else None,
            json.dumps(reversibility.undo_commands) if reversibility else None,
            json.dumps(reversibility.backup_files) if reversibility else None,
            reversibility.reason if reversibility else None,
            now,
        ))
        self.conn.commit()
        return exec_id

    def _snapshot_to_dict(self, snapshot: StateSnapshot) -> dict:
        """Convert StateSnapshot to JSON-serializable dict."""
        return {
            "timestamp": snapshot.timestamp.isoformat(),
            "files": snapshot.files,
            "processes": snapshot.processes,
            "system_metrics": snapshot.system_metrics,
        }

    # =========================================================================
    # USER FEEDBACK
    # =========================================================================

    def store_feedback(self, feedback: UserFeedback) -> str:
        """Store user feedback."""
        now = datetime.now().isoformat()

        self.conn.execute("""
            INSERT INTO user_feedback (
                id, operation_id, user_id, feedback_type,
                rating, rating_dimensions, comment,
                system_classification, user_corrected_classification, correction_reasoning,
                approved, modified, modification_extent, modification_details, time_to_decision_ms,
                retried, time_to_retry_ms, undid, time_to_undo_ms, abandoned,
                operation_persisted, days_persisted, reused_pattern, referenced_later,
                feedback_confidence, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            feedback.id,
            feedback.operation_id,
            feedback.user_id,
            feedback.feedback_type.value,
            feedback.rating,
            json.dumps(feedback.rating_dimensions) if feedback.rating_dimensions else None,
            feedback.comment,
            json.dumps(feedback.system_classification) if feedback.system_classification else None,
            json.dumps(feedback.user_corrected_classification) if feedback.user_corrected_classification else None,
            feedback.correction_reasoning,
            1 if feedback.approved else (0 if feedback.approved is False else None),
            1 if feedback.modified else 0,
            feedback.modification_extent,
            json.dumps(feedback.modification_details) if feedback.modification_details else None,
            feedback.time_to_decision_ms,
            1 if feedback.retried else 0,
            feedback.time_to_retry_ms,
            1 if feedback.undid else 0,
            feedback.time_to_undo_ms,
            1 if feedback.abandoned else 0,
            1 if feedback.operation_persisted else (0 if feedback.operation_persisted is False else None),
            feedback.days_persisted,
            1 if feedback.reused_pattern else 0,
            1 if feedback.referenced_later else 0,
            feedback.feedback_confidence,
            now,
        ))
        self.conn.commit()
        return feedback.id

    def get_feedback_for_operation(self, operation_id: str) -> list[UserFeedback]:
        """Get all feedback for an operation."""
        cursor = self.conn.execute(
            "SELECT * FROM user_feedback WHERE operation_id = ? ORDER BY created_at",
            (operation_id,)
        )
        return [self._row_to_feedback(row) for row in cursor.fetchall()]

    def _row_to_feedback(self, row: sqlite3.Row) -> UserFeedback:
        """Convert database row to UserFeedback."""
        return UserFeedback(
            id=row["id"],
            operation_id=row["operation_id"],
            user_id=row["user_id"],
            feedback_type=FeedbackType(row["feedback_type"]),
            rating=row["rating"],
            rating_dimensions=json.loads(row["rating_dimensions"]) if row["rating_dimensions"] else {},
            comment=row["comment"],
            system_classification=json.loads(row["system_classification"]) if row["system_classification"] else None,
            user_corrected_classification=json.loads(row["user_corrected_classification"]) if row["user_corrected_classification"] else None,
            correction_reasoning=row["correction_reasoning"],
            approved=bool(row["approved"]) if row["approved"] is not None else None,
            modified=bool(row["modified"]),
            modification_extent=row["modification_extent"] or 0.0,
            modification_details=json.loads(row["modification_details"]) if row["modification_details"] else None,
            time_to_decision_ms=row["time_to_decision_ms"],
            retried=bool(row["retried"]),
            time_to_retry_ms=row["time_to_retry_ms"],
            undid=bool(row["undid"]),
            time_to_undo_ms=row["time_to_undo_ms"],
            abandoned=bool(row["abandoned"]),
            operation_persisted=bool(row["operation_persisted"]) if row["operation_persisted"] is not None else None,
            days_persisted=row["days_persisted"],
            reused_pattern=bool(row["reused_pattern"]),
            referenced_later=bool(row["referenced_later"]),
            feedback_confidence=row["feedback_confidence"] or 0.5,
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    # =========================================================================
    # LEARNING METRICS
    # =========================================================================

    def store_learning_metrics(self, metrics: LearningMetrics) -> str:
        """Store aggregated learning metrics."""
        from uuid import uuid4
        metric_id = str(uuid4())
        now = datetime.now().isoformat()

        self.conn.execute("""
            INSERT INTO learning_metrics (
                id, user_id, window_start, window_end, window_days,
                classification_accuracy, sample_size,
                accuracy_by_destination, accuracy_by_consumer, accuracy_by_semantics,
                previous_accuracy, improvement, avg_rating, correction_rate,
                computed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            metric_id,
            metrics.user_id,
            metrics.window_start.isoformat(),
            metrics.window_end.isoformat(),
            metrics.window_days,
            metrics.classification_accuracy,
            metrics.sample_size,
            json.dumps(metrics.accuracy_by_destination),
            json.dumps(metrics.accuracy_by_consumer),
            json.dumps(metrics.accuracy_by_semantics),
            metrics.previous_accuracy,
            metrics.improvement,
            metrics.avg_rating,
            metrics.correction_rate,
            now,
        ))
        self.conn.commit()
        return metric_id

    # =========================================================================
    # QUERY METHODS
    # =========================================================================

    def get_operations_by_status(
        self,
        user_id: str,
        statuses: list[OperationStatus],
    ) -> list[AtomicOperation]:
        """Get operations by status for a user."""
        placeholders = ",".join("?" for _ in statuses)
        query = f"""
            SELECT * FROM atomic_operations
            WHERE user_id = ? AND status IN ({placeholders})
            ORDER BY created_at DESC
        """
        params = [user_id] + [s.value for s in statuses]
        cursor = self.conn.execute(query, params)
        return [self._row_to_operation(row) for row in cursor.fetchall()]

    def find_similar_operations(
        self,
        embedding: bytes,
        user_id: str,
        limit: int = 5,
    ) -> list[tuple[AtomicOperation, float]]:
        """Find similar operations using embedding cosine similarity.

        Note: This performs similarity computation in Python since SQLite
        doesn't have native vector operations. For production scale,
        consider using a vector database extension.
        """
        import numpy as np

        # Get all operations with embeddings for this user
        cursor = self.conn.execute("""
            SELECT ao.*, mlf.request_embedding
            FROM atomic_operations ao
            JOIN ml_features mlf ON ao.id = mlf.operation_id
            WHERE ao.user_id = ? AND mlf.request_embedding IS NOT NULL
            AND ao.status = 'complete'
        """, (user_id,))

        results = []
        query_vec = np.frombuffer(embedding, dtype=np.float32)
        query_norm = np.linalg.norm(query_vec)

        if query_norm == 0:
            return []

        for row in cursor.fetchall():
            stored_embedding = row["request_embedding"]
            if stored_embedding:
                stored_vec = np.frombuffer(stored_embedding, dtype=np.float32)
                stored_norm = np.linalg.norm(stored_vec)

                if stored_norm > 0:
                    similarity = float(np.dot(query_vec, stored_vec) / (query_norm * stored_norm))
                    op = self._row_to_operation(row)
                    results.append((op, similarity))

        # Sort by similarity descending and limit
        results.sort(key=lambda x: x[1], reverse=True)
        return results[:limit]

    def get_classification_stats(self, user_id: str) -> dict:
        """Get classification statistics for a user.

        Returns accuracy and distribution stats based on user feedback.
        """
        # Get total operations
        cursor = self.conn.execute(
            "SELECT COUNT(*) FROM atomic_operations WHERE user_id = ?",
            (user_id,)
        )
        total_ops = cursor.fetchone()[0]

        # Get operations with approval feedback
        cursor = self.conn.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN uf.approved = 1 THEN 1 ELSE 0 END) as approved,
                SUM(CASE WHEN uf.user_corrected_classification IS NOT NULL THEN 1 ELSE 0 END) as corrected
            FROM atomic_operations ao
            JOIN user_feedback uf ON ao.id = uf.operation_id
            WHERE ao.user_id = ? AND uf.feedback_type IN ('approval', 'correction')
        """, (user_id,))
        feedback_row = cursor.fetchone()

        feedback_total = feedback_row[0] or 0
        approved = feedback_row[1] or 0
        corrected = feedback_row[2] or 0

        accuracy = approved / feedback_total if feedback_total > 0 else 0.0
        correction_rate = corrected / feedback_total if feedback_total > 0 else 0.0

        # Get distribution by destination type
        cursor = self.conn.execute("""
            SELECT destination_type, COUNT(*) as count
            FROM atomic_operations
            WHERE user_id = ? AND destination_type IS NOT NULL
            GROUP BY destination_type
        """, (user_id,))
        dest_dist = {row[0]: row[1] for row in cursor.fetchall()}

        # Get distribution by consumer type
        cursor = self.conn.execute("""
            SELECT consumer_type, COUNT(*) as count
            FROM atomic_operations
            WHERE user_id = ? AND consumer_type IS NOT NULL
            GROUP BY consumer_type
        """, (user_id,))
        consumer_dist = {row[0]: row[1] for row in cursor.fetchall()}

        # Get distribution by semantics
        cursor = self.conn.execute("""
            SELECT execution_semantics, COUNT(*) as count
            FROM atomic_operations
            WHERE user_id = ? AND execution_semantics IS NOT NULL
            GROUP BY execution_semantics
        """, (user_id,))
        semantics_dist = {row[0]: row[1] for row in cursor.fetchall()}

        # Get average rating
        cursor = self.conn.execute("""
            SELECT AVG(rating) FROM user_feedback
            WHERE user_id = ? AND rating IS NOT NULL
        """, (user_id,))
        avg_rating = cursor.fetchone()[0]

        return {
            "total_operations": total_ops,
            "feedback_count": feedback_total,
            "accuracy": accuracy,
            "correction_rate": correction_rate,
            "avg_rating": avg_rating,
            "distribution": {
                "destination": dest_dist,
                "consumer": consumer_dist,
                "semantics": semantics_dist,
            },
        }
