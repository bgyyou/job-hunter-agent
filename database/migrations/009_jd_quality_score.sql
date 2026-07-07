-- ============================================================
-- Migration 009: JD 质量分索引
-- 实际 ALTER 由 _apply_idempotent_migrations inline 完成（PRAGMA 检查）
-- 此文件仅创建 INDEX 保持向后兼容记录
-- ============================================================

CREATE INDEX IF NOT EXISTS idx_jds_quality_score
    ON jds(quality_score);

UPDATE schema_version
   SET version = 9,
       description = 'JD quality_score composite cache (services.jd_quality_service)',
       applied_at = datetime('now')
 WHERE id = 1;
