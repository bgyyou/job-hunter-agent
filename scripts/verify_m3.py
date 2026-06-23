# -*- coding: utf-8 -*-
"""M3 验证脚本：embedder + chunker + 向量检索端到端。

跑法：
    python scripts/verify_m3.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def section(title: str):
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


def main():
    # ---------- 1. Embedder ----------
    section("1) Embedder 维度 / 速度")
    from tools.embedder import Embedder
    t0 = time.time()
    emb = Embedder()
    v = emb.embed("AI 产品经理 大模型 RAG")
    t1 = time.time()
    print(f"  模型: {emb.model_name}")
    print(f"  首次加载+1 次 embed 耗时: {t1 - t0:.2f}s")
    print(f"  向量维度: {len(v)}")
    assert len(v) >= 256, "维度异常"
    # L2 norm 应 ~1
    norm = sum(x * x for x in v) ** 0.5
    print(f"  L2 范数: {norm:.4f}（应 ≈ 1.0）")

    # 批量
    t0 = time.time()
    vs = emb.embed_batch(["Python 后端", "前端 React", "机器学习", "财务报表"])
    t1 = time.time()
    print(f"  批量 4 条耗时: {(t1 - t0) * 1000:.1f}ms")

    # ---------- 2. Chunker ----------
    section("2) Chunker 切分类型覆盖（合成样例 + 真实 JD）")
    from tools.chunker import SemanticChunker

    synth_jd = (
        "职位描述\n我们是一家 AI 公司，致力于通过大模型重新定义生产力。\n\n"
        "岗位职责\n- 负责 LLM 应用的产品定义与端到端交付\n"
        "- 与算法、工程、设计团队协作\n- 通过用户访谈和数据分析驱动迭代\n\n"
        "任职要求\n- 3 年以上 B2C/B2B 产品经验\n- 熟悉 RAG / Agent / Prompt Engineering\n"
        "- 优秀的英文阅读与写作能力\n\n"
        "加分项\n- 有 0→1 项目落地经验\n- 熟悉 LangChain / OpenAI API"
    )
    synth_chunks = SemanticChunker().split(synth_jd)
    synth_types = {c.chunk_type for c in synth_chunks}
    print(f"  [合成 JD] chunks={len(synth_chunks)}, types={sorted(synth_types)}")
    for c in synth_chunks:
        head = c.heading_path[0] if c.heading_path else ""
        print(f"    [{c.chunk_type:<14}] {c.chunk_text[:50]!r}  heading={head!r}")
    assert "responsibility" in synth_types, "应识别岗位职责"
    assert "requirement" in synth_types, "应识别任职要求"
    assert "nice_to_have" in synth_types, "应识别加分项"
    assert "full" not in synth_types, "不应出现遗留 'full' 类型"

    dump_path = PROJECT_ROOT / "data" / "temp" / "m2_5_jobsdb_real_dump.json"
    if dump_path.exists():
        data = json.loads(dump_path.read_text(encoding="utf-8"))
        raw_text = data.get("raw_text") or synth_jd
        real_chunks = SemanticChunker().split(raw_text)
        real_types = {c.chunk_type for c in real_chunks}
        print(f"\n  [真实 JobsDB JD] len={len(raw_text)}, chunks={len(real_chunks)}, "
              f"types={sorted(real_types)}")
    else:
        raw_text = synth_jd
        real_chunks = synth_chunks

    # ---------- 3. 端到端：插 JD → 向量化 → 检索 ----------
    section("3) 端到端：插 JD → embed_and_store_jd_chunks → Retriever.retrieve")
    from database.factory import get_db
    from tools.jd_indexer import embed_and_store_jd_chunks
    from tools.retriever import Retriever

    db = get_db()
    test_url = f"verify-m3://{int(time.time())}"
    jd_id = db.insert_jd({
        "url": test_url,
        "title": "[VERIFY M3] AI 产品经理 LLM",
        "company": "Verify Co.",
        "raw_text": raw_text,
        "parsed_sections": {"verify": "m3"},
        "tags": ["verify_m3"],
        "source": "verify_m3",
    })
    print(f"  JD inserted: id={jd_id}")

    t0 = time.time()
    n = embed_and_store_jd_chunks(db, jd_id, raw_text)
    t1 = time.time()
    print(f"  embed_and_store: {n} chunks, {(t1 - t0) * 1000:.0f}ms")
    assert n >= 3, "向量化 chunk 数量异常"

    # 检索
    retriever = Retriever(db)
    queries = [
        ("LLM 应用 产品交付", "responsibility"),
        ("RAG Agent Prompt 经验", "requirement"),
        ("LangChain", "nice_to_have"),
    ]
    for q, expected_pref in queries:
        results = retriever.retrieve(q, top_k=5, min_similarity=0.3)
        print(f"\n  query: {q!r}  → {len(results)} hits")
        for r in results[:3]:
            print(f"    sim={r['similarity']:.3f}  weight={r['chunk_weight']:.1f}  "
                  f"type={r['chunk_type']:<14}  text={r['chunk_text'][:50]!r}")
        assert results, f"query {q!r} 应返回结果"
        top_sim = results[0]["similarity"]
        assert 0.4 <= top_sim <= 0.99, f"top similarity 异常: {top_sim}"

    # 清理验证 JD
    try:
        db.soft_delete_jd(jd_id)
        print(f"\n  cleanup: soft-deleted jd_id={jd_id}")
    except Exception:
        pass

    section("M3 VERIFY OK")


if __name__ == "__main__":
    main()
