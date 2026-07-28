#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""M-v4-1 web_app 拆分 — Flow A 第 3 步（改写）+ 第 4 步（预览）+ 第 5 步（导出）。

来源：web_app.py 原 render_flow_a_step_3_rewrite + render_flow_a_step_4_preview +
render_flow_a_step_5_export + 私有 helpers（_score_resume / _compose_final_resume /
_render_rewrite_results / _estimate_resume / _render_one_page_estimate /
_handle_export / _offer_html_fallback）。

三步合并到一个 page（用户在 Streamlit 5-step 状态机里顺序前进）；
Streamlit multipage 自动识别 → sidebar 出现 "💬 Flow A Step3" 入口。

拆分原因：step3/4/5 共享 fa_step3_rewrites / fa_step3_final_resume / fa_step3_mode 等
session_state，强行拆 3 个 page 会让用户跨 page 切换时 state 丢失（且 dispatcher
逻辑要求按 fa_step 决定渲染哪个）。
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st  # noqa: E402

from web_app import (  # noqa: E402
    init_session_state,
    init_app_services,
    render_top_nav,
    run_async,
    reset_flow_a_state,
    _sync_flow_a_position_from_jd,
)

st.set_page_config(
    page_title="JobHunter · Flow A Step 3",
    page_icon="💬",
    layout="wide",
    initial_sidebar_state="collapsed",
)


# ---------------------------------------------------------------------------
# Private helpers（原文搬迁）
# ---------------------------------------------------------------------------


def step2_form_to_resume(form: Dict[str, Any]) -> Dict[str, Any]:
    """Step 2 表单 → Resume dict（与 04 page 同源；这里 1:1 复制以避免跨 page import）。

    字段对齐 models.resume.py:ResumeProfile + update_plan §1.1。
    """
    basic = form.get("basic") or {}
    return {
        "name": basic.get("name", ""),
        "phone": basic.get("phone", ""),
        "email": basic.get("email", ""),
        "location": basic.get("location", ""),
        "target_roles": [basic.get("target_role", "")] if basic.get("target_role") else [],
        "summary": "",
        "experience": [
            {
                "company": w.get("company", ""),
                "title": w.get("title", ""),
                "start_date": w.get("start_date", ""),
                "end_date": w.get("end_date", ""),
                "description": w.get("description", ""),
                "achievements": [
                    a.strip() for a in (w.get("achievements_text", "") or "").splitlines() if a.strip()
                ],
            }
            for w in (form.get("work") or [])
        ],
        "projects": [
            {
                "name": p.get("name", ""),
                "role": p.get("role", ""),
                "start_date": p.get("start_date", ""),
                "end_date": p.get("end_date", ""),
                "description": p.get("description", ""),
                "contribution": p.get("contribution", ""),
                "achievements": [
                    a.strip() for a in (p.get("achievements_text", "") or "").splitlines() if a.strip()
                ],
            }
            for p in (form.get("projects") or [])
        ],
        "education": [
            {k: edu.get(k, "") for k in ("school", "degree", "major", "start_year", "end_year", "gpa")}
            for edu in (form.get("education") or [])
        ],
        "skills": [s.strip() for s in (form.get("skills_text", "") or "").replace("\n", ",").split(",") if s.strip()],
        "certifications": [s.strip() for s in (form.get("certifications_text", "") or "").split(",") if s.strip()],
        "languages": [s.strip() for s in (form.get("languages_text", "") or "").split(",") if s.strip()],
        "portfolio": form.get("portfolio", ""),
    }


def _score_resume(resume: Dict[str, Any]) -> Dict[str, Any]:
    """调 round-1 InformationScorer。LLM 客户端未配置时返回 0 分。"""
    try:
        from services.information_scorer import InformationScorer
        scorer = InformationScorer()
        score = scorer.score(resume)
        return {
            "total_score": float(getattr(score, "total_score", 0)),
            "recommended_mode": str(getattr(score, "recommended_mode", "B")),
            "reason": str(getattr(score, "reason", "无评分信息")),
        }
    except Exception:
        return {"total_score": 0.0, "recommended_mode": "B", "reason": "评分失败，默认 B"}


