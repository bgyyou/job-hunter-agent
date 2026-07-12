-- ============================================================
-- Migration 012 (SQLite): v3 resumes.achievements 顶层字段
-- 实际 ALTER 由 sqlite_backend.py:_apply_idempotent_migrations PRAGMA 检查内联完成
-- （同 knowledge_chunks.legacy / resumes.parent_resume_id 处理模式）
-- 此文件仅作 schema_version 里程碑标记
-- ============================================================

UPDATE schema_version
SET version = 12,
    description = 'Add resumes.achievements 顶层字段 (v3 M-rebuild-1)',
    applied_at = datetime('now')
WHERE id = 1;