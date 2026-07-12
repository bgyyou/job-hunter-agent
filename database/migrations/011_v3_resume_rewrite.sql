-- ============================================================
-- Migration 011 (SQLite): v3 resume rewrite infrastructure
-- 引入 4 张表：jd_structured / rewrite_history / rag_industry_function / interview_questions
-- ============================================================

-- JD 结构化存储（覆盖 text/image/rag 三种来源）
CREATE TABLE IF NOT EXISTS jd_structured (
    jd_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL DEFAULT 'default',
    source TEXT NOT NULL CHECK (source IN ('text', 'image', 'rag')),
    raw_text TEXT,
    company TEXT,
    title TEXT,
    industry TEXT,
    function TEXT,
    level TEXT,
    responsibilities TEXT NOT NULL DEFAULT '[]',  -- JSON 列表
    requirements TEXT NOT NULL DEFAULT '[]',      -- JSON 列表
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    deleted_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_jd_structured_user_source
    ON jd_structured(user_id, source, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_jd_structured_industry_function
    ON jd_structured(industry, function, level);
CREATE INDEX IF NOT EXISTS idx_jd_structured_deleted
    ON jd_structured(deleted_at);

-- 改写记录（每次改写都留痕，支持版本对比 + 用户编辑追溯）
CREATE TABLE IF NOT EXISTS rewrite_history (
    rewrite_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL DEFAULT 'default',
    resume_id TEXT NOT NULL,
    jd_id INTEGER,
    mode TEXT NOT NULL CHECK (mode IN ('A', 'B', 'A+B')),
    input_snapshot TEXT NOT NULL DEFAULT '{}',    -- JSON，改写前的简历快照
    output_snapshot TEXT NOT NULL DEFAULT '{}',   -- JSON，改写后的内容
    rewrite_notes TEXT NOT NULL DEFAULT '{}',     -- JSON，每段改写说明
    user_edited INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (jd_id) REFERENCES jd_structured(jd_id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_rewrite_history_resume_created
    ON rewrite_history(resume_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_rewrite_history_jd
    ON rewrite_history(jd_id);
CREATE INDEX IF NOT EXISTS idx_rewrite_history_user_edited
    ON rewrite_history(user_id, user_edited);

-- RAG 库：行业×职能×级别分类树（数据待渠道明确后回填）
CREATE TABLE IF NOT EXISTS rag_industry_function (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    industry TEXT NOT NULL,
    function TEXT NOT NULL,
    level TEXT,                              -- 'junior' / 'mid' / 'senior'
    sample_jds TEXT NOT NULL DEFAULT '[]',   -- JSON，该组合下的真实 JD 样本
    sample_resumes TEXT NOT NULL DEFAULT '[]',  -- JSON，该组合下的优质简历样本
    scoring_rubric TEXT,                     -- JSON，评分维度（人工标）
    source TEXT,                             -- 'scraped' / 'user_contributed' / 'ai_generated'
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(industry, function, level)
);

CREATE INDEX IF NOT EXISTS idx_rag_industry_function_lookup
    ON rag_industry_function(industry, function, level);

-- 面试真题（M-rebuild-4 暂不做，schema 先留）
CREATE TABLE IF NOT EXISTS interview_questions (
    question_id INTEGER PRIMARY KEY AUTOINCREMENT,
    industry TEXT NOT NULL,
    function TEXT NOT NULL,
    level TEXT,
    type TEXT,                               -- 'single_choice' / 'multiple_choice' / 'true_false'
    question TEXT NOT NULL,
    options TEXT,                            -- JSON
    answer TEXT,
    analysis TEXT,
    key_points TEXT,                         -- JSON
    source TEXT,                             -- 'ai_generated' / 'user_contributed' / 'scraped'
    reviewed_by TEXT,                        -- 人工审核者（AI 生成的题必须经人审）
    reviewed_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_interview_questions_lookup
    ON interview_questions(industry, function, level);

UPDATE schema_version
SET version = 11,
    description = 'v3 resume rewrite infrastructure (jd_structured, rewrite_history, rag_industry_function, interview_questions)',
    applied_at = datetime('now')
WHERE id = 1;