#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""M-v4-1 web_app 拆分 — Flow B：上传简历 + JD → 匹配分析 → 优化 + Cover Letter。

来源：web_app.py 原 render_flow_b() + generate_optimized_resume + generate_cover_letter +
render_generation_toolbar + _db_resume_to_resume_data + resume_to_db_payload + jd_to_db_payload。

Streamlit multipage 自动识别 → sidebar 出现 "📄 Flow B" 入口。
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st  # noqa: E402

from web_app import (  # noqa: E402
    init_session_state,
    init_app_services,
    render_top_nav,
    require_services,
    run_async,
    current_user_id,
)

# log_action 走 services.audit_service（在 render_flow_b / generate_* 内部按需 import，避免循环）。

st.set_page_config(
    page_title="JobHunter · Flow B",
    page_icon="📄",
    layout="wide",
    initial_sidebar_state="collapsed",
)


# ---------------------------------------------------------------------------
# payload helpers（原文搬迁）
# ---------------------------------------------------------------------------


def resume_to_db_payload(resume_data: Dict[str, Any], user_id: str) -> Dict[str, Any]:
    """resume_data（ResumeProfile dict）→ db insert payload。"""
    return {
        "user_id": user_id,
        "name": resume_data.get("name", ""),
        "phone": resume_data.get("phone", ""),
        "email": resume_data.get("email", ""),
        "summary": resume_data.get("summary", ""),
        "skills": resume_data.get("skills", []) or [],
        "education": resume_data.get("education", []) or [],
        "experience": resume_data.get("experience", []) or resume_data.get("work", []) or [],
        "projects": resume_data.get("projects", []) or [],
        "target_roles": resume_data.get("target_roles", []) or [],
    }


def _db_resume_to_resume_data(row: Dict[str, Any]) -> Dict[str, Any]:
    """db row → resume_data（resume_data 字段对齐 models.resume.ResumeProfile）。"""
    return {
        "name": row.get("name", ""),
        "phone": row.get("phone", ""),
        "email": row.get("email", ""),
        "summary": row.get("summary", ""),
        "skills": row.get("skills", []) or [],
        "education": row.get("education", []) or [],
        "experience": row.get("experience", []) or [],
        "projects": row.get("projects", []) or [],
        "target_roles": row.get("target_roles", []) or [],
    }


def jd_to_db_payload(
    jd_text: str, jd_result: Dict[str, Any], user_id: str, source: str = "manual",
) -> Dict[str, Any]:
    return {
        "user_id": user_id,
        "title": jd_result.get("title", ""),
        "company": jd_result.get("company", ""),
        "location": jd_result.get("location", ""),
        "raw_text": jd_text,
        "parsed_sections": {
            "responsibilities": jd_result.get("responsibilities", []) or jd_result.get("core_requirements", []) or [],
            "requirements": jd_result.get("requirements", []) or jd_result.get("core_requirements", []) or [],
        },
        "tags": jd_result.get("keywords", []) or jd_result.get("tags", []) or [],
        "source": source,
    }


# ---------------------------------------------------------------------------
# render functions
# ---------------------------------------------------------------------------


def render_generation_toolbar() -> None:
    can_generate = bool(
        st.session_state.services_ready
        and st.session_state.resume_data
        and st.session_state.jd_result
        and st.session_state.match_result
    )
    col1, col2, col3 = st.columns([1, 1, 2])
    with col1:
        if st.button("生成优化简历", type="primary", disabled=not can_generate, use_container_width=True):
            generate_optimized_resume()
    with col2:
        if st.button("生成 Cover Letter", disabled=not can_generate, use_container_width=True):
            generate_cover_letter()
    with col3:
        if not can_generate:
            st.caption("完成上传简历、上传/选择 JD、匹配度分析后即可生成。")


