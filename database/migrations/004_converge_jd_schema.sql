-- ============================================================
-- Migration 004 (SQLite): JD schema convergence
-- 5 fields → 2 fields: parsed_sections + tags
--
-- 删除：requirements, preferred_requirements, skills_required,
--       implicit_requirements, parsed_data
-- 新增：parsed_sections (JSON dict), tags (JSON list)
--
-- 注：本脚本由 sqlite_backend._apply_idempotent_migrations() 在检测到
--     `jds` 表还有 `requirements` 列时整体执行（事务内）。
--     已经迁移过的库直接 SKIP。
-- ============================================================

CREATE TABLE jds_v3 (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL DEFAULT 'default',
    url TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    company TEXT NOT NULL DEFAULT '',
    location TEXT NOT NULL DEFAULT '',
    salary_str TEXT,
    salary_min INTEGER,
    salary_max INTEGER,
    parsed_sections TEXT NOT NULL DEFAULT '{}',
    tags TEXT NOT NULL DEFAULT '[]',
    raw_text TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'manual',
    search_keyword TEXT,
    platform TEXT,
    job_id TEXT,
    language TEXT DEFAULT 'zh',
    industry_tag TEXT,
    function_tag TEXT,
    position_tag TEXT,
    auto_classified INTEGER NOT NULL DEFAULT 1,
    is_public INTEGER NOT NULL DEFAULT 0 CHECK (is_public IN (0, 1)),
    crawled_at TEXT NOT NULL DEFAULT (datetime('now')),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    deleted_at TEXT,
    UNIQUE(url, user_id)
);

INSERT INTO jds_v3 (
    id, user_id, url, title, company, location,
    salary_str, salary_min, salary_max,
    parsed_sections, tags, raw_text,
    source, search_keyword, platform, job_id, language,
    industry_tag, function_tag, position_tag,
    auto_classified, is_public, crawled_at, created_at, updated_at, deleted_at
)
SELECT
    id, user_id, url, title, company, location,
    salary_str, salary_min, salary_max,
    json_object(
        'requirements', COALESCE(json(requirements), json('[]')),
        'preferred', COALESCE(json(preferred_requirements), json('[]')),
        'skills', COALESCE(json(skills_required), json('[]')),
        'implicit', COALESCE(implicit_requirements, '')
    ),
    COALESCE(skills_required, '[]'),
    raw_text,
    source, search_keyword, platform, job_id, language,
    industry_tag, function_tag, position_tag,
    auto_classified, is_public, crawled_at, created_at, updated_at, deleted_at
FROM jds;

DROP TABLE jds;
ALTER TABLE jds_v3 RENAME TO jds;

-- 重建所有索引（schema.sql 的 CREATE INDEX IF NOT EXISTS 会在下次启动补上其它的）
CREATE INDEX IF NOT EXISTS idx_jds_user_id ON jds(user_id);
CREATE INDEX IF NOT EXISTS idx_jds_url ON jds(url);
CREATE INDEX IF NOT EXISTS idx_jds_source ON jds(source);
CREATE INDEX IF NOT EXISTS idx_jds_platform ON jds(platform);
CREATE INDEX IF NOT EXISTS idx_jds_industry ON jds(industry_tag);
CREATE INDEX IF NOT EXISTS idx_jds_function ON jds(function_tag);
CREATE INDEX IF NOT EXISTS idx_jds_position ON jds(position_tag);
CREATE INDEX IF NOT EXISTS idx_jds_company ON jds(company);
CREATE INDEX IF NOT EXISTS idx_jds_crawled_at ON jds(crawled_at);
CREATE INDEX IF NOT EXISTS idx_jds_is_public ON jds(is_public);
CREATE INDEX IF NOT EXISTS idx_jds_deleted ON jds(deleted_at);
CREATE INDEX IF NOT EXISTS idx_jds_user_crawled
    ON jds(user_id, crawled_at DESC)
    WHERE deleted_at IS NULL;

UPDATE schema_version SET version = 4, description = 'JD schema converged to parsed_sections + tags', applied_at = datetime('now') WHERE id = 1;