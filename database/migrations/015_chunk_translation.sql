-- 015: chunk 级翻译字段（cross-language 召回支持）
-- 背景（2026-07-25）：
--   DB 99% 索引 chunks 来自 jobsdb (English source)，但 51job/liepin/manual 中文查询占 50%+
--   q0084 "招聘经理coe" → top hits "Personal Assistant to the Managing Partner" 暴露 cross-language 错配
-- 决策（用户 2026-07-25 选 A 方案）：
--   索引时把英文 chunk 翻译成中文，存到 chunk_text；原文存 original_text；language 标 en
--   vec0 embedding 同步重建（BGE-small-zh 在中文向量空间里 cosine 对齐）

ALTER TABLE knowledge_chunks ADD COLUMN original_text TEXT;
ALTER TABLE knowledge_chunks ADD COLUMN language TEXT NOT NULL DEFAULT 'zh' CHECK (language IN ('zh', 'en', 'mixed'));
ALTER TABLE knowledge_chunks ADD COLUMN translated_at TEXT;

-- 翻译进度索引（增量回填用）
CREATE INDEX IF NOT EXISTS idx_chunk_language ON knowledge_chunks(language);
CREATE INDEX IF NOT EXISTS idx_chunk_untranslated
    ON knowledge_chunks(language, translated_at)
    WHERE language IN ('en', 'mixed') AND translated_at IS NULL;

-- schema_version 同步
UPDATE schema_version SET version = 15 WHERE version = 14;
