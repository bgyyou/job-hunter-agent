-- ============================================================
-- Migration 007 (SQLite): dedicated LLM call observability table
-- ============================================================

CREATE TABLE IF NOT EXISTS llm_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
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
    metadata TEXT,  -- JSON
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_llm_calls_created_at ON llm_calls(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_llm_calls_model ON llm_calls(model);
CREATE INDEX IF NOT EXISTS idx_llm_calls_status ON llm_calls(status);
CREATE INDEX IF NOT EXISTS idx_llm_calls_operation ON llm_calls(operation);

UPDATE schema_version
SET version = 7,
    description = 'Add llm_calls observability table',
    applied_at = datetime('now')
WHERE id = 1;
