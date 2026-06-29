-- ============================================================
-- Job Hunter v2 — PostgreSQL + pgvector Schema
-- Compatible with: PostgreSQL 14+, pgvector 0.8+
-- pgvector 0.8+ renamed operator classes:
--   vector_cos_ops  → vector_cosine_ops
--   vector_l2_ops   → vector_l2_ops (unchanged)
--   vector_ip_ops   → vector_ip_ops (unchanged)
-- ============================================================

-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ============================================================
-- Table: schema_version
-- Singleton row tracking migration state
-- ============================================================
CREATE TABLE IF NOT EXISTS schema_version (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    version INTEGER NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    applied_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

INSERT INTO schema_version (id, version, description)
VALUES (1, 1, 'Initial schema - unified job hunter database (PostgreSQL)')
ON CONFLICT (id) DO NOTHING;

-- ============================================================
-- Table: resumes
-- Persistent resume profiles. One user may have multiple versions.
-- ============================================================
CREATE TABLE IF NOT EXISTS resumes (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL DEFAULT 'default',
    name TEXT NOT NULL DEFAULT '',
    phone TEXT,
    email TEXT,
    summary TEXT,
    skills JSONB NOT NULL DEFAULT '[]',
    experience_years INTEGER DEFAULT 0,
    domains JSONB DEFAULT '[]',
    target_roles JSONB DEFAULT '[]',
    preferred_locations JSONB DEFAULT '[]',
    education JSONB NOT NULL DEFAULT '[]',
    projects JSONB NOT NULL DEFAULT '[]',
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMP WITH TIME ZONE
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
    url TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    company TEXT NOT NULL DEFAULT '',
    location TEXT NOT NULL DEFAULT '',
    salary_str TEXT,
    salary_min INTEGER,
    salary_max INTEGER,
    parsed_sections JSONB NOT NULL DEFAULT '{}',
    tags JSONB NOT NULL DEFAULT '[]',
    raw_text TEXT NOT NULL DEFAULT '',
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
    crawled_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMP WITH TIME ZONE,

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
-- Trigram index for fuzzy title/company search
CREATE INDEX IF NOT EXISTS idx_jds_title_trgm ON jds USING gin (title gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_jds_company_trgm ON jds USING gin (company gin_trgm_ops);
-- GIN indexes for JSON search on parsed_sections and tags
CREATE INDEX IF NOT EXISTS idx_jds_tags ON jds USING gin (tags jsonb_path_ops);
CREATE INDEX IF NOT EXISTS idx_jds_parsed_sections ON jds USING gin (parsed_sections jsonb_path_ops);

-- ============================================================
-- Table: knowledge_chunks
-- JD text chunks for RAG retrieval.
-- MUST be created before match_history / optimizations
-- because optimizations(chunk_id) references knowledge_chunks(id).
-- ============================================================
CREATE TABLE IF NOT EXISTS knowledge_chunks (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL DEFAULT 'default',
    jd_id TEXT NOT NULL,
    chunk_index INTEGER NOT NULL CHECK (chunk_index >= 0),
    chunk_text TEXT NOT NULL DEFAULT '',
    chunk_type TEXT NOT NULL DEFAULT 'full' CHECK (chunk_type IN ('overview', 'responsibility', 'requirement', 'nice_to_have', 'full')),
    keywords JSONB DEFAULT '[]',
    embedding vector(512),
    embedding_dim INTEGER,
    context TEXT NOT NULL DEFAULT '',
    heading_path TEXT[],
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMP WITH TIME ZONE,

    FOREIGN KEY (jd_id) REFERENCES jds(id)
);

CREATE INDEX IF NOT EXISTS idx_chunk_user_id ON knowledge_chunks(user_id);
CREATE INDEX IF NOT EXISTS idx_chunk_jd_id ON knowledge_chunks(jd_id);
CREATE INDEX IF NOT EXISTS idx_chunk_type ON knowledge_chunks(chunk_type);
CREATE INDEX IF NOT EXISTS idx_chunk_deleted ON knowledge_chunks(deleted_at);
-- GIN index for full-text search on chunk_text
CREATE INDEX IF NOT EXISTS idx_chunk_text_gin ON knowledge_chunks USING gin (to_tsvector('simple', chunk_text));
-- HNSW index for vector similarity search (RAG lookup target)
-- pgvector 0.8+: vector_cosine_ops; older: vector_cos_ops
CREATE INDEX IF NOT EXISTS idx_chunk_embedding_hnsw ON knowledge_chunks
    USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);

-- ============================================================
-- Table: chunks_vector
-- PG-specific vector table for HNSW approximate nearest neighbor search.
-- Separated from knowledge_chunks to keep vector columns independent
-- (pgvector requires vector columns in their own table).
--
-- Index strategy:
--   1. HNSW (recommended): O(log n) query, fast, requires pgvector >= 0.5
--      - metric: l2 or cosine
--      - m: 16 (default, balance memory vs query speed)
--      - ef_construction: 64 (balance build time vs quality)
--   2. IVFFlat (fallback): O(log n) query, slower construction,
--      - useful if pgvector < 0.5 or HNSW not available
--      - NOTE: pgvector 0.8+ uses vector_cosine_ops (not vector_cos_ops)
-- ============================================================
CREATE TABLE IF NOT EXISTS chunks_vector (
    id TEXT PRIMARY KEY,
    jd_id TEXT NOT NULL,
    chunk_index INTEGER NOT NULL CHECK (chunk_index >= 0),
    chunk_text TEXT NOT NULL DEFAULT '',
    chunk_context TEXT NOT NULL DEFAULT '',
    embedding vector(512) NOT NULL,
    metadata JSONB DEFAULT '{}',
    heading_path TEXT[],
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),

    FOREIGN KEY (jd_id) REFERENCES jds(id)
);

-- HNSW index: cosine distance, m=16, ef_construction=64
-- NOTE: If pgvector version < 0.5, HNSW may not be available.
-- Fallback to IVFFlat:
--   CREATE INDEX IF NOT EXISTS chunks_vector_idx ON chunks_vector
--     USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
CREATE INDEX IF NOT EXISTS chunks_vector_idx ON chunks_vector
    USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);

