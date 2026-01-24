-- Archive Memory System tables for conversation archival with quality tracking

-- Archive metadata: Links archives to conversations with LLM-extracted context
CREATE TABLE IF NOT EXISTS archive_metadata (
    archive_id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    act_id TEXT,
    linking_reason TEXT,
    topics TEXT,  -- JSON array of topic strings
    sentiment TEXT,  -- positive, neutral, negative, mixed
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_archive_metadata_conversation
    ON archive_metadata(conversation_id);
CREATE INDEX IF NOT EXISTS idx_archive_metadata_act
    ON archive_metadata(act_id);

-- Archive quality assessments: LLM-generated quality scores
CREATE TABLE IF NOT EXISTS archive_assessments (
    id TEXT PRIMARY KEY,
    archive_id TEXT NOT NULL,
    title_quality INTEGER NOT NULL,  -- 1-5
    summary_quality INTEGER NOT NULL,  -- 1-5
    act_linking INTEGER NOT NULL,  -- 1-5
    knowledge_relevance INTEGER NOT NULL,  -- 1-5
    knowledge_coverage INTEGER NOT NULL,  -- 1-5
    deduplication INTEGER NOT NULL,  -- 1-5
    overall_score INTEGER NOT NULL,  -- 1-5
    suggestions TEXT,  -- JSON array of suggestions
    assessed_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_archive_assessments_archive
    ON archive_assessments(archive_id);

-- User feedback on archives: For learning and improving archival quality
CREATE TABLE IF NOT EXISTS archive_feedback (
    id TEXT PRIMARY KEY,
    archive_id TEXT NOT NULL,
    rating INTEGER NOT NULL,  -- 1-5 stars
    feedback TEXT,  -- Optional text feedback
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_archive_feedback_archive
    ON archive_feedback(archive_id);
CREATE INDEX IF NOT EXISTS idx_archive_feedback_rating
    ON archive_feedback(rating);
