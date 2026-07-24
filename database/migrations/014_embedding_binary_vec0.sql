-- ============================================================
-- Migration 014 (SQLite): sqlite-vec vec0 索引 + embedding 改二进制 BLOB
-- 目的:
--   1. vector_search 走 vec0 MATCH，O(N) JSON 全表扫描 → ANN 索引（24k chunks 实测 6334ms → 59ms，107x）
--   2. embedding 列内嵌格式 json.dumps(list) → numpy.float32() binary（每条 ~11KB → 2KB）
--
-- 设计要点:
--   - vec0 虚拟表 knowledge_chunks_vec 的 rowid 与 knowledge_chunks.rowid 对齐，
--     这样 vec0 MATCH 返回的 rowid = knowledge_chunks.rowid，可一行 JOIN 回主表
--     （knowledge_chunks.id 是 TEXT UUID，vec0 虚拟表 column 必须是 integer，额外列约束受限，
--      直接借 rowid 关联最干净）
--   - vec0 cosine 要求向量 L2-normalized；BGE-small-zh-v1.5 输出已 L2-norm，无需额外处理
--   - embedding_dim != 512 的 chunk 不入 vec0（MOCK 测试 + 早期 chunk）；vector_search
--     走 vec0 时只召回 512 维 chunk；其余走 numpy fallback
--   - 主表 embedding 列类型不变（BLOB），但写入格式从 json 切到 float32 binary（计划见 SqliteBackend._embedding_to_blob）
-- ============================================================

-- 1) 建 vec0 虚拟表
--    IF NOT EXISTS 幂等：旧 DB 已经导入过（sqlite_vec.load 已启用），重启时这行不报错
CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_chunks_vec USING vec0(
    embedding float[512] distance_metric=cosine
);

-- 2) 标记 schema_version
UPDATE schema_version
SET version = 14,
    description = 'sqlite-vec vec0 索引 + embedding 二进制 BLOB（v4 P0-模块 3）',
    applied_at = datetime('now')
WHERE id = 1;
