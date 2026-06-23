-- ============================================================
-- Migration 002: 列表/分页热路径复合索引
-- 目的：消除"过滤 + 排序"双重扫描，把 (user_id, X DESC) 直接索引化
-- ============================================================

-- match_history: 用户首页常按 created_at DESC 列出该用户的匹配记录
CREATE INDEX IF NOT EXISTS idx_match_user_created
    ON match_history(user_id, created_at DESC)
    WHERE deleted_at IS NULL;

-- optimizations: 简历优化建议列表也按 created_at DESC
CREATE INDEX IF NOT EXISTS idx_opt_user_created
    ON optimizations(user_id, created_at DESC)
    WHERE deleted_at IS NULL;

-- jds: 列表最常 ORDER BY crawled_at DESC LIMIT，按 user_id 分租
CREATE INDEX IF NOT EXISTS idx_jds_user_crawled
    ON jds(user_id, crawled_at DESC)
    WHERE deleted_at IS NULL;

-- knowledge_chunks: 按 jd_id 取所有 chunk 时，索引顺序保证 chunk_index 有序返回
CREATE INDEX IF NOT EXISTS idx_chunk_jd_index
    ON knowledge_chunks(jd_id, chunk_index)
    WHERE deleted_at IS NULL;

-- 更新 schema_version
UPDATE schema_version SET version = 2, description = 'Composite indexes for list/paging hot paths', applied_at = datetime('now') WHERE id = 1;
