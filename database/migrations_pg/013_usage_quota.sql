-- ============================================================
-- Migration 013 (PostgreSQL): llm_calls.user_id 配额统计维度（v4 T1.4）
-- PG 支持 ADD COLUMN IF NOT EXISTS，编号迁移每次启动重放安全
-- ============================================================

ALTER TABLE llm_calls
    ADD COLUMN IF NOT EXISTS user_id TEXT NOT NULL DEFAULT 'default';

CREATE INDEX IF NOT EXISTS idx_llm_calls_user_created_at
    ON llm_calls(user_id, created_at);

UPDATE schema_version
SET version = 13,
    description = 'Add llm_calls.user_id + (user_id, created_at) 索引 (v4 T1.4 配额)',
    applied_at = NOW()
WHERE id = 1;