def _compose_final_resume(
    resume: Dict[str, Any], result: Any, form: Dict[str, Any],
) -> Dict[str, Any]:
    """把改写结果合并进简历 dict（下游 Step 4/5 用）。"""
    out = dict(resume)
    rewrites = result.rewrites if hasattr(result, "rewrites") else result.get("rewrites", [])
    # 模式 A：每段含 section / original / rewritten → 用 rewritten 替换
    # 模式 B：每段含 section / content → 用 content 当作追加段
    out["_rewrites"] = list(rewrites)
    out["_rewrite_mode"] = getattr(result, "mode", "A")
    return out


def _render_rewrite_results(rewrites_dict: Dict[str, Any]) -> None:
    """展示改写结果（模式 A 段 vs 模式 B 段视觉区分）。"""
    rewrites = rewrites_dict.get("rewrites") or []
    mode = rewrites_dict.get("mode", "A")
    warnings = rewrites_dict.get("warnings") or []
    needs_review = rewrites_dict.get("needs_user_review", False)

    if warnings:
        with st.expander(f"⚠️ 警告（{len(warnings)} 条）", expanded=False):
            for w in warnings:
                st.warning(f"· {w}")

    if needs_review:
        st.caption("📝 改写结果需要人工校对（每段都附改写理由）。")

    for i, rw in enumerate(rewrites):
        section = rw.get("section") or f"段 {i + 1}"
        original = rw.get("original") or ""
        rewritten = rw.get("rewritten") or rw.get("content") or ""
        reason = rw.get("rewrite_reason") or ""
        warn = rw.get("warning") or ""
        is_ai = bool(rw.get("is_ai_generated", False)) or mode == "B"

        if is_ai:
            st.markdown(
                f'<div style="border:2px dashed #d97706;background:#fffbeb;'
                f'padding:12px;margin:8px 0;border-radius:6px;color:#92400e">'
                f'<strong>⚠️ [AI 模板生成] · {section}</strong><br/>'
                f'{rewritten}<br/>'
                f'<small>anchored_keywords: {rw.get("anchored_keywords") or "-"}</small>'
                f'<br/><em>AI 虚构，不带公司名/时间/学校，请结合自身情况填写</em>'
                f'</div>',
                unsafe_allow_html=True,
            )
        else:
            with st.expander(f"✏️ {section}", expanded=False):
                if original:
                    st.markdown("**原**")
                    st.markdown(f"> {original}")
                st.markdown("**改写**")
                st.markdown(rewritten)
                if reason:
                    st.caption(f"💡 改写理由：{reason}")
                if warn:
                    st.caption(f"⚠️ 风险：{warn}")


def _estimate_resume(resume: Dict[str, Any]) -> Any:
    """调 round-1 OnePageEstimator。"""
    try:
        from services.one_page_estimator import OnePageEstimator
        estimator = OnePageEstimator()
        return estimator.estimate(resume)
    except Exception as exc:
        # 估算失败不阻塞主流程，返回一个 fallback PageEstimate
        from services.one_page_estimator import PageEstimate
        return PageEstimate(
            total_mm=0.0, capacity_mm=265.0, total_lines=0, capacity_lines=55,
            overflow=False, overflow_segments=[], suggestions=[f"估算失败：{exc}"],
            segment_lines={},
        )


