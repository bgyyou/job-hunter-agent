-- ============================================================
-- Migration 015 (PG): knowledge_chunks 加 original_text / language / translated_at
-- 与 SQLite migration 015 对齐 — 翻译 backfill 用。
-- SQLite 015 用 TEXT + 'zh' 默认；PG 同步：
--   original_text TEXT（PG TEXT 与 SQLite TEXT 兼容）
--   language TEXT NOT NULL DEFAULT 'zh' CHECK (language IN ('zh','en','mixed'))
--   translated_at TIMESTAMP WITH TIME ZONE（PG 原生时区）
-- ============================================================

ALTER TABLE knowledge_chunks ADD COLUMN IF NOT EXISTS original_text TEXT;
ALTER TABLE knowledge_chunks ADD COLUMN IF NOT EXISTS language TEXT NOT NULL DEFAULT 'zh'
    CHECK (language IN ('zh', 'en', 'mixed'));
ALTER TABLE knowledge_chunks ADD COLUMN IF NOT EXISTS translated_at TIMESTAMP WITH TIME ZONE;

-- 翻译进度索引（增量回填用）
CREATE INDEX IF NOT EXISTS idx_chunk_language ON knowledge_chunks(language);
CREATE INDEX IF NOT EXISTS idx_chunk_untranslated
    ON knowledge_chunks(language, translated_at)
    WHERE language IN ('en', 'mixed') AND translated_at IS NULL;

-- schema_version 同步
UPDATE schema_version SET version = 15 WHERE version = 14;