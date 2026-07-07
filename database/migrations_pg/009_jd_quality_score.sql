-- ============================================================
-- Migration 009 (PG): jds.quality_score 列 + 索引
-- 与 SQLite 版本对应；用 ADD COLUMN IF NOT EXISTS 保持幂等
-- ============================================================

ALTER TABLE jds
    ADD COLUMN IF NOT EXISTS quality_score REAL;

ALTER TABLE jds
    ADD COLUMN IF NOT EXISTS quality_checked_at TEXT;

CREATE INDEX IF NOT EXISTS idx_jds_quality_score
    ON jds(quality_score);

UPDATE schema_version
   SET version = 9,
       description = 'JD quality_score composite cache (services.jd_quality_service)'
 WHERE id = 1;
