-- ============================================================
-- Migration 010 (SQLite): Flow A recoverable draft state
-- ============================================================

CREATE TABLE IF NOT EXISTS flow_a_drafts (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL DEFAULT 'default',
    status TEXT NOT NULL DEFAULT 'draft',
    industry TEXT,
    function TEXT,
    position TEXT,
    current_step TEXT NOT NULL DEFAULT 'target',
    current_section TEXT,
    section_data TEXT NOT NULL DEFAULT '{}',
    section_messages TEXT NOT NULL DEFAULT '{}',
    section_status TEXT NOT NULL DEFAULT '{}',
    generation_state TEXT NOT NULL DEFAULT '{}',
    last_error TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    completed_at TEXT,
    deleted_at TEXT,
    CHECK (status IN ('draft', 'generating', 'completed', 'failed', 'abandoned'))
);

CREATE INDEX IF NOT EXISTS idx_flow_a_drafts_user_status_updated
    ON flow_a_drafts(user_id, status, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_flow_a_drafts_deleted
    ON flow_a_drafts(deleted_at);

UPDATE schema_version
SET version = 10,
    description = 'Add Flow A recoverable draft state',
    applied_at = datetime('now')
WHERE id = 1;
