-- ============================================================
-- Migration 018 (SQLite): DROP knowledge_chunks.legacy 列
-- 目的:
--   knowledge_chunks.legacy 列 137 行代码层面做 INSERT 时的兼容保留；
--   v2.1 P2-017 复审发现仍有 45 行 legacy=1 残留数据（from backfill_chunks.py）
--   且所有 SQL 过滤层都加了 `kc.legacy = 0`。owner 2026-08-03 Q4 决议
--   "P0 强制清理"：DELETE 残留行 + DROP COLUMN + 全量重写 SQL 去掉过滤。
--
--   注：019+ 新 DB 启动序列不再 ADD COLUMN legacy（sqlite_backend.py
--   _apply_idempotent_migrations 已删 ALTER）。
-- ============================================================

-- 1) 清掉旧 backfill 残留的 legacy=1 行（P2-017 评估期发现的 45 行）
DELETE FROM knowledge_chunks WHERE legacy = 1;

-- 2) DROP COLUMN（SQLite 3.35+ 原生支持；CI 使用 SQLite ≥3.40）
ALTER TABLE knowledge_chunks DROP COLUMN legacy;

UPDATE schema_version
SET version = 18,
    description = 'DROP knowledge_chunks.legacy column + DELETE 45 row residue (v4 M-v4-2)',
    applied_at = datetime('now')
WHERE id = 1;
