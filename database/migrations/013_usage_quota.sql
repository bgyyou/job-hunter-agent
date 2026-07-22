-- ============================================================
-- Migration 013 (SQLite): llm_calls.user_id 配额统计维度（v4 T1.4）
-- 实际 ALTER 由 sqlite_backend.py:_apply_idempotent_migrations PRAGMA 检查内联完成
-- （同 knowledge_chunks.legacy / resumes.achievements 处理模式，
--  因 SQLite ALTER TABLE ADD COLUMN 不支持 IF NOT EXISTS，编号迁移每次启动都会重放）
-- 此文件仅作 schema_version 里程碑标记
-- ============================================================

UPDATE schema_version
SET version = 13,
    description = 'Add llm_calls.user_id + (user_id, created_at) 索引 (v4 T1.4 配额)',
    applied_at = datetime('now')
WHERE id = 1;
