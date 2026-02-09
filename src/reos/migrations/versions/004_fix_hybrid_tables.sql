-- Migration 004: Fix hybrid V1/V2 tables
--
-- Migration 003 failed to properly transform existing V1 tables to V2 schema.
-- This migration drops the broken hybrid tables and lets init_atomic_ops_schema()
-- recreate them cleanly with the V2 schema on next access.
--
-- Data in these tables is operational logs (classification attempts, feedback)
-- not user data — safe to rebuild.
--
-- On fresh databases these tables may not exist yet — DROP IF EXISTS handles that.

-- Drop views that reference tables we're about to drop
DROP VIEW IF EXISTS classification_history;

-- Drop the broken hybrid tables
DROP TABLE IF EXISTS classification_log;
DROP TABLE IF EXISTS user_feedback;

-- atomic_operations must be dropped last (others have FK references to it)
-- First drop tables that reference it
DROP TABLE IF EXISTS operation_verification;
DROP TABLE IF EXISTS operation_execution;
DROP TABLE IF EXISTS classification_clarifications;
DROP TABLE IF EXISTS atomic_operations;

-- Clean up other remnants from V1
DROP TABLE IF EXISTS learning_metrics;
DROP TABLE IF EXISTS ml_features;
DROP VIEW IF EXISTS training_data;

-- Reset the atomic_ops schema version so init_atomic_ops_schema() will
-- recreate everything fresh with the V2 schema
DROP TABLE IF EXISTS atomic_ops_schema_version;

SELECT 1;
