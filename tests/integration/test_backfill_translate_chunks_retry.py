# -*- coding: utf-8 -*-
"""P1-003 回归：翻译 backfill MAX_RETRIES_PER_RECORD 兜底行为可观测。

commit ``3b854ef`` 加了 ``MAX_RETRIES_PER_RECORD`` 兜底（``scripts/backfill_translate_chunks.py:54``），
但没有回归测试覆盖。本文件补三条：

1. **永久失败 → chunk 自动跳过**：连续 N 次 LLM 永久 429 → retry_count 达上限 →
   ``SELECT ... WHERE retry_count < ?`` 过滤掉 → 不再处理（"skipped"）
2. **偶发失败 → 重试成功**：first call fail, second call success → 该 chunk
   ``translated_at`` 被写入，retry_count 反映中途失败次数
3. **retry_count 字段持久化**：每批失败的 chunk ``retry_count + 1`` 落到 DB 列
   （即便后续 run 也会读到最新值，不跨 run 丢）

注意：本测试直接用 ``backfill_translate_chunks.BackfillRunner``（不用 backend
抽象），因为 backfill 走的是自己 ``_conn()`` 的裸 sqlite3 连接，必须用真
DB 文件。embedding 走 ``tests.conftest._FakeEmbedder``（8-d 向量）避开
网络；脚本里 vec0 写入会校验 dim，所以成功路径要走 ``_FakeEmbedder`` 不
是裸 ``[0.1]*8``。"""
from __future__ import annotations

import asyncio
import sqlite3

import pytest

from database.backends.sqlite_backend import SqliteBackend


class _BgeDimEmbedder:
    """512-d fake embedder（vec0 表强校验此维数）。

    BackfillRunner 实例化后调 ``.embed(text)`` 或 ``.embed_batch(texts)``。
    用 SHA-256 派生 deterministic 向量。
    """

    _DEFAULT_DIM = 512

    def __init__(self, *args, **kwargs):
        self._dim = self._DEFAULT_DIM
        self.model_name = "fake-bge-512"

    @property
    def dim(self) -> int:
        return self._dim

    def embed(self, text: str):
        return self.embed_batch([text])[0]

    def embed_batch(self, texts, batch_size: int = 32):
        import hashlib
        out = []
        for t in texts:
            digest = b""
            seed = (t or " ").encode("utf-8")
            while len(digest) < self._dim * 4:
                digest += hashlib.sha256(seed + digest).digest()
            vec = [(digest[i] / 255.0) * 2 - 1 for i in range(self._dim)]
            norm = sum(x * x for x in vec) ** 0.5 or 1.0
            out.append([x / norm for x in vec])
        return out


def _seed_chunk(backend: SqliteBackend, text: str, *, cid: str):
    """建一条 knowledge_chunks 记录：英文、未翻译、retry_count=0。

    先创建对应的 jds 行（FK 依赖），再插 chunk。每次拿/关独立连接，
    避免与 ``BackfillRunner``（自己 ``sqlite3.connect``）长期持锁互锁。"""
    jd_id = f"jd-{cid}"
    conn = sqlite3.connect(str(backend.db_path))
    try:
        conn.execute(
            "INSERT OR IGNORE INTO jds "
            "(id, user_id, url, title, source, is_public, parsed_sections, tags) "
            "VALUES (?, 'test', ?, ?, 'manual', 0, '{}', '[]')",
            (jd_id, f"https://example/{cid}", cid),
        )
        conn.execute(
            "INSERT INTO knowledge_chunks "
            "(id, jd_id, chunk_index, chunk_text, original_text, language, "
            " translated_at, retry_count, deleted_at) "
            "VALUES (?, ?, 0, ?, ?, 'en', NULL, 0, NULL)",
            (cid, jd_id, text, text),
        )
        conn.commit()
    finally:
        conn.close()


def _read_chunk(backend: SqliteBackend, cid: str):
    """从 knowledge_chunks 读一行。独立短连接。"""
    conn = sqlite3.connect(str(backend.db_path))
    try:
        row = conn.execute(
            "SELECT chunk_text, translated_at, retry_count, language, original_text "
            "FROM knowledge_chunks WHERE id = ?", (cid,),
        ).fetchone()
        return row
    finally:
        conn.close()


# ===========================================================================
# 1. 永久失败：retry_count 达上限后 chunk 被 SELECT 过滤掉 → 不再处理
# ===========================================================================

