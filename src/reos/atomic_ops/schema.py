"""Database schema for atomic operations.

This module defines the v2 schema for atomic operations.
Operations are stored as blocks (type='atomic_operation') with additional
data in specialized tables.

Schema v2 changes (LLM-native classification):
- atomic_operations: confident INTEGER replaces confidence REAL, adds reasoning/model
- classification_log: confident INTEGER, reasoning TEXT (no alternatives)
- ml_features table REMOVED
- training_data view REMOVED
- user_feedback: simplified to approval/correction/rejection
- classification_clarifications: new table for ambiguous requests
- classification_history: new view joining operations with corrections
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime
from typing import Any, Optional

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

logger = logging.getLogger(__name__)

# Schema version for atomic operations tables
ATOMIC_OPS_SCHEMA_VERSION = 2

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
    classification_confident INTEGER NOT NULL DEFAULT 0,
    classification_reasoning TEXT,
    classification_model TEXT,

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
                      'awaiting_clarification', 'executing', 'complete', 'failed', 'decomposed'))
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
    confident INTEGER NOT NULL DEFAULT 0,

    -- Reasoning
    reasoning TEXT,

    -- Model used
    model TEXT,

    -- Timestamps
    created_at TEXT NOT NULL,

    FOREIGN KEY (operation_id) REFERENCES atomic_operations(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_classification_log_op ON classification_log(operation_id);

-- User feedback collection (simplified: approval/correction/rejection)
CREATE TABLE IF NOT EXISTS user_feedback (
    id TEXT PRIMARY KEY,
    operation_id TEXT NOT NULL,
    user_id TEXT NOT NULL,

    -- Feedback type
    feedback_type TEXT NOT NULL,

    -- Correction fields
    system_classification TEXT,  -- JSON of system's classification
    user_corrected_destination TEXT,
    user_corrected_consumer TEXT,
    user_corrected_semantics TEXT,
    correction_reasoning TEXT,

    -- Approval fields
    approved INTEGER,
    time_to_decision_ms INTEGER,

    -- Timestamps
    created_at TEXT NOT NULL,

    FOREIGN KEY (operation_id) REFERENCES atomic_operations(id) ON DELETE CASCADE,
    CHECK (feedback_type IN ('approval', 'correction', 'rejection'))
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

-- Classification clarifications (for ambiguous requests)
CREATE TABLE IF NOT EXISTS classification_clarifications (
    id TEXT PRIMARY KEY,
    operation_id TEXT NOT NULL,
    question TEXT NOT NULL,
    user_response TEXT,
    resolved INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,

    FOREIGN KEY (operation_id) REFERENCES atomic_operations(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_clarification_operation ON classification_clarifications(operation_id);

-- Schema version tracking for atomic ops
CREATE TABLE IF NOT EXISTS atomic_ops_schema_version (
    version INTEGER PRIMARY KEY
);

-- Classification history view (joins operations with corrections for few-shot learning)
CREATE VIEW IF NOT EXISTS classification_history AS
SELECT
    ao.id AS operation_id,
    ao.user_request,
    ao.destination_type AS system_destination,
    ao.consumer_type AS system_consumer,
    ao.execution_semantics AS system_semantics,
    ao.classification_confident,
    ao.source_agent,

    uf.feedback_type,
    uf.approved,
    uf.user_corrected_destination,
    uf.user_corrected_consumer,
    uf.user_corrected_semantics,
    uf.correction_reasoning,

    ao.created_at,
    uf.created_at AS feedback_at

FROM atomic_operations ao
LEFT JOIN user_feedback uf ON ao.id = uf.operation_id
WHERE uf.feedback_type IN ('correction', 'approval')
  AND (uf.approved = 1 OR uf.user_corrected_destination IS NOT NULL);
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
    system, including CRUD operations and feedback collection.

    Important: This class does NOT manage transactions. The caller must
    wrap operations in a transaction context (e.g., db.transaction()) and
    commit/rollback as appropriate.
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
                classification_confident, classification_reasoning, classification_model,
                is_decomposed, parent_id, child_ids,
                status, source_agent, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            op.id,
            op.block_id,
            op.user_request,
            op.user_id,
            op.classification.destination.value if op.classification else None,
            op.classification.consumer.value if op.classification else None,
            op.classification.semantics.value if op.classification else None,
            1 if (op.classification and op.classification.confident) else 0,
            op.classification.reasoning if op.classification else None,
            None,  # model stored in classification_log
            1 if op.is_decomposed else 0,
            op.parent_id,
            json.dumps(op.child_ids) if op.child_ids else None,
            op.status.value,
            op.source_agent,
            now,
        ))
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

    def update_operation_classification(
        self,
        operation_id: str,
        classification: Classification,
        model: str = "",
    ) -> None:
        """Update operation classification."""
        self.conn.execute("""
            UPDATE atomic_operations
            SET destination_type = ?, consumer_type = ?, execution_semantics = ?,
                classification_confident = ?, classification_reasoning = ?,
                classification_model = ?
            WHERE id = ?
        """, (
            classification.destination.value,
            classification.consumer.value,
            classification.semantics.value,
            1 if classification.confident else 0,
            classification.reasoning,
            model,
            operation_id,
        ))

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
                confident=bool(row["classification_confident"]),
                reasoning=row["classification_reasoning"] or "",
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
        model: str = "",
    ) -> str:
        """Log classification reasoning."""
        from uuid import uuid4
        log_id = str(uuid4())
        now = datetime.now().isoformat()

        self.conn.execute("""
            INSERT INTO classification_log (
                id, operation_id, destination_type, consumer_type, execution_semantics,
                confident, reasoning, model, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            log_id,
            operation_id,
            classification.destination.value,
            classification.consumer.value,
            classification.semantics.value,
            1 if classification.confident else 0,
            classification.reasoning,
            model,
            now,
        ))
        return log_id

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
                system_classification, user_corrected_destination,
                user_corrected_consumer, user_corrected_semantics,
                correction_reasoning,
                approved, time_to_decision_ms,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            feedback.id,
            feedback.operation_id,
            feedback.user_id,
            feedback.feedback_type.value,
            json.dumps(feedback.system_classification) if feedback.system_classification else None,
            feedback.user_corrected_destination,
            feedback.user_corrected_consumer,
            feedback.user_corrected_semantics,
            feedback.correction_reasoning,
            1 if feedback.approved else (0 if feedback.approved is False else None),
            feedback.time_to_decision_ms,
            now,
        ))
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
            system_classification=json.loads(row["system_classification"]) if row["system_classification"] else None,
            user_corrected_destination=row["user_corrected_destination"],
            user_corrected_consumer=row["user_corrected_consumer"],
            user_corrected_semantics=row["user_corrected_semantics"],
            correction_reasoning=row["correction_reasoning"],
            approved=bool(row["approved"]) if row["approved"] is not None else None,
            time_to_decision_ms=row["time_to_decision_ms"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    # =========================================================================
    # CLARIFICATIONS
    # =========================================================================

    def store_clarification(
        self,
        operation_id: str,
        question: str,
    ) -> str:
        """Store a clarification question for an ambiguous request."""
        from uuid import uuid4
        clar_id = str(uuid4())
        now = datetime.now().isoformat()

        self.conn.execute("""
            INSERT INTO classification_clarifications (
                id, operation_id, question, resolved, created_at
            ) VALUES (?, ?, ?, 0, ?)
        """, (clar_id, operation_id, question, now))
        return clar_id

    # =========================================================================
    # CORRECTIONS FOR FEW-SHOT LEARNING
    # =========================================================================

    def get_recent_corrections(
        self,
        user_id: str | None = None,
        limit: int = 10,
    ) -> list[dict]:
        """Get recent corrections for few-shot classifier context.

        Returns dicts with request, system classification, and user correction.
        """
        query = """
            SELECT
                ao.user_request AS request,
                ao.destination_type AS system_destination,
                ao.consumer_type AS system_consumer,
                ao.execution_semantics AS system_semantics,
                uf.user_corrected_destination AS corrected_destination,
                uf.user_corrected_consumer AS corrected_consumer,
                uf.user_corrected_semantics AS corrected_semantics
            FROM user_feedback uf
            JOIN atomic_operations ao ON uf.operation_id = ao.id
            WHERE uf.feedback_type = 'correction'
              AND uf.user_corrected_destination IS NOT NULL
        """
        params: list[Any] = []

        if user_id:
            query += " AND uf.user_id = ?"
            params.append(user_id)

        query += " ORDER BY uf.created_at DESC LIMIT ?"
        params.append(limit)

        cursor = self.conn.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]

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

    def get_classification_stats(self, user_id: str) -> dict:
        """Get classification statistics for a user."""
        cursor = self.conn.execute(
            "SELECT COUNT(*) FROM atomic_operations WHERE user_id = ?",
            (user_id,)
        )
        total_ops = cursor.fetchone()[0]

        cursor = self.conn.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN uf.approved = 1 THEN 1 ELSE 0 END) as approved,
                SUM(CASE WHEN uf.user_corrected_destination IS NOT NULL THEN 1 ELSE 0 END) as corrected
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

        return {
            "total_operations": total_ops,
            "feedback_count": feedback_total,
            "accuracy": accuracy,
            "correction_rate": correction_rate,
        }
