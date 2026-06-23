-- ============================================================
-- Migration 003 (PG): pgvector HNSW index on knowledge_chunks.embedding
-- 目标：RAG 向量搜索从 O(n) 顺序扫描加速到 O(log n)
-- 等效于 chunks_vector 已有的 HNSW，但 knowledge_chunks 是 RAG 实际查询表
-- ============================================================

-- HNSW index: cosine distance, m=16, ef_construction=64
-- 注意：embedding 列可能是 NULL（旧数据），NULL 不被索引但不影响查询
CREATE INDEX IF NOT EXISTS idx_chunk_embedding_hnsw
    ON knowledge_chunks
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- 更新 schema_version
UPDATE schema_version SET version = 3, description = 'HNSW index on knowledge_chunks.embedding for fast RAG retrieval' WHERE id = 1;