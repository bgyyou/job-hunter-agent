-- ============================================================
-- Migration 004 (PG): JD schema convergence
-- 5 fields → 2 fields: parsed_sections + tags
--
-- 删除：requirements, preferred_requirements, skills_required,
--       implicit_requirements, parsed_data
-- 新增：parsed_sections (JSONB dict), tags (JSONB list)
--
-- PG 支持 ALTER TABLE DROP COLUMN，单事务安全切换。
-- 幂等：通过 IF NOT EXISTS / DO 块判断列存在性
-- ============================================================

-- 新增列（已存在则跳过）
ALTER TABLE jds ADD COLUMN IF NOT EXISTS parsed_sections JSONB NOT NULL DEFAULT '{}';
ALTER TABLE jds ADD COLUMN IF NOT EXISTS tags JSONB NOT NULL DEFAULT '[]';

-- 数据迁移：仅当旧字段还存在时
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'jds' AND column_name = 'requirements'
    ) THEN
        UPDATE jds SET parsed_sections = jsonb_build_object(
            'requirements', COALESCE(requirements::jsonb, '[]'::jsonb),
            'preferred', COALESCE(preferred_requirements::jsonb, '[]'::jsonb),
            'skills', COALESCE(skills_required::jsonb, '[]'::jsonb),
            'implicit', COALESCE(to_jsonb(implicit_requirements), '""'::jsonb)
        )
        WHERE parsed_sections = '{}'::jsonb;

        UPDATE jds SET tags = COALESCE(skills_required::jsonb, '[]'::jsonb)
        WHERE tags = '[]'::jsonb;

        -- 删除旧字段
        ALTER TABLE jds DROP COLUMN IF EXISTS requirements;
        ALTER TABLE jds DROP COLUMN IF EXISTS preferred_requirements;
        ALTER TABLE jds DROP COLUMN IF EXISTS skills_required;
        ALTER TABLE jds DROP COLUMN IF EXISTS implicit_requirements;
        ALTER TABLE jds DROP COLUMN IF EXISTS parsed_data;
    END IF;
END $$;

-- GIN 索引：跟 schema_pg.sql 保持一致
CREATE INDEX IF NOT EXISTS idx_jds_tags ON jds USING gin (tags jsonb_path_ops);
CREATE INDEX IF NOT EXISTS idx_jds_parsed_sections ON jds USING gin (parsed_sections jsonb_path_ops);

UPDATE schema_version SET version = 4, description = 'JD schema converged to parsed_sections + tags' WHERE id = 1;