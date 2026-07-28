-- ============================================================
-- Migration 016 (PostgreSQL): knowledge_chunks.retry_count 字段 — backfill 死循环兜底
-- 与 SQLite migration 016 同步：脚本需要 retry_count 字段支持
-- MAX_RETRIES_PER_RECORD 上限。PG 支持 ADD COLUMN IF NOT EXISTS 幂等。
-- ============================================================

ALTER TABLE knowledge_chunks
    ADD COLUMN IF NOT EXISTS retry_count INTEGER NOT NULL DEFAULT 0;

CREATE INDEX IF NOT EXISTS idx_chunk_retry_count
    ON knowledge_chunks(retry_count)
    WHERE translated_at IS NULL;

UPDATE schema_version
SET version = 16,
    description = 'Add knowledge_chunks.retry_count — backfill MAX_RETRIES_PER_RECORD 兜底 (M-v4-1 hotfix)',
    applied_at = NOW()
WHERE id = 1;