def generate_optimized_resume() -> None:
    from loguru import logger
    from services.audit_service import log_action
    with st.spinner("正在基于 JD 库生成优化简历..."):
        try:
            from tools.retriever import Retriever
            jd_query = st.session_state.jd_result.get("title") or st.session_state.jd_result.get("raw_text", "")[:200]
            reference_chunks = Retriever().retrieve(jd_query, top_k=3, filter_chunk_type="responsibility")
            recommendations = st.session_state.match_result.get("recommendations", [])
            from tools.generator.resume_optimizer import ResumeOptimizer
            optimizer = ResumeOptimizer(st.session_state.llm_client)
            optimized = run_async(optimizer.optimize(
                st.session_state.resume_data,
                st.session_state.jd_result,
                recommendations,
                reference_chunks=reference_chunks,
            ))
            from tools.generator.resume_generator import ResumeGenerator
            generator = ResumeGenerator()
            st.session_state.optimized_resume = generator.to_markdown(optimized)
            st.session_state.optimized_resume_html = generator.to_html(optimized)
            st.success("优化简历已生成。")
        except Exception as exc:
            logger.exception("generate_optimized_resume failed")
            st.error(f"生成优化简历失败：{exc}")


def generate_cover_letter() -> None:
    from services.audit_service import log_action
    with st.spinner("正在生成 Cover Letter..."):
        try:
            company = st.session_state.flow_b_company_name or st.session_state.jd_result.get("company", "目标公司")
            from tools.generator.cover_letter_generator import CoverLetterGenerator
            generator = CoverLetterGenerator(st.session_state.llm_client)
            st.session_state.cover_letter = run_async(generator.generate(
                st.session_state.resume_data,
                st.session_state.jd_result,
                company,
            ))
            st.success("Cover Letter 已生成。")
        except Exception as exc:
            st.error(f"生成 Cover Letter 失败：{exc}")


