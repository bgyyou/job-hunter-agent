-- ============================================================
-- Migration 017 (SQLite): DROP rag_industry_function dead schema
-- 目的:
--   rag_industry_function 表 011 引入后从未真正投产：v4-2 RAG 0 召回修复
--   (services/jd_parser.py RAGJDRetriever) 改为走 Retriever 语义检索，
--   整张表的 1 行 user_contributed 数据无召回价值。owner 2026-08-03 Q4 决议
--   "P0 强制清理"：不留 alias，删表 + 删代码引用。
--
--   注：011 自身已落 git 历史，不动 011；017 在所有新 DB 启动序列里后置执行。
-- ============================================================

DROP TABLE IF EXISTS rag_industry_function;

UPDATE schema_version
SET version = 17,
    description = 'DROP rag_industry_function dead schema (v4 M-v4-2)',
    applied_at = datetime('now')
WHERE id = 1;
