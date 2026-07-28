-- ============================================================
-- Migration 016 (SQLite): chunks.retry_count 字段 — backfill 死循环兜底
-- 背景（2026-07-28 hotfix）：
--   M-v4-1 收口时 backfill 24091/24093 = 99.99%，剩 2 条被 MiniMax `new_sensitive`
--   敏感词过滤器永久拒，每次脚本重跑都撞回这同 2 条（done=26/failed=26 日志同 ID）。
--   决策：可忽略（2/24093 = 0.008% 噪音），但脚本需加 retry_count 上限从根上关死循环。
--   本 migration 加 retry_count 字段；scripts/backfill_translate_chunks.py 改 SELECT
--   加 `retry_count < ?` 过滤，每次失败 retry_count + 1，达到 MAX_RETRIES_PER_RECORD
--   (默认 3) 后该 chunk 静默退出，避免下次再被捞。
-- ============================================================

ALTER TABLE knowledge_chunks ADD COLUMN retry_count INTEGER NOT NULL DEFAULT 0;

-- 增量回填索引：(language, translated_at, retry_count) 组合，便于 WHERE 过滤
-- SQLite 兼容 IF NOT EXISTS
CREATE INDEX IF NOT EXISTS idx_chunk_retry_count
    ON knowledge_chunks(retry_count)
    WHERE translated_at IS NULL;

UPDATE schema_version
SET version = 16,
    description = 'Add knowledge_chunks.retry_count — backfill MAX_RETRIES_PER_RECORD 兜底 (M-v4-1 hotfix)',
    applied_at = datetime('now')
WHERE id = 1;