def _render_one_page_estimate(estimate: Any) -> None:
    """渲染一页纸预估：进度条 + 段行数 + 瘦身建议。"""
    total = float(getattr(estimate, "total_mm", 0.0))
    cap = float(getattr(estimate, "capacity_mm", 265.0))
    overflow = bool(getattr(estimate, "overflow", False))
    pct = min(1.0, total / cap) if cap > 0 else 0.0

    if overflow:
        st.error(f"⚠️ 超页：{total:.1f}mm / {cap}mm（已用 {pct * 100:.0f}%）")
    else:
        st.success(f"✓ 一页可容纳：{total:.1f}mm / {cap}mm（已用 {pct * 100:.0f}%）")
    st.progress(pct)

    seg_lines = getattr(estimate, "segment_lines", {}) or {}
    if seg_lines:
        with st.expander(f"段行数明细（共 {sum(seg_lines.values())} 行）", expanded=False):
            for k, v in seg_lines.items():
                st.write(f"- {k}: {v} 行")

    suggestions = list(getattr(estimate, "suggestions", []) or [])
    overflow_segments = list(getattr(estimate, "overflow_segments", []) or [])
    if suggestions:
        st.markdown("##### 瘦身建议")
        for s in suggestions:
            st.markdown(f"- 💡 {s}")
    if overflow_segments:
        st.warning(f"超页段：{', '.join(overflow_segments)}")


def _handle_export(ext: str, resume: Any, jd: Any, template: str) -> None:
    """调 document_generator，渲染并展示下载按钮。

    P0-1 闭环：PDF 路径失败时降级到 HTML 下载 + 浏览器打印指引。
    """
    try:
        from services.document_generator import DocumentGenerator
        gen = DocumentGenerator()
        method = gen.generate_word if ext == "docx" else gen.generate_pdf
        result = method(resume, jd=jd, template=template, strict_one_page=True)
        st.success(
            f"✅ {ext.upper()} 已生成：{result.filename}（{len(result.content)} bytes）"
        )
        st.download_button(
            label=f"下载 {result.filename}",
            data=result.content,
            file_name=result.filename,
            mime=result.mime_type,
            key=f"fa_step5_dl_{ext}_{len(result.content)}",
        )
    except Exception as exc:
        if ext == "pdf":
            _offer_html_fallback(resume, jd, template, error=str(exc))
        else:
            st.error(f"导出失败：{exc}")


def _offer_html_fallback(
    resume: Any, jd: Any, template: str, error: Optional[str] = None,
) -> None:
    """P0-1 闭环：PDF 不可用时给用户 HTML 下载 + 浏览器打印指引。"""
    from services.document_generator import DocumentGenerator, suggest_filename
    gen = DocumentGenerator()
    resume_d = gen._to_dict(resume)
    jd_d = gen._to_dict(jd) if jd is not None else {}
    try:
        html_bytes = gen._render_html(resume_d, jd_d, template, for_pdf=True).encode("utf-8")
    except Exception as exc:
        st.error(f"HTML 渲染也失败（极端情况）：{exc}")
        return

    jd_title = jd_d.get("title", "岗位") if jd_d else "通用岗位"
    company = jd_d.get("company", "公司") if jd_d else "公司"
    html_name = suggest_filename(
        name=resume_d.get("name", "简历"),
        jd_title=jd_title,
        company=company,
        ext="html",
    )
    if error:
        st.warning(
            f"⚠️ PDF 渲染失败（{error}）→ 降级到 **HTML + 浏览器打印** 方案"
        )
    else:
        st.info("📄 提供 HTML 下载（浏览器打开后用 Ctrl/Cmd+P 另存为 PDF）")

    st.download_button(
        label=f"下载 {html_name}",
        data=html_bytes,
        file_name=html_name,
        mime="text/html",
        key=f"fa_step5_dl_html_{len(html_bytes)}",
    )
    with st.expander("💡 浏览器打印 PDF 步骤", expanded=True):
        st.markdown(
            "1. 用浏览器打开下载的 HTML 文件\n"
            "2. 按 **Ctrl/Cmd + P** 打开打印对话框\n"
            "3. 目标选 **另存为 PDF**\n"
            "4. 边距选 **最小**（保证一页纸）\n"
            "5. 缩放 100%，点保存\n"
        )


# ---------------------------------------------------------------------------
# Step 3 — 改写 / 生成
# ---------------------------------------------------------------------------