class TestPermanentFailureSkipped:
    """模拟 LLM 永久 429：连续 MAX_RETRIES 次 run → 后续 run SELECT 不再选中。"""

    def test_max_retries_per_record_skips_after_threshold(
        self, tmp_db, monkeypatch,
    ):
        from scripts.backfill_translate_chunks import BackfillRunner

        _seed_chunk(tmp_db, "Permanent failure text", cid="c-permanent")
        MAX_RETRIES = 3

        # 构造一个永远返 (None, error) 的 translator
        class _FailingTranslator:
            async def translate_batch(self, texts, on_done=None):
                return [(t, None, "API 调用失败 (429): rate limit") for t in texts]

        # 跑 MAX_RETRIES 次 backfill
        for run_idx in range(MAX_RETRIES):
            runner = BackfillRunner(
                db_path=str(tmp_db.db_path),
                batch_size=10,
                concurrency=1,
                dry_run=False,
                max_retries=MAX_RETRIES,
            )
            monkeypatch.setattr(runner, "translator", _FailingTranslator())
            asyncio.run(runner.run(limit=0))

        # 末态：retry_count == MAX_RETRIES, translated_at 仍 NULL（永久卡死 chunk）
        final = _read_chunk(tmp_db, "c-permanent")
        assert final[1] is None, (
            f"永久失败 chunk 不应有 translated_at: {final[1]}"
        )
        assert final[2] == MAX_RETRIES, (
            f"retry_count 应等于上限 {MAX_RETRIES}，实际 {final[2]}"
        )

        # 再跑一次 → 该 chunk 不应再被 SELECT 选中（自动跳过 = "skipped"）
        # 验证方法：把 _FailingTranslator 的调用次数从无限降到 0，
        # 因为 SELECT 阶段就过滤了
        class _ShouldNotBeCalled:
            def __init__(self):
                self.translate_batch_calls = 0

            async def translate_batch(self, texts, on_done=None):
                self.translate_batch_calls += 1
                return [(t, None, "won't happen") for t in texts]

        fake = _ShouldNotBeCalled()
        runner = BackfillRunner(
            db_path=str(tmp_db.db_path),
            batch_size=10,
            concurrency=1,
            dry_run=False,
            max_retries=MAX_RETRIES,
        )
        monkeypatch.setattr(runner, "translator", fake)
        asyncio.run(runner.run(limit=0))

        assert fake.translate_batch_calls == 0, (
            f"retry_count 达上限后应被 SELECT 过滤，实际仍调了 "
            f"{fake.translate_batch_calls} 次"
        )

    def test_retry_exhausted_counted_in_stats(self, tmp_db, monkeypatch):
        """stats() 报 ``retry_exhausted`` 数 — 评测面板接入用。"""
        from scripts.backfill_translate_chunks import BackfillRunner

        _seed_chunk(tmp_db, "t1", cid="c-stat-1")
        _seed_chunk(tmp_db, "t2", cid="c-stat-2")
        # 这条 chunk 是旧数据但 retry_count 已被前次跑满到上限（模拟）
        _seed_chunk(tmp_db, "t3", cid="c-stat-3")
        conn = sqlite3.connect(str(tmp_db.db_path))
        try:
            conn.execute(
                "UPDATE knowledge_chunks SET retry_count = 5 WHERE id = 'c-stat-3'"
            )
            conn.commit()
        finally:
            conn.close()

        runner = BackfillRunner(
            db_path=str(tmp_db.db_path),
            batch_size=10,
            concurrency=1,
            dry_run=True,  # 只读 stats
            max_retries=3,
        )
        stats = runner.stats()
        # c-stat-3 retry_count=5 >= max_retries=3 → 计入 retry_exhausted
        assert stats["retry_exhausted"] >= 1, stats
        # c-stat-1/2 未翻译 → 计入 to_translate
        assert stats["to_translate"] >= 2, stats


# ===========================================================================
# 2. 偶发失败：重试成功 → chunk 入库（translated_at 写入）
# ===========================================================================

