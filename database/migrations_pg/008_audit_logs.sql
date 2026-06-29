-- ============================================================
-- Migration 008 (PG): audit_logs table for user action auditing
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

UPDATE schema_version
SET version = 8,
    description = 'Add audit_logs table',
    applied_at = NOW()
WHERE id = 1;
