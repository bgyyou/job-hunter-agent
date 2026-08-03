-- ============================================================
-- Migration 017 (PostgreSQL): DROP rag_industry_function dead schema
-- 对齐 SQLite 017。PG 也曾创建该表（migrations_pg/011），现统一 DROP。
-- ============================================================

DROP TABLE IF EXISTS rag_industry_function;
