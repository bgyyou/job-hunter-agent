-- ============================================================
-- Migration 010 (PostgreSQL): Flow A recoverable draft state
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
    section_data JSONB NOT NULL DEFAULT '{}'::jsonb,
    section_messages JSONB NOT NULL DEFAULT '{}'::jsonb,
    section_status JSONB NOT NULL DEFAULT '{}'::jsonb,
    generation_state JSONB NOT NULL DEFAULT '{}'::jsonb,
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    deleted_at TIMESTAMPTZ,
    CHECK (status IN ('draft', 'generating', 'completed', 'failed', 'abandoned'))
);

CREATE INDEX IF NOT EXISTS idx_flow_a_drafts_user_status_updated
    ON flow_a_drafts(user_id, status, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_flow_a_drafts_deleted
    ON flow_a_drafts(deleted_at);

UPDATE schema_version
SET version = 10,
    description = 'Add Flow A recoverable draft state',
    applied_at = NOW()
WHERE id = 1;