class TestIntermittentFailure:

    def test_intermittent_failure_then_success_imports_chunk(
        self, tmp_db, monkeypatch,
    ):
        """第一次 LLM 失败 → retry_count 累加；模拟"LLM 已恢复"重置
        retry_count=0 后再跑 → translated_at 写入。

        注：BackfillRunner 单次 ``run()`` 内的 while 循环会把 chunk 反
        复处理直到 retry_count ≥ ``max_retries``。所以"先失败后成功"横跨
        两次 ``run()``：
          - run 1: translator 全失败，retry_count 累加到 N（不写入）
          - reset retry_count=0
          - run 2: 一次成功 → translated_at 写入、retry_count 不再 +1
        """
        from scripts.backfill_translate_chunks import BackfillRunner

        _seed_chunk(tmp_db, "Flaky chunk text", cid="c-flaky")

        MAX_RETRIES = 5

        class _AlwaysFailTranslator:
            def __init__(self):
                self.calls = 0

            async def translate_batch(self, texts, on_done=None):
                self.calls += 1
                return [(t, None, "API 调用失败 (429): rate limit") for t in texts]

        class _AlwaysSucceedTranslator:
            async def translate_batch(self, texts, on_done=None):
                return [(f"{t} - 翻译后", f"{t} - 翻译后", None) for t in texts]

        # Embedder 走 512-d fake（vec0 写入校验 dim，必须 ≥ 512）
        import tools.embedder as embedder_mod
        monkeypatch.setattr(embedder_mod, "Embedder", _BgeDimEmbedder)

        # run 1：全失败 → retry_count 累加到 MAX_RETRIES；不写入
        r1 = BackfillRunner(
            db_path=str(tmp_db.db_path),
            batch_size=10, concurrency=1,
            dry_run=False, max_retries=MAX_RETRIES,
        )
        monkeypatch.setattr(r1, "translator", _AlwaysFailTranslator())
        asyncio.run(r1.run(limit=0))

        after_fail = _read_chunk(tmp_db, "c-flaky")
        assert after_fail[1] is None, (
            f"全部失败 chunk 不应有 translated_at，实际 {after_fail[1]!r}"
        )
        assert after_fail[2] == MAX_RETRIES, (
            f"retry_count 应累加到 {MAX_RETRIES}，实际 {after_fail[2]}"
        )

        # reset retry_count=0 — 模拟"LLM 已恢复"
        conn = sqlite3.connect(str(tmp_db.db_path))
        try:
            conn.execute(
                "UPDATE knowledge_chunks SET retry_count = 0 WHERE id = ?",
                ("c-flaky",),
            )
            conn.commit()
        finally:
            conn.close()

        # run 2：成功路径 → translated_at 写入；retry_count 不变 (0)
        r2 = BackfillRunner(
            db_path=str(tmp_db.db_path),
            batch_size=10, concurrency=1,
            dry_run=False, max_retries=MAX_RETRIES,
        )
        monkeypatch.setattr(r2, "translator", _AlwaysSucceedTranslator())
        asyncio.run(r2.run(limit=0))

        after_ok = _read_chunk(tmp_db, "c-flaky")
        assert after_ok[1] is not None, (
            "LLM 恢复后该 chunk 应被翻译（translated_at 写入）"
        )
        # 成功 run 内部只跑一次，retry_count 保持 0（成功不 bump）
        assert after_ok[2] == 0, (
            f"成功 run 不应 bump retry_count；应为 0，实际 {after_ok[2]}"
        )
        # chunk_text 已被翻译成 "Flaky chunk text - 翻译后"
        assert "翻译后" in (after_ok[0] or ""), (
            f"chunk_text 应包含译文，实际 {after_ok[0]!r}"
        )


# ===========================================================================
# 3. retry_count 字段持久化
# ===========================================================================

class TestRetryCountPersistence:

    def test_retry_count_persists_across_runs(self, tmp_db, monkeypatch):
        """retry_count +1 后下次 run 看到的是最新值（不是 reset 0）。

        BackfillRunner 单次 run 的内部 while 循环会把 retry_count 累加到
        ``max_retries`` 边界，所以配置 2：run 1 后 retry_count=2（不再被
        SELECT），run 2 也不变。本断言验证**跨 run 持久化**（run 2 不 reset）。"""
        from scripts.backfill_translate_chunks import BackfillRunner

        _seed_chunk(tmp_db, "Persisted chunk", cid="c-persist")

        class _FailingTranslator:
            async def translate_batch(self, texts, on_done=None):
                return [(t, None, "临时性错误") for t in texts]

        MAX_RETRIES = 2
        for _ in range(2):  # 跑 2 次
            r = BackfillRunner(
                db_path=str(tmp_db.db_path),
                batch_size=10,
                concurrency=1,
                dry_run=False, max_retries=MAX_RETRIES,
            )
            monkeypatch.setattr(r, "translator", _FailingTranslator())
            asyncio.run(r.run(limit=0))

        # run 1 内部 while 累加到 2；run 2 SELECT 是 0 行跳过
        mid = _read_chunk(tmp_db, "c-persist")
        assert mid[2] == MAX_RETRIES, (
            f"累加两次后 retry_count={MAX_RETRIES}，actual {mid[2]} — "
            f"累加错误或被 reset 0 了"
        )

        # 再跑一次：retry_count 已经持久 = 2，本次 SELECT 0 行，不应再 bump
        before = mid[2]
        r3 = BackfillRunner(
            db_path=str(tmp_db.db_path),
            batch_size=10,
            concurrency=1,
            dry_run=False, max_retries=MAX_RETRIES,
        )
        monkeypatch.setattr(r3, "translator", _FailingTranslator())
        asyncio.run(r3.run(limit=0))

        after = _read_chunk(tmp_db, "c-persist")
        assert after[2] == before, (
            f"已是阈值的 chunk 不应再被处理；retry_count {before} → "
            f"{after[2]}"
        )

        # 直接读 DB 列（不经 backend）确认列真有 +1 增量（跨连接可见）
        raw_conn = sqlite3.connect(str(tmp_db.db_path))
        try:
            raw_count = raw_conn.execute(
                "SELECT retry_count FROM knowledge_chunks WHERE id = ?",
                ("c-persist",),
            ).fetchone()[0]
        finally:
            raw_conn.close()
        assert raw_count == before, (
            f"DB 列 retry_count 应有持久化值 {before}，actual {raw_count}"
        )


