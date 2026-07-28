-- ============================================================
-- Migration 014 (PG): knowledge_chunks.embedding 保留 vector(512) + HNSW 已就位
-- 与 SQLite migration 014 对齐 — SQLite 切 vec0 + 二进制 BLOB，
-- PG 端 pgvector 已用 vector(512)（schema_pg.sql:127）+ HNSW 索引（migration 003）。
-- 本迁移仅为占位/对齐编号，无 schema 变更；schema_version 标记到位。
-- ============================================================

UPDATE schema_version
SET version = 14,
    description = 'embedding 保留 vector(512) + HNSW（PG 端 sqlite-vec vec0 不适用）',
    applied_at = NOW()
WHERE id = 1;