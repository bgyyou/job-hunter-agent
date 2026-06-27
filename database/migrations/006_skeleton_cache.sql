-- ============================================================
-- Migration 006 (SQLite): skeleton cache for Flow A build_skeleton
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

UPDATE schema_version
SET version = 6,
    description = 'Add skeleton cache for Flow A build_skeleton',
    applied_at = datetime('now')
WHERE id = 1;
