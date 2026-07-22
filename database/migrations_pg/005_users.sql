-- ============================================================
-- Migration 005 (PG): users table for product auth
-- 对齐 SQLite 版 005_users.sql；方言差异：
--   SQLite 的 datetime now 默认值 → NOW()，时间列用 TIMESTAMPTZ
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
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMPTZ,
    CHECK (email IS NOT NULL OR phone IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE INDEX IF NOT EXISTS idx_users_phone ON users(phone);
CREATE INDEX IF NOT EXISTS idx_users_provider_subject ON users(provider, provider_subject);
CREATE INDEX IF NOT EXISTS idx_users_deleted ON users(deleted_at);

UPDATE schema_version
SET version = 5,
    description = 'Add users table for product auth',
    applied_at = NOW()
WHERE id = 1;