def render_flow_b() -> None:
    from services.audit_service import log_action
    from services.jd_library_service import (
        count_visible_jds,
        get_visible_jd,
        insert_user_jd,
        list_visible_jds,
    )
    from services.pdf_ingestion_service import PdfIngestionService
    from tools.jd_indexer import embed_and_store_jd_chunks
    from tools.resume_parser import ResumeParser
    from tools.scraper.jd_analyzer_enhanced import JDAnalyzerEnhanced
    from database.classifier import Classifier

    render_top_nav()
    st.header("修改已有简历")
    st.caption("上传简历和目标 JD，先看匹配度，再生成优化简历和 Cover Letter。")

    if not require_services():
        return

    st.divider()

    step1, step2, step3 = st.columns(3)
    step1.markdown('<span class="step-pill">1 上传简历</span>', unsafe_allow_html=True)
    step2.markdown('<span class="step-pill">2 上传 / 选择 JD</span>', unsafe_allow_html=True)
    step3.markdown('<span class="step-pill">3 匹配分析</span>', unsafe_allow_html=True)

    with st.expander("1. 上传并解析简历", expanded=st.session_state.resume_data is None):
        uploaded_resume = st.file_uploader("上传简历文件", type=["pdf", "docx", "md", "txt"], key="fb_resume_upload")
        if uploaded_resume and st.button("解析简历", type="primary"):
            temp_dir = PROJECT_ROOT / "data" / "temp"
            temp_dir.mkdir(parents=True, exist_ok=True)
            temp_path = temp_dir / uploaded_resume.name
            temp_path.write_bytes(uploaded_resume.getbuffer())
            with st.spinner("正在解析简历..."):
                parser = ResumeParser(llm_client=st.session_state.llm_client)
                resume_data = run_async(parser.parse(str(temp_path)))
                st.session_state.resume_data = resume_data
                st.session_state.resume_id = st.session_state.db.insert_resume(
                    resume_to_db_payload(resume_data, current_user_id())
                )
                log_action(
                    st.session_state.db,
                    user_id=current_user_id(),
                    action="resume.create",
                    target_table="resumes",
                    target_id=st.session_state.resume_id,
                    details={"flow": "b", "source": uploaded_resume.name},
                )
                st.success("简历解析完成。")
        if st.session_state.resume_data:
            st.json(st.session_state.resume_data, expanded=False)

        with st.expander("从简历库选择"):
            from services.resume_library_service import list_resumes_flat
            saved = list_resumes_flat(st.session_state.db, current_user_id())
            if not saved:
                st.info("简历库为空，请先上传并保存简历。")
            else:
                opts = {f"{r['name']}（v{r.get('version',1)}·{r.get('updated_at','')[:10]}）": r["id"] for r in saved}
                selected_label = st.selectbox("选择简历版本", list(opts.keys()), key="fb_lib_resume_sel")
                if selected_label and st.button("加载到当前会话", key="fb_load_lib_resume"):
                    rid = opts[selected_label]
                    row = st.session_state.db.get_resume(rid)
                    if row:
                        st.session_state.resume_data = _db_resume_to_resume_data(row)
                        st.session_state.resume_id = rid
                        st.rerun()
                st.caption("注意：从库加载会覆盖当前会话中的简历内容。")

    with st.expander("2. 上传 / 选择目标 JD", expanded=st.session_state.resume_data is not None and st.session_state.jd_result is None):
        input_type = st.radio("JD 来源", ["粘贴 JD", "上传 PDF", "从 JD库选择", "职位 URL"], horizontal=True, key="fb_jd_input_type_radio")
        if input_type == "粘贴 JD":
            jd_text = st.text_area("粘贴目标 JD", height=220)
            if st.button("分析并保存 JD", disabled=not jd_text):
                with st.spinner("正在分析 JD..."):
                    analyzer = JDAnalyzerEnhanced(llm_client=st.session_state.llm_client)
                    jd_result = run_async(analyzer.parse_from_text(jd_text))
                    jd_payload = jd_to_db_payload(jd_text, jd_result, current_user_id(), source="manual")
                    jd_id = insert_user_jd(st.session_state.db, current_user_id(), jd_payload)
                    embed_and_store_jd_chunks(st.session_state.db, jd_id, jd_text, user_id=current_user_id())
                    log_action(
                        st.session_state.db,
                        user_id=current_user_id(),
                        action="jd.create",
                        target_table="jds",
                        target_id=jd_id,
                        details={"flow": "b", "source": "manual"},
                    )
                    st.session_state.jd_result = jd_result
                    st.session_state.jd_id = jd_id
                    st.success("JD 已分析并保存到 JD库。")
        elif input_type == "上传 PDF":
            uploaded_pdf = st.file_uploader("上传 JD PDF", type=["pdf"], key="fb_jd_pdf")
            if uploaded_pdf and st.button("解析 PDF JD"):
                upload_dir = PROJECT_ROOT / "data" / "uploads"
                upload_dir.mkdir(parents=True, exist_ok=True)
                pdf_path = upload_dir / uploaded_pdf.name
                pdf_path.write_bytes(uploaded_pdf.getbuffer())
                with st.spinner("正在解析 PDF JD..."):
                    jd_id = PdfIngestionService(db=st.session_state.db, classifier=Classifier()).ingest(
                        str(pdf_path), user_id=current_user_id(),
                    )
                    log_action(
                        st.session_state.db,
                        user_id=current_user_id(),
                        action="jd.create",
                        target_table="jds",
                        target_id=jd_id,
                        details={"flow": "b", "source": "pdf", "file": uploaded_pdf.name},
                    )
                    jd = st.session_state.db.get_jd(jd_id)
                    st.session_state.jd_id = jd_id
                    st.session_state.jd_result = {
                        "title": jd.get("title", ""),
                        "company": jd.get("company", ""),
                        "location": jd.get("location", ""),
                        "core_requirements": jd.get("parsed_sections", {}).get("requirements", []),
                        "keywords": jd.get("tags", []),
                        "raw_text": jd.get("raw_text", ""),
                    }
                    st.success("PDF JD 已入库。")
        elif input_type == "从 JD库选择":
            jd_search = st.text_input("搜索 JD库", placeholder="职位、公司、关键词", key="flow_b_jd_search")
            total = count_visible_jds(st.session_state.db, current_user_id(), search=jd_search or None)
            page_size = st.session_state.flow_b_jd_page_size
            max_page = max(1, (total + page_size - 1) // page_size)
            st.session_state.flow_b_jd_page = min(st.session_state.flow_b_jd_page, max_page)
            p1, p2, p3 = st.columns([1, 1, 2])
            with p1:
                if st.button("上一页", disabled=st.session_state.flow_b_jd_page <= 1, key="fb_jd_prev"):
                    st.session_state.flow_b_jd_page -= 1
                    st.rerun()
            with p2:
                if st.button("下一页", disabled=st.session_state.flow_b_jd_page >= max_page, key="fb_jd_next"):
                    st.session_state.flow_b_jd_page += 1
                    st.rerun()
            with p3:
                st.caption(f"共 {total} 条 · 第 {st.session_state.flow_b_jd_page}/{max_page} 页")
            rows = list_visible_jds(
                st.session_state.db,
                current_user_id(),
                search=jd_search or None,
                limit=page_size,
                offset=(st.session_state.flow_b_jd_page - 1) * page_size,
            )
            options = {f"{r.get('title') or '未命名'} @ {r.get('company') or '未知公司'} ({r.get('source')})": r["id"] for r in rows}
            selected = st.selectbox("选择 JD", list(options.keys()) if options else ["JD库暂无内容"])
            if options and st.button("使用这个 JD"):
                jd = get_visible_jd(st.session_state.db, current_user_id(), options[selected])
                st.session_state.jd_id = jd["id"]
                st.session_state.jd_result = {
                    "title": jd.get("title", ""),
                    "company": jd.get("company", ""),
                    "location": jd.get("location", ""),
                    "core_requirements": jd.get("parsed_sections", {}).get("requirements", []),
                    "keywords": jd.get("tags", []),
                    "raw_text": jd.get("raw_text", ""),
                }
                st.success("已选择 JD。")
        else:
            jd_url = st.text_input("职位 URL")
            if st.button("从 URL 分析 JD", disabled=not jd_url):
                with st.spinner("正在抓取并分析 JD..."):
                    analyzer = JDAnalyzerEnhanced(llm_client=st.session_state.llm_client)
                    jd_result = run_async(analyzer.parse_from_url(jd_url))
                    raw_text = jd_result.get("raw_text", jd_url)
                    jd_payload = jd_to_db_payload(raw_text, jd_result, current_user_id(), source="url")
                    jd_payload["url"] = jd_url
                    jd_id = insert_user_jd(st.session_state.db, current_user_id(), jd_payload)
                    embed_and_store_jd_chunks(st.session_state.db, jd_id, raw_text, user_id=current_user_id())
                    log_action(
                        st.session_state.db,
                        user_id=current_user_id(),
                        action="jd.create",
                        target_table="jds",
                        target_id=jd_id,
                        details={"flow": "b", "source": "url", "url": jd_url[:200]},
                    )
                    st.session_state.jd_result = jd_result
                    st.session_state.jd_id = jd_id
                    st.success("JD 已分析并保存。")
        if st.session_state.jd_result:
            st.json(st.session_state.jd_result, expanded=False)

    with st.expander("3. 匹配度分析", expanded=st.session_state.resume_data is not None and st.session_state.jd_result is not None):
        if st.button("分析匹配度", type="primary", disabled=not st.session_state.resume_data or not st.session_state.jd_result):
            with st.spinner("正在分析匹配度..."):
                agent = st.session_state.agent
                agent.state["resume_data"] = st.session_state.resume_data
                agent.state["jd_result"] = st.session_state.jd_result
                result = run_async(agent._tool_analyze_match())
                match_result = result.get("match_result", result)
                st.session_state.match_result = match_result
                score = match_result.get("score", 0)
                st.session_state.last_match_score = score
                if st.session_state.resume_id and st.session_state.jd_id:
                    st.session_state.last_match_id = st.session_state.db.insert_match({
                        "user_id": current_user_id(),
                        "resume_id": st.session_state.resume_id,
                        "jd_id": st.session_state.jd_id,
                        "score": score,
                        "reasoning": match_result.get("reasoning", ""),
                        "matched_skills": match_result.get("matched_skills", []),
                        "missing_skills": match_result.get("missing_skills", []),
                        "gaps": match_result.get("gaps", []),
                        "recommendations": match_result.get("recommendations", []),
                        "skill_mapping": match_result.get("skill_mapping", []),
                    })
                    log_action(
                        st.session_state.db,
                        user_id=current_user_id(),
                        action="match.create",
                        target_table="match_history",
                        target_id=st.session_state.last_match_id,
                        details={"score": score, "resume_id": st.session_state.resume_id, "jd_id": st.session_state.jd_id},
                    )
                    opt_ids = []
                    for rec in match_result.get("recommendations", []):
                        opt_ids.append(st.session_state.db.insert_optimization({
                            "user_id": current_user_id(),
                            "resume_id": st.session_state.resume_id,
                            "jd_id": st.session_state.jd_id,
                            "optimization_type": rec.get("type", "modify"),
                            "section": rec.get("section", ""),
                            "original_content": rec.get("original", ""),
                            "suggested_content": rec.get("suggestion", ""),
                            "reason": rec.get("reason", ""),
                        }))
                    if opt_ids:
                        log_action(
                            st.session_state.db,
                            user_id=current_user_id(),
                            action="optimization.create",
                            target_table="optimizations",
                            target_id=opt_ids[0],
                            details={"count": len(opt_ids), "match_id": st.session_state.last_match_id},
                        )
                    st.session_state.last_opt_ids = opt_ids
                st.success("匹配分析完成。")
        if st.session_state.match_result:
            match = st.session_state.match_result
            st.metric("匹配度", f"{match.get('score', 0)}%")
            if match.get("reasoning"):
                st.write(match["reasoning"])
            if match.get("matched_skills"):
                st.markdown("**已匹配技能**")
                st.write("、".join(match["matched_skills"]))
            if match.get("missing_skills"):
                st.markdown("**缺失技能**")
                st.write("、".join(match["missing_skills"]))
            if match.get("recommendations"):
                st.markdown("**优化建议**")
                for rec in match["recommendations"]:
                    st.markdown(f"- **{rec.get('section', '')}**：{rec.get('reason') or rec.get('suggestion', '')}")

    render_generation_toolbar()
    st.divider()
    st.session_state.flow_b_company_name = st.text_input("目标公司名（用于 Cover Letter）", value=st.session_state.flow_b_company_name or (st.session_state.jd_result or {}).get("company", ""))
    if st.session_state.optimized_resume:
        st.markdown("### 优化后简历")
        st.markdown(st.session_state.optimized_resume)
        st.download_button("下载优化简历 Markdown", st.session_state.optimized_resume, file_name="optimized_resume.md", mime="text/markdown")
        if st.session_state.optimized_resume_html:
            st.download_button("下载优化简历 HTML", st.session_state.optimized_resume_html, file_name="optimized_resume.html", mime="text/html")
    if st.session_state.cover_letter:
        st.markdown("### Cover Letter")
        st.markdown(st.session_state.cover_letter)
        st.download_button("下载 Cover Letter", st.session_state.cover_letter, file_name="cover_letter.txt", mime="text/plain")


def main() -> None:
    init_session_state()
    init_app_services()
    render_flow_b()


if __name__ == "__main__":
    main()
