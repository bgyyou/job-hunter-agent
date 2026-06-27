-- ============================================================
-- Job Hunter v2 Unified Database Schema
-- Database file: data/jobhunter_v2.db
-- Supports: multi-tenancy (user_id), public/private JDs, RAG
-- ============================================================

PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

-- ============================================================
-- Table: schema_version
-- Singleton row tracking migration state
-- ============================================================
CREATE TABLE IF NOT EXISTS schema_version (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    version INTEGER NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    applied_at TEXT NOT NULL DEFAULT (datetime('now'))
);

INSERT OR IGNORE INTO schema_version (id, version, description)
VALUES (1, 1, 'Initial schema - unified job hunter database');

-- ============================================================
-- Table: users
-- Product auth identities. First provider is local email/phone;
-- provider/provider_subject leave room for WeChat/SMS/email adapters.
-- ============================================================
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    email TEXT UNIQUE,
    phone TEXT UNIQUE,
    name TEXT NOT NULL DEFAULT '',
    password_hash TEXT NOT NULL,
    password_salt TEXT NOT NULL,
    provider TEXT NOT NULL DEFAULT 'local',
    provider_subject TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    deleted_at TEXT,
    CHECK (email IS NOT NULL OR phone IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE INDEX IF NOT EXISTS idx_users_phone ON users(phone);
CREATE INDEX IF NOT EXISTS idx_users_provider_subject ON users(provider, provider_subject);
CREATE INDEX IF NOT EXISTS idx_users_deleted ON users(deleted_at);

-- ============================================================
-- Table: resumes
-- Persistent resume profiles. One user may have multiple versions.
-- ============================================================
CREATE TABLE IF NOT EXISTS resumes (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL DEFAULT 'default',
    name TEXT NOT NULL,
    phone TEXT,
    email TEXT,
    summary TEXT,
    skills TEXT NOT NULL DEFAULT '[]',
    experience_years INTEGER DEFAULT 0,
    domains TEXT DEFAULT '[]',
    target_roles TEXT DEFAULT '[]',
    preferred_locations TEXT DEFAULT '[]',
    education TEXT NOT NULL DEFAULT '[]',
    projects TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    deleted_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_resumes_user_id ON resumes(user_id);
CREATE INDEX IF NOT EXISTS idx_resumes_deleted ON resumes(deleted_at);

-- ============================================================
-- Table: jds
-- Unified job description storage from ALL sources.
-- Deduplication by (url, user_id).
-- ============================================================
CREATE TABLE IF NOT EXISTS jds (
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

-- ============================================================
-- Table: match_history
-- Every resume-to-JD match record.
-- ============================================================
CREATE TABLE IF NOT EXISTS match_history (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL DEFAULT 'default',
    resume_id TEXT NOT NULL,
    jd_id TEXT NOT NULL,
    score REAL NOT NULL,
    reasoning TEXT NOT NULL DEFAULT '',
    matched_skills TEXT DEFAULT '[]',
    missing_skills TEXT DEFAULT '[]',
    gaps TEXT NOT NULL DEFAULT '[]',
    recommendations TEXT NOT NULL DEFAULT '[]',
    skill_mapping TEXT DEFAULT '[]',
    should_apply INTEGER NOT NULL DEFAULT 0,
    user_feedback TEXT,
    applied INTEGER NOT NULL DEFAULT 0,
    applied_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    deleted_at TEXT,

    FOREIGN KEY (resume_id) REFERENCES resumes(id),
    FOREIGN KEY (jd_id) REFERENCES jds(id)
);

CREATE INDEX IF NOT EXISTS idx_match_user_id ON match_history(user_id);
CREATE INDEX IF NOT EXISTS idx_match_resume_id ON match_history(resume_id);
CREATE INDEX IF NOT EXISTS idx_match_jd_id ON match_history(jd_id);
CREATE INDEX IF NOT EXISTS idx_match_score ON match_history(score);
CREATE INDEX IF NOT EXISTS idx_match_applied ON match_history(applied);
CREATE INDEX IF NOT EXISTS idx_match_deleted ON match_history(deleted_at);

-- ============================================================
-- Table: optimizations
-- Resume optimization suggestions linked to JD chunks.
-- ============================================================
CREATE TABLE IF NOT EXISTS optimizations (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL DEFAULT 'default',
    resume_id TEXT,
    jd_id TEXT NOT NULL,
    chunk_id TEXT,
    optimization_type TEXT NOT NULL CHECK (optimization_type IN ('modify', 'delete', 'suggest_add')),
    section TEXT,
    original_content TEXT,
    suggested_content TEXT,
    reason TEXT NOT NULL,
    user_adopted INTEGER NOT NULL DEFAULT 0 CHECK (user_adopted IN (0, 1, 2)),
    user_rating INTEGER CHECK (user_rating BETWEEN 1 AND 5),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    deleted_at TEXT,

    FOREIGN KEY (resume_id) REFERENCES resumes(id),
    FOREIGN KEY (jd_id) REFERENCES jds(id),
    FOREIGN KEY (chunk_id) REFERENCES knowledge_chunks(id)
);

CREATE INDEX IF NOT EXISTS idx_opt_user_id ON optimizations(user_id);
CREATE INDEX IF NOT EXISTS idx_opt_jd_id ON optimizations(jd_id);
CREATE INDEX IF NOT EXISTS idx_opt_resume_id ON optimizations(resume_id);
CREATE INDEX IF NOT EXISTS idx_opt_chunk_id ON optimizations(chunk_id);
CREATE INDEX IF NOT EXISTS idx_opt_type ON optimizations(optimization_type);
CREATE INDEX IF NOT EXISTS idx_opt_adopted ON optimizations(user_adopted);
CREATE INDEX IF NOT EXISTS idx_opt_deleted ON optimizations(deleted_at);

-- ============================================================
-- Table: knowledge_chunks
-- JD text chunks for RAG retrieval.
-- ============================================================
CREATE TABLE IF NOT EXISTS knowledge_chunks (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL DEFAULT 'default',
    jd_id TEXT NOT NULL,
    chunk_index INTEGER NOT NULL CHECK (chunk_index >= 0),
    chunk_text TEXT NOT NULL,
    chunk_type TEXT NOT NULL DEFAULT 'full' CHECK (chunk_type IN ('overview', 'responsibility', 'requirement', 'nice_to_have', 'full')),
    keywords TEXT DEFAULT '[]',
    context TEXT NOT NULL DEFAULT '',
    heading_path TEXT NOT NULL DEFAULT '[]',
    embedding BLOB,
    embedding_dim INTEGER,
    legacy INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    deleted_at TEXT,

    FOREIGN KEY (jd_id) REFERENCES jds(id)
);

CREATE INDEX IF NOT EXISTS idx_chunk_user_id ON knowledge_chunks(user_id);
CREATE INDEX IF NOT EXISTS idx_chunk_jd_id ON knowledge_chunks(jd_id);
CREATE INDEX IF NOT EXISTS idx_chunk_type ON knowledge_chunks(chunk_type);

-- ============================================================
-- Table: quality_checks
-- Stores automated quality check results for data validation.
-- ============================================================
CREATE TABLE IF NOT EXISTS quality_checks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    check_type TEXT NOT NULL,
    target_table TEXT,
    target_id INTEGER,
    score REAL,
    details TEXT,
    checked_at TEXT NOT NULL DEFAULT (datetime('now')),
    user_id TEXT NOT NULL DEFAULT 'default'
);

CREATE INDEX IF NOT EXISTS idx_qc_check_type ON quality_checks(check_type);
CREATE INDEX IF NOT EXISTS idx_qc_target ON quality_checks(target_table, target_id);
CREATE INDEX IF NOT EXISTS idx_qc_user_id ON quality_checks(user_id);

-- ============================================================
-- Table: skeleton_cache
-- Caches RAG skeletons for Flow A to avoid rebuilding the same
-- (position, industry, function) skeleton on every resume generation.
-- ============================================================
CREATE TABLE IF NOT EXISTS skeleton_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    position TEXT NOT NULL,
    industry TEXT NOT NULL,
    function TEXT,
    skeleton_text TEXT NOT NULL,
    n_chunks INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL DEFAULT 'rag',
    industries_covered TEXT,  -- JSON list
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(position, industry, function)
);

CREATE INDEX IF NOT EXISTS idx_skeleton_cache_lookup
    ON skeleton_cache(position, industry, function);
CREATE INDEX IF NOT EXISTS idx_skeleton_cache_expires
    ON skeleton_cache(expires_at);