def render_flow_a_step_3_rewrite() -> None:
    """v3 Step 3: 模式 A/B/auto 切换器 + 改写结果展示。"""
    form = st.session_state.get("fa_step2_form")
    jd = st.session_state.get("fa_jd_structured")
    if not form:
        st.warning("⚠️ 请先完成 Step 2 填写简历内容。")
        if st.button("返回 Step 2", key="fa_step3_back2"):
            st.session_state.fa_step = 2
            st.rerun()
        return
    if not jd:
        st.warning("⚠️ 请先完成 Step 1 选择目标 JD。")
        if st.button("返回 Step 1", key="fa_step3_back1"):
            st.session_state.fa_step = 1
            st.rerun()
        return

    st.markdown('<span class="step-pill">第 3 步</span>改写 / 生成', unsafe_allow_html=True)
    target = (jd or {}).get("title") or "（未选岗位）"
    st.caption(f"目标岗位：{target} — 选择改写模式，AI 会按你的原简历 + 目标 JD 改写。")

    if st.button("← 返回 Step 2 改简历内容", key="fa_step3_back"):
        st.session_state.fa_step = 2
        st.rerun()

    resume = step2_form_to_resume(form)
    score = _score_resume(resume)
    auto_mode = score["recommended_mode"]
    st.info(
        f"📊 **信息量评估**：{score['total_score']:.0f}/100 → "
        f"auto 推荐 **模式 {auto_mode}**（{score['reason']}）"
    )

    mode_choice = st.radio(
        "改写模式",
        options=["auto", "A", "B"],
        format_func=lambda m: {
            "auto": f"auto（推荐 {auto_mode}）",
            "A": "模式 A — 基于原简历改写（不编造数据）",
            "B": "模式 B — AI 生成模板（不带公司名/时间）",
        }[m],
        index=0,
        horizontal=True,
        key="fa_step3_mode_choice",
    )

    rewrites = st.session_state.get("fa_step3_rewrites")
    last_mode = st.session_state.get("fa_step3_mode")
    first_run = st.session_state.get("fa_step3_first_run", True)

    if first_run:
        run_label = "🚀 改写 / 生成"
        run_help = "首次跑改写（用上方 auto / A / B 选择）"
    else:
        target_mode = auto_mode if mode_choice == "auto" else mode_choice
        if last_mode and target_mode != last_mode:
            run_label = f"🔁 切换为 模式 {target_mode} 重跑"
            run_help = f"上次跑的是模式 {last_mode}，这次按你的选择切到 {target_mode} 重跑"
        else:
            run_label = f"🔁 用 模式 {target_mode} 重跑"
            run_help = f"上次已经跑过模式 {last_mode or target_mode}，按相同模式再跑一遍"

    col_run, col_next = st.columns([1, 1])
    with col_run:
        run_clicked = st.button(
            run_label,
            type="primary",
            key="fa_step3_run",
            help=run_help,
        )
    with col_next:
        next_disabled = not rewrites
        if st.button(
            "下一步：预览与导出 →", disabled=next_disabled, key="fa_step3_next",
        ):
            st.session_state.fa_step = 4
            st.rerun()

    if run_clicked:
        actual_mode = auto_mode if mode_choice == "auto" else mode_choice
        with st.spinner(
            f"模式 {actual_mode} 改写中…（约 5-15s）"
        ):
            try:
                from services.resume_rewriter import ResumeRewriter
                rewriter = ResumeRewriter(
                    llm_client=st.session_state.get("llm_client"),
                )
                result = run_async(rewriter.rewrite(
                    original=resume,
                    jd=jd,
                    mode="auto" if mode_choice == "auto" else mode_choice,
                ))
                st.session_state.fa_step3_rewrites = result.to_dict()
                st.session_state.fa_step3_mode = result.mode
                st.session_state.fa_step3_first_run = False
                st.session_state.fa_step3_final_resume = _compose_final_resume(
                    resume, result, form,
                )
                st.success(f"✅ 模式 {result.mode} 改写完成（{len(result.rewrites)} 段）")
            except Exception as exc:
                st.error(f"改写失败：{exc}")
                return

    if rewrites:
        _render_rewrite_results(rewrites)


# ---------------------------------------------------------------------------
# Step 4 — 一页纸预览
# ---------------------------------------------------------------------------


