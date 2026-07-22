-- ============================================================
-- Migration 006 (PG): skeleton cache for Flow A build_skeleton
-- 对齐 SQLite 版 006_skeleton_cache.sql；方言差异：
--   SQLite 自增主键 → SERIAL，industries_covered JSON → JSONB，
--   SQLite 的 datetime now 默认值 → NOW()，时间列用 TIMESTAMPTZ
-- 与 data/schema_pg.sql 中 skeleton_cache 定义保持一致（幂等）
-- ============================================================

CREATE TABLE IF NOT EXISTS skeleton_cache (
    id SERIAL PRIMARY KEY,
    position TEXT NOT NULL,
    industry TEXT NOT NULL,
    function TEXT,
    skeleton_text TEXT NOT NULL,
    n_chunks INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL DEFAULT 'rag',
    industries_covered JSONB,  -- JSON list
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(position, industry, function)
);

CREATE INDEX IF NOT EXISTS idx_skeleton_cache_lookup
    ON skeleton_cache(position, industry, function);
CREATE INDEX IF NOT EXISTS idx_skeleton_cache_expires
    ON skeleton_cache(expires_at);

UPDATE schema_version
SET version = 6,
    description = 'Add skeleton cache for Flow A build_skeleton',
    applied_at = NOW()
WHERE id = 1;
