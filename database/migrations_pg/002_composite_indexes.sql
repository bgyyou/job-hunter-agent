-- ============================================================
-- Migration 002 (PG): 列表/分页热路径复合索引
-- 与 SQLite 版本对应：partial index WHERE deleted_at IS NULL
-- PG 支持 partial index 语法，与 SQLite 完全兼容
-- ============================================================

CREATE INDEX IF NOT EXISTS idx_match_user_created
    ON match_history(user_id, created_at DESC)
    WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_opt_user_created
    ON optimizations(user_id, created_at DESC)
    WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_jds_user_crawled
    ON jds(user_id, crawled_at DESC)
    WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_chunk_jd_index
    ON knowledge_chunks(jd_id, chunk_index)
    WHERE deleted_at IS NULL;

UPDATE schema_version SET version = 2, description = 'Composite indexes for list/paging hot paths' WHERE id = 1;