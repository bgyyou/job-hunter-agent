-- ============================================================
-- Migration 011 (PostgreSQL): v3 resume rewrite infrastructure
-- ============================================================

-- JD 结构化存储（覆盖 text/image/rag 三种来源）
CREATE TABLE IF NOT EXISTS jd_structured (
    jd_id BIGSERIAL PRIMARY KEY,
    user_id TEXT NOT NULL DEFAULT 'default',
    source TEXT NOT NULL CHECK (source IN ('text', 'image', 'rag')),
    raw_text TEXT,
    company TEXT,
    title TEXT,
    industry TEXT,
    function TEXT,
    level TEXT,
    responsibilities JSONB NOT NULL DEFAULT '[]'::jsonb,
    requirements JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_jd_structured_user_source
    ON jd_structured(user_id, source, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_jd_structured_industry_function
    ON jd_structured(industry, function, level);
CREATE INDEX IF NOT EXISTS idx_jd_structured_deleted
    ON jd_structured(deleted_at);

-- 改写记录
CREATE TABLE IF NOT EXISTS rewrite_history (
    rewrite_id BIGSERIAL PRIMARY KEY,
    user_id TEXT NOT NULL DEFAULT 'default',
    resume_id TEXT NOT NULL,
    jd_id BIGINT,
    mode TEXT NOT NULL CHECK (mode IN ('A', 'B', 'A+B')),
    input_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    output_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    rewrite_notes JSONB NOT NULL DEFAULT '{}'::jsonb,
    user_edited INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    FOREIGN KEY (jd_id) REFERENCES jd_structured(jd_id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_rewrite_history_resume_created
    ON rewrite_history(resume_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_rewrite_history_jd
    ON rewrite_history(jd_id);
CREATE INDEX IF NOT EXISTS idx_rewrite_history_user_edited
    ON rewrite_history(user_id, user_edited);

-- RAG 库：行业×职能×级别分类树
CREATE TABLE IF NOT EXISTS rag_industry_function (
    id BIGSERIAL PRIMARY KEY,
    industry TEXT NOT NULL,
    function TEXT NOT NULL,
    level TEXT,
    sample_jds JSONB NOT NULL DEFAULT '[]'::jsonb,
    sample_resumes JSONB NOT NULL DEFAULT '[]'::jsonb,
    scoring_rubric JSONB,
    source TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(industry, function, level)
);

CREATE INDEX IF NOT EXISTS idx_rag_industry_function_lookup
    ON rag_industry_function(industry, function, level);

-- 面试真题
CREATE TABLE IF NOT EXISTS interview_questions (
    question_id BIGSERIAL PRIMARY KEY,
    industry TEXT NOT NULL,
    function TEXT NOT NULL,
    level TEXT,
    type TEXT,
    question TEXT NOT NULL,
    options JSONB,
    answer TEXT,
    analysis TEXT,
    key_points JSONB,
    source TEXT,
    reviewed_by TEXT,
    reviewed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_interview_questions_lookup
    ON interview_questions(industry, function, level);

UPDATE schema_version
SET version = 11,
    description = 'v3 resume rewrite infrastructure (jd_structured, rewrite_history, rag_industry_function, interview_questions)',
    applied_at = NOW()
WHERE id = 1;