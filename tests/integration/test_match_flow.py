# -*- coding: utf-8 -*-
"""v2.1 M4.6: 集成测试 — JD → 切分 → embedding → 写库 → 检索 → match 闭环。

使用 mock_embedder 替换真实 BGE，避免下载 95MB 模型；用 tmp_db 隔离 sqlite 文件。
"""
from __future__ import annotations


SAMPLE_JD = """职位描述：
我们正在招募 AI 产品经理，参与 LLM 应用建设。

岗位职责：
- 负责 AI 产品规划与落地
- 推动跨团队协作，梳理 PRD
- 跟进 LLM / RAG 技术选型

任职要求：
- 3 年以上互联网产品经验
- 熟悉 LLM、RAG、Agent 应用架构
- 良好的英语沟通能力

加分项：
- 有 ToB SaaS 产品经验
"""


def test_full_match_flow(tmp_db, mock_embedder):
    """端到端：插 JD → 切分+向量化落库 → 检索 → 写 match。"""
    from tools.jd_indexer import embed_and_store_jd_chunks

    # 1) 插简历 + JD
    rid = tmp_db.insert_resume({
        "user_id": "default", "name": "Leon",
        "skills": ["LLM", "RAG", "Agent"],
        "experience_years": 3,
    })
    jid = tmp_db.insert_jd({
        "user_id": "default", "url": "https://x/y", "title": "AI PM",
        "company": "ACME", "raw_text": SAMPLE_JD,
    })

    # 2) 切分 + 向量化（用 mock embedder，8 维确定向量）
    n = embed_and_store_jd_chunks(tmp_db, jid, SAMPLE_JD)
    assert n > 0

    chunks = tmp_db.get_chunks_by_jd(jid)
    assert len(chunks) == n
    types = {c["chunk_type"] for c in chunks}
    assert "responsibility" in types
    assert "requirement" in types
    # embedding round-trip 成功
    assert all(c["embedding"] and len(c["embedding"]) == 8 for c in chunks)

    # 3) 检索：用 mock embedder 算 cosine + 类型加权
    results = tmp_db.search_similar_chunks("LLM RAG 经验", top_k=3)
    assert len(results) > 0
    for r in results:
        assert "similarity" in r
        assert "chunk_type" in r
        assert "ranked_score" in r
        assert r["jd_id"] == jid

    # 4) 写 match
    mid = tmp_db.insert_match({
        "resume_id": rid, "jd_id": jid, "score": 85,
        "reasoning": "matched on LLM/RAG",
        "matched_skills": ["LLM", "RAG"],
        "missing_skills": ["ToB SaaS"],
    })
    matches = tmp_db.list_matches(jd_id=jid)
    assert len(matches) == 1 and matches[0]["id"] == mid

    # 5) 软删 JD → chunks 级联软删，检索不再命中
    tmp_db.soft_delete_jd(jid)
    after = tmp_db.search_similar_chunks("LLM RAG 经验", top_k=3)
    assert all(r["jd_id"] != jid for r in after)


def test_empty_raw_text_skipped(tmp_db, mock_embedder):
    """空 raw_text 不应崩，只是 0 chunks。"""
    from tools.jd_indexer import embed_and_store_jd_chunks
    jid = tmp_db.insert_jd({"user_id": "default", "url": "u", "title": "t",
                             "company": "c", "raw_text": ""})
    n = embed_and_store_jd_chunks(tmp_db, jid, "")
    assert n == 0
    assert tmp_db.get_chunks_by_jd(jid) == []