def render_flow_a_step_4_preview() -> None:
    """v3 Step 4: 一页纸实时预览 + 瘦身向导。"""
    form = st.session_state.get("fa_step2_form")
    final = st.session_state.get("fa_step3_final_resume")
    jd = st.session_state.get("fa_jd_structured")
    if not form or not final:
        st.warning("⚠️ 请先完成 Step 1-3。")
        if st.button("返回 Step 3", key="fa_step4_back3"):
            st.session_state.fa_step = 3
            st.rerun()
        return

    st.markdown('<span class="step-pill">第 4 步</span>一页纸预览 + 瘦身', unsafe_allow_html=True)
    st.caption("实时估算总高度，超页时按建议精简。")

    if st.button("← 返回 Step 3 改写", key="fa_step4_back"):
        st.session_state.fa_step = 3
        st.rerun()

    estimate = _estimate_resume(final)
    _render_one_page_estimate(estimate)

    if st.session_state.get("fa_step3_mode") == "B":
        st.caption("📌 模式 B 输出含 AI 模板生成标记")

    if st.button("下一步：导出 Word / PDF →", type="primary", key="fa_step4_next"):
        st.session_state.fa_step = 5
        st.rerun()


# ---------------------------------------------------------------------------
# Step 5 — 导出
# ---------------------------------------------------------------------------


def render_flow_a_step_5_export() -> None:
    """v3 Step 5: Word / PDF 导出。"""
    form = st.session_state.get("fa_step2_form")
    final = st.session_state.get("fa_step3_final_resume")
    jd = st.session_state.get("fa_jd_structured")
    if not form or not final:
        st.warning("⚠️ 请先完成 Step 1-4。")
        if st.button("返回 Step 4", key="fa_step5_back4"):
            st.session_state.fa_step = 4
            st.rerun()
        return

    st.markdown('<span class="step-pill">第 5 步</span>导出 Word / PDF', unsafe_allow_html=True)
    st.caption("文件名：{姓名}_{岗位}_{公司}.{ext}。超页会被拦截。")

    if st.button("← 返回 Step 4 预览", key="fa_step5_back"):
        st.session_state.fa_step = 4
        st.rerun()

    template = st.radio(
        "Word 模板",
        options=["conservative", "modern"],
        format_func=lambda t: {"conservative": "保守（经典灰）", "modern": "现代（蓝色头部栏）"}[t],
        horizontal=True,
        key="fa_step5_template",
    )

    estimate = _estimate_resume(final)
    if getattr(estimate, "overflow", False):
        st.error("⚠️ 当前简历超出一页纸，请先回 Step 4 瘦身。")
        if st.button("返回 Step 4 瘦身", key="fa_step5_overflow_back"):
            st.session_state.fa_step = 4
            st.rerun()
        return

    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("导出 Word (.docx)", type="primary", key="fa_step5_docx"):
            _handle_export("docx", final, jd, template)
    with col2:
        if st.button("导出 PDF", type="primary", key="fa_step5_pdf"):
            _handle_export("pdf", final, jd, template)
    with col3:
        if st.button("导出两者", type="primary", key="fa_step5_both"):
            _handle_export("docx", final, jd, template)
            _handle_export("pdf", final, jd, template)

    st.divider()
    if st.button("🔄 重新开始（清空当前流程）", key="fa_step5_reset"):
        reset_flow_a_state()
        st.rerun()


# ---------------------------------------------------------------------------
# Page entry — 按 fa_step dispatch
# ---------------------------------------------------------------------------


def main() -> None:
    init_session_state()
    init_app_services()
    _sync_flow_a_position_from_jd()
    render_top_nav()
    fa_step = st.session_state.get("fa_step", 1)
    if fa_step == 3:
        render_flow_a_step_3_rewrite()
    elif fa_step == 4:
        render_flow_a_step_4_preview()
    elif fa_step == 5:
        render_flow_a_step_5_export()
    else:
        st.warning("请先完成 Step 1 / 2；从 sidebar 进入对应页面。")


if __name__ == "__main__":
    main()
