-- ============================================================
-- Migration 005 (SQLite): users table for product auth
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

UPDATE schema_version
SET version = 5,
    description = 'Add users table for product auth',
    applied_at = datetime('now')
WHERE id = 1;
