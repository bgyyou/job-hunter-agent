-- ============================================================
-- Migration 012 (PostgreSQL): v3 resumes.achievements 顶层字段
-- ============================================================

ALTER TABLE resumes
    ADD COLUMN IF NOT EXISTS achievements JSONB NOT NULL DEFAULT '[]'::jsonb;

UPDATE schema_version
SET version = 12,
    description = 'Add resumes.achievements 顶层字段 (v3 M-rebuild-1)',
    applied_at = NOW()
WHERE id = 1;