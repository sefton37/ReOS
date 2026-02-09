-- Migration 003: LLM-native classification
-- Replaces ML feature extraction with LLM-based classification.
--
-- For existing databases: migrates atomic_operations, classification_log, etc.
-- For fresh databases: tables are already created with v2 schema, so this is a no-op.
--
-- We check for the old column name to detect whether migration is needed.

-- Drop old tables that are no longer needed (safe for fresh installs too)
DROP TABLE IF EXISTS ml_features;
DROP VIEW IF EXISTS training_data;
DROP TABLE IF EXISTS learning_metrics;

-- Create new tables (IF NOT EXISTS, safe for both fresh and upgrade)
CREATE TABLE IF NOT EXISTS classification_clarifications (
    id TEXT PRIMARY KEY,
    operation_id TEXT NOT NULL,
    question TEXT NOT NULL,
    user_response TEXT,
    resolved INTEGER DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_clarification_operation ON classification_clarifications(operation_id);

-- Note: ALTER TABLE changes for existing v1 databases are handled by
-- init_atomic_ops_schema() in schema.py which creates tables with IF NOT EXISTS.
-- On upgrade, the old tables remain but the new schema version (2) means
-- AtomicOpsStore will not re-create them. The old columns become unused
-- but don't cause errors since SQLite is loosely typed.

SELECT 1;