-- GIN index for metadata key/value search
CREATE INDEX IF NOT EXISTS idx_chunks_vector_metadata ON chunks_vector USING gin (metadata);

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
    matched_skills JSONB DEFAULT '[]',
    missing_skills JSONB DEFAULT '[]',
    gaps JSONB NOT NULL DEFAULT '[]',
    recommendations JSONB NOT NULL DEFAULT '[]',
    skill_mapping JSONB DEFAULT '[]',
    should_apply INTEGER NOT NULL DEFAULT 0,
    user_feedback TEXT,
    applied INTEGER NOT NULL DEFAULT 0,
    applied_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMP WITH TIME ZONE,

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
    reason TEXT NOT NULL DEFAULT '',
    user_adopted INTEGER NOT NULL DEFAULT 0 CHECK (user_adopted IN (0, 1, 2)),
    user_rating INTEGER CHECK (user_rating BETWEEN 1 AND 5),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMP WITH TIME ZONE,

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
-- Table: quality_checks
-- Stores automated quality check results for data validation.
-- ============================================================
CREATE TABLE IF NOT EXISTS quality_checks (
    id SERIAL PRIMARY KEY,
    check_type TEXT NOT NULL,
    target_table TEXT,
    target_id INTEGER,
    score REAL,
    details JSONB,
    checked_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
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
    id SERIAL PRIMARY KEY,
    position TEXT NOT NULL,
    industry TEXT NOT NULL,
    function TEXT,
    skeleton_text TEXT NOT NULL,
    n_chunks INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL DEFAULT 'rag',
    industries_covered JSONB,
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    UNIQUE(position, industry, function)
);

CREATE INDEX IF NOT EXISTS idx_skeleton_cache_lookup
    ON skeleton_cache(position, industry, function);
CREATE INDEX IF NOT EXISTS idx_skeleton_cache_expires
    ON skeleton_cache(expires_at);

-- ============================================================
-- Table: llm_calls
-- Dedicated observability table for every LLM invocation.
-- ============================================================
CREATE TABLE IF NOT EXISTS llm_calls (
    id SERIAL PRIMARY KEY,
    request_id TEXT,
    model TEXT NOT NULL,
    endpoint TEXT,
    operation TEXT NOT NULL DEFAULT 'analyze',
    prompt_tokens INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    total_tokens INTEGER NOT NULL DEFAULT 0,
    latency_ms INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'success',
    error_type TEXT,
    error_message TEXT,
    metadata JSONB,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_llm_calls_created_at ON llm_calls(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_llm_calls_model ON llm_calls(model);
CREATE INDEX IF NOT EXISTS idx_llm_calls_status ON llm_calls(status);
CREATE INDEX IF NOT EXISTS idx_llm_calls_operation ON llm_calls(operation);

-- ============================================================
-- Table: audit_logs
-- v2.1 P1-16: 用户关键操作审计日志
-- ============================================================
CREATE TABLE IF NOT EXISTS audit_logs (
    id SERIAL PRIMARY KEY,
    user_id TEXT NOT NULL DEFAULT 'default',
    action TEXT NOT NULL,
    target_table TEXT,
    target_id TEXT,
    status TEXT NOT NULL DEFAULT 'success',
    error_message TEXT,
    details JSONB,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_audit_user_id ON audit_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_logs(action);
CREATE INDEX IF NOT EXISTS idx_audit_target ON audit_logs(target_table, target_id);
CREATE INDEX IF NOT EXISTS idx_audit_created_at ON audit_logs(created_at DESC);
