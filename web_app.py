#!/usr/bin/env python3
"""
Job Hunter - 网页版 (Streamlit)
更直观、更漂亮地展示简历分析结果！
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st
import json
import asyncio
import re
from loguru import logger

from dotenv import load_dotenv
import os
load_dotenv()

# v2.1 P0.5: 首次运行配置向导（无 key 时阻断在 set_page_config 之前）
from setup_wizard import run_if_needed as _run_setup_wizard
_run_setup_wizard()

# v2.1 M1.5: 启用 loguru 滚动日志（20MB / 7 天）
from config.settings import settings
settings.setup_logging()

from tools.llm import OpenAICompatibleClient
from tools.resume_parser import ResumeParser
from tools.scraper.jd_analyzer_enhanced import JDAnalyzerEnhanced
from tools.scraper.scraper_manager import ScraperManager
from tools.generator.resume_generator import ResumeGenerator
from tools.generator.resume_optimizer import ResumeOptimizer
from tools.generator.cover_letter_generator import CoverLetterGenerator
from tools.knowledge_base import KnowledgeBase
from database.backends.sqlite_backend import SqliteBackend
from database.classifier import Classifier
from database.factory import get_db
from config.settings import settings
from agents.coordinator import CoordinatorAgent
from core.cache import Cache

# 页面配置
st.set_page_config(
    page_title="Job Hunter - 智能求职助手",
    page_icon="💼",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 自定义样式
st.markdown("""
<style>
    .main-header {
        font-size: 2.5rem;
        font-weight: bold;
        color: #1e3a8a;
        text-align: center;
        margin-bottom: 0.5rem;
    }
    .sub-header {
        font-size: 1.2rem;
        color: #64748b;
        text-align: center;
        margin-bottom: 2rem;
    }
    .section-card {
        background-color: #f8fafc;
        border-radius: 12px;
        padding: 1.5rem;
        margin-bottom: 1rem;
        border: 1px solid #e2e8f0;
    }
    .match-high {
        color: #059669;
        font-weight: bold;
        font-size: 1.5rem;
    }
    .match-medium {
        color: #d97706;
        font-weight: bold;
        font-size: 1.5rem;
    }
    .match-low {
        color: #dc2626;
        font-weight: bold;
        font-size: 1.5rem;
    }
    .skill-tag {
        display: inline-block;
        padding: 0.25rem 0.75rem;
        margin: 0.25rem;
        border-radius: 9999px;
        font-size: 0.9rem;
    }
    .skill-match {
        background-color: #dcfce7;
        color: #166534;
    }
    .skill-gap {
        background-color: #fee2e2;
        color: #991b1b;
    }
    .skill-neutral {
        background-color: #e0e7ff;
        color: #3730a3;
    }
    .divider {
        margin: 2rem 0;
        border-bottom: 2px solid #e2e8f0;
    }
</style>
""", unsafe_allow_html=True)

# 初始化 Session State
if 'agent' not in st.session_state:
    st.session_state.agent = None
if 'resume_data' not in st.session_state:
    st.session_state.resume_data = None
if 'resume_id' not in st.session_state:
    st.session_state.resume_id = None
if 'jd_result' not in st.session_state:
    st.session_state.jd_result = None
if 'jd_id' not in st.session_state:
    st.session_state.jd_id = None
if 'match_result' not in st.session_state:
    st.session_state.match_result = None
if 'last_match_id' not in st.session_state:
    st.session_state.last_match_id = None
if 'last_opt_ids' not in st.session_state:
    st.session_state.last_opt_ids = []  # v2.1 M2: 最近一次生成建议的 opt_id 列表
if 'optimized_resume' not in st.session_state:
    st.session_state.optimized_resume = None
if 'optimized_resume_html' not in st.session_state:
    st.session_state.optimized_resume_html = None
if 'cover_letter' not in st.session_state:
    st.session_state.cover_letter = None
if 'kb' not in st.session_state:
    st.session_state.kb = KnowledgeBase()
if 'current_db' not in st.session_state:
    st.session_state.current_db = "AI产品经理"
    st.session_state.kb.switch_database("AI产品经理")
if 'auto_save' not in st.session_state:
    st.session_state.auto_save = True
if 'scraper_manager' not in st.session_state:
    st.session_state.scraper_manager = None
if 'db' not in st.session_state:
    st.session_state.db = SqliteBackend(db_path=settings.db_path)

# P2-3 Flow A 状态
if 'fa_industry' not in st.session_state:
    st.session_state.fa_industry = None
if 'fa_function' not in st.session_state:
    st.session_state.fa_function = None
if 'fa_position' not in st.session_state:
    st.session_state.fa_position = None
if 'fa_messages' not in st.session_state:
    st.session_state.fa_messages = []  # [{role, content}]
if 'fa_chat_done' not in st.session_state:
    st.session_state.fa_chat_done = False
if 'fa_resume_data' not in st.session_state:
    st.session_state.fa_resume_data = None
if 'fa_resume_md' not in st.session_state:
    st.session_state.fa_resume_md = None
if 'fa_resume_html' not in st.session_state:
    st.session_state.fa_resume_html = None

# 侧边栏
with st.sidebar:
    st.markdown("## 💼 Job Hunter")
    st.markdown("### 智能求职助手")
    st.divider()

    st.markdown("### 🔧 设置")

    api_key = st.text_input("LLM API Key", type="password", value=os.getenv("LLM_API_KEY", ""))
    api_url = st.text_input("API Base URL", value=os.getenv("LLM_BASE_URL", "https://apihub.agnes-ai.com/v1"))
    model = st.text_input("模型", value=os.getenv("LLM_MODEL", "agnes-2.0-flash"))
    use_anthropic_format = st.checkbox("使用 Anthropic 格式", value=os.getenv("LLM_USE_ANTHROPIC_FORMAT", "false").lower() == "true")

    col1, col2 = st.columns(2)
    with col1:
        if st.button("初始化 Agent", type="primary"):
            try:
                with st.spinner("正在初始化 Agent..."):
                    llm_client = OpenAICompatibleClient(
                        api_key=api_key,
                        api_url=api_url.rstrip('/'),
                        model=model,
                        is_coding_api=False,
                        use_anthropic_format=True
                    )
                    st.session_state.agent = CoordinatorAgent(llm_client=llm_client)
                    # 给知识库也设置LLM客户端
                    st.session_state.kb.set_llm_client(llm_client)
                    # 初始化爬虫管理器
                    st.session_state.scraper_manager = ScraperManager(llm_client=llm_client)
                    st.success("✅ Agent 初始化成功！")
            except Exception as e:
                st.error(f"初始化失败: {e}")

    with col2:
        if st.button("测试 LLM 连接"):
            if not api_key:
                st.error("请先输入 API Key！")
            else:
                try:
                    with st.spinner("正在测试 LLM 连接..."):
                        llm_client = OpenAICompatibleClient(
                            api_key=api_key,
                            api_url=api_url.rstrip('/'),
                            model=model,
                            is_coding_api=False,
                            use_anthropic_format=True
                        )
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        from tools.llm import LLMMessage
                        messages = [LLMMessage(role="user", content="你好，请回复'连接成功'")]

                        # 重置统计
                        llm_client.reset_stats()

                        st.info(f"🔗 正在调用 API: {api_url}")
                        st.info(f"🤖 模型: {model}")
                        st.info(f"📝 格式: {'Anthropic' if use_anthropic_format else 'OpenAI'}")

                        response = loop.run_until_complete(llm_client.analyze(messages=messages, max_tokens=50))
                        loop.close()

                        st.success("✅ LLM 真实被调用！")
                        st.markdown(f"**响应内容**: {response.content[:200]}")

                        # 显示统计信息
                        stats = llm_client.get_stats()
                        st.info(f"📊 调用次数: {stats.get('total_calls', 0)}")
                        st.info(f"🎯 使用 Token: {stats.get('total_tokens', 0)}")
                        st.info(f"🤖 模型返回: {response.model}")

                except Exception as e:
                    st.error(f"❌ 连接失败: {e}")
                    import traceback
                    st.error(traceback.format_exc())

    st.divider()
    st.markdown("### 📚 知识库设置")

    # 数据库选择
    db_list = st.session_state.kb.list_databases()
    selected_db = st.selectbox(
        "选择数据库",
        db_list,
        index=db_list.index(st.session_state.current_db) if st.session_state.current_db in db_list else 0
    )
    if selected_db != st.session_state.current_db:
        st.session_state.current_db = selected_db
        st.session_state.kb.switch_database(selected_db)

    # 新数据库创建
    new_db_name = st.text_input("创建新数据库", placeholder="输入数据库名称...")
    if st.button("创建新库") and new_db_name:
        st.session_state.kb.create_database(new_db_name)
        st.session_state.current_db = new_db_name
        st.session_state.kb.switch_database(new_db_name)
        st.success(f"已创建并切换到: {new_db_name}")

    # 自动保存开关
    st.session_state.auto_save = st.checkbox(
        "自动保存到知识库",
        value=st.session_state.auto_save,
        help="分析JD后自动保存到当前数据库"
    )

    st.divider()
    st.markdown("### 📊 当前状态")
    if st.session_state.resume_data:
        st.success("✅ 简历已解析")
    if st.session_state.jd_result:
        st.success("✅ JD 已分析")
    if st.session_state.match_result:
        st.success("✅ 匹配度已分析")

    st.divider()
    if st.button("🔄 重置所有"):
        st.session_state.resume_data = None
        st.session_state.jd_result = None
        st.session_state.match_result = None
        st.session_state.optimized_resume = None
        st.session_state.cover_letter = None
        st.experimental_rerun()

# 主页面
st.markdown('<div class="main-header">💼 Job Hunter</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-header">智能求职助手 - 让找工作更简单</div>', unsafe_allow_html=True)

# 标签页（v2.1 M2: 新增 📈 投递历史；P2-3: 新增 ✨ 从零生成）
tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs([
    "📄 上传简历",
    "🎯 分析职位",
    "📊 匹配度分析",
    "🚀 生成优化内容",
    "📚 知识库",
    "📈 投递历史",
    "✨ 从零生成简历",
])

# =====================================================
# 标签页 1: 上传简历
# =====================================================
with tab1:
    st.header("上传简历")
    col1, col2 = st.columns([1, 1])

    with col1:
        uploaded_file = st.file_uploader("选择简历文件", type=["pdf", "docx", "md", "txt"])

        if uploaded_file is not None:
            # 保存临时文件
            temp_path = PROJECT_ROOT / "data" / "temp" / uploaded_file.name
            temp_path.parent.mkdir(exist_ok=True, parents=True)
            with open(temp_path, "wb") as f:
                f.write(uploaded_file.getvalue())

            st.info(f"✅ 文件已上传: {uploaded_file.name}")

            if st.button("解析简历", type="primary"):
                if not st.session_state.agent:
                    st.error("请先在侧边栏初始化 Agent！")
                else:
                    with st.spinner("正在解析简历..."):
                        try:
                            # v2.1 M2.5: 优先用 LLM 抽取，失败自动降级到正则
                            llm_client = st.session_state.agent.llm_client if st.session_state.agent else None
                            parser = ResumeParser(llm_client=llm_client)
                            loop = asyncio.new_event_loop()
                            asyncio.set_event_loop(loop)
                            resume_data = loop.run_until_complete(parser.parse(str(temp_path)))
                            loop.close()

                            st.session_state.resume_data = resume_data

                            # 持久化到数据库（v2.1 M2：保留 resume_id 供后续 match/optimization 关联）
                            db = st.session_state.db
                            resume_id = db.insert_resume(resume_data)
                            st.session_state.resume_id = resume_id
                            st.success(f"✅ 简历解析成功并已保存！(ID: {resume_id[:8]})")
                        except Exception as e:
                            st.error(f"解析失败: {e}")

    with col2:
        if st.session_state.resume_data:
            st.markdown("### 简历解析结果")

            rd = st.session_state.resume_data

            # 基本信息
            with st.expander("👤 基本信息", expanded=True):
                header = rd.get("header", {})
                st.write(f"**姓名**: {header.get('name', 'N/A')}")
                st.write(f"**邮箱**: {header.get('contact', {}).get('email', 'N/A')}")
                st.write(f"**电话**: {header.get('contact', {}).get('phone', 'N/A')}")
                st.write(f"**个人简介**: {header.get('summary', 'N/A')}")

            # 技能
            with st.expander("🛠️ 技能列表", expanded=True):
                skills = rd.get("skills", {})
                tech_skills = skills.get("technical", [])
                if tech_skills:
                    for skill in tech_skills:
                        st.markdown(f'<span class="skill-tag skill-neutral">{skill}</span>', unsafe_allow_html=True)

            # 工作经历
            with st.expander("💼 工作经历", expanded=True):
                exp = rd.get("experience", [])
                for job in exp:
                    st.markdown(f"**{job.get('company', 'N/A')}** - {job.get('title', 'N/A')}")
                    st.write(job.get('description', ''))
                    st.divider()

            # 教育经历
            with st.expander("🎓 教育经历", expanded=False):
                edu = rd.get("education", [])
                for school in edu:
                    st.markdown(f"**{school.get('school', 'N/A')}**")
                    st.write(f"{school.get('degree', '')} - {school.get('major', '')}")
                    st.divider()

# =====================================================
# 标签页 2: 分析职位
# =====================================================
with tab2:
    st.header("分析职位描述")

    input_type = st.radio("选择输入方式", ["直接粘贴 JD", "批量粘贴 JD", "上传 PDF 文件", "输入职位 URL"])

    if input_type == "直接粘贴 JD":
        jd_text = st.text_area("职位描述 (JD)", height=300, placeholder="请复制粘贴完整的职位描述...")

        if st.button("分析 JD", type="primary") and jd_text and st.session_state.agent:
            with st.spinner("正在分析职位描述..."):
                try:
                    llm_client = st.session_state.agent.llm_client
                    analyzer = JDAnalyzerEnhanced(llm_client=llm_client)

                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    jd_result = loop.run_until_complete(analyzer.parse_from_text(jd_text))

                    # 自动分类JD
                    classification = loop.run_until_complete(st.session_state.kb.classify_jd(jd_result))
                    loop.close()

                    st.session_state.jd_result = jd_result

                    # 持久化到数据库（含自动分类）
                    db = st.session_state.db
                    jd_for_db = {
                        "url": jd_result.get("_url", f"pasted://{len(jd_text)}chars"),
                        "title": jd_result.get("title", ""),
                        "company": jd_result.get("company", ""),
                        "location": jd_result.get("location", ""),
                        "salary_str": jd_result.get("salary_range"),
                        "raw_text": jd_text,
                        "source": "manual",
                        "requirements": jd_result.get("core_requirements", []),
                        "preferred_requirements": jd_result.get("preferred_requirements", []),
                        "skills_required": jd_result.get("keywords", []),
                        "implicit_requirements": jd_result.get("implicit_requirements", ""),
                        "parsed_data": jd_result,
                    }
                    from database.classifier import Classifier
                    clf = Classifier()
                    tags = clf.classify(jd_for_db["title"], jd_text)
                    jd_for_db.update(tags)
                    jd_id = db.insert_jd(jd_for_db)
                    st.session_state.jd_id = jd_id  # v2.1 M2: 供 Tab3 写 match_history

                    # v2.1 M3.4: JD 入库后语义切分 + 向量化
                    try:
                        from tools.jd_indexer import embed_and_store_jd_chunks
                        n_chunks = embed_and_store_jd_chunks(db, jd_id, jd_text)
                        if n_chunks:
                            st.caption(f"🧩 已切分 {n_chunks} 个语义 chunk 并向量化")
                    except Exception as _ex:
                        st.caption(f"⚠️ 向量化失败：{_ex}")

                    # 显示分类结果
                    st.info(f"📋 自动分类: **{classification['category']}** (置信度: {int(classification['confidence']*100)}%)")
                    if classification['reasoning']:
                        st.caption(f"理由: {classification['reasoning']}")

                    # 自动切换数据库并保存
                    if st.session_state.auto_save:
                        kb = st.session_state.kb
                        kb.switch_database(classification['category'])
                        st.session_state.current_db = classification['category']

                        jd_id = kb.add_jd({
                            "raw_text": jd_text,
                            "parsed_data": jd_result,
                            "source": "manual"
                        })
                        st.success(f"✅ JD 分析成功！已保存到「{classification['category']}」(ID: {jd_id})")
                    else:
                        st.success("✅ JD 分析成功！")
                except Exception as e:
                    st.error(f"分析失败: {e}")

    elif input_type == "批量粘贴 JD":
        # v2.1 M6.A.2: 批量预览/确认
        st.markdown(
            "一次粘贴多条 JD，**用 `---` 或连续空行分隔**。"
            "下一行会解析出列表预览，可勾选后批量保存（自动跑分类 + 切分 + 向量化）。"
        )
        batch_text = st.text_area(
            "批量 JD（多条）", height=300,
            placeholder="JD 1...\n\n---\n\nJD 2...\n\n---\n\nJD 3...",
            key="batch_jd_input",
        )

        # 切分：先按 --- 分，再按 2+ 连续空行兜底
        def _split_batch(raw: str):
            if not raw or not raw.strip():
                return []
            parts = [p.strip() for p in re.split(r"^\s*---+\s*$", raw, flags=re.MULTILINE) if p.strip()]
            if len(parts) <= 1:
                parts = [p.strip() for p in re.split(r"\n\s*\n\s*\n+", raw) if p.strip()]
            return parts

        if st.button("预览解析", key="batch_preview_btn") and batch_text:
            pieces = _split_batch(batch_text)
            if not pieces:
                st.warning("未检测到有效 JD，请确认用 `---` 或两空行分隔。")
            else:
                st.session_state["batch_pieces"] = pieces
                st.success(f"已切出 {len(pieces)} 条 JD，下方可勾选保存。")

        pieces = st.session_state.get("batch_pieces") or []
        if pieces:
            st.markdown(f"### 预览（{len(pieces)} 条）")
            cols = st.columns([1, 6])
            with cols[0]:
                if st.button("全选", key="batch_sel_all"):
                    st.session_state["batch_sel"] = list(range(len(pieces)))
                if st.button("反选", key="batch_sel_inv"):
                    cur = set(st.session_state.get("batch_sel", []))
                    st.session_state["batch_sel"] = [i for i in range(len(pieces)) if i not in cur]
            selected = []
            for i, p in enumerate(pieces):
                preview = p[:120].replace("\n", " ")
                if len(p) > 120:
                    preview += "…"
                with cols[1]:
                    chk = st.checkbox(f"#{i+1}  {preview}", key=f"batch_chk_{i}")
                if chk:
                    selected.append(i)
            st.session_state["batch_sel"] = selected

            if st.button("💾 批量保存", type="primary", key="batch_save_btn"):
                if not selected:
                    st.warning("请至少勾选一条 JD。")
                else:
                    db = st.session_state.db
                    llm_client = st.session_state.agent.llm_client if st.session_state.agent else None
                    analyzer = JDAnalyzerEnhanced(llm_client=llm_client) if llm_client else None
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    from database.classifier import Classifier as _Bclf
                    bclf = _Bclf()
                    ok, fail = 0, 0
                    progress = st.progress(0.0)
                    for idx, i in enumerate(selected):
                        jd_text_i = pieces[i]
                        try:
                            jd_for_db = {
                                "url": f"pasted://batch/{i}/{len(jd_text_i)}chars",
                                "title": "",
                                "company": "",
                                "raw_text": jd_text_i,
                                "source": "manual_batch",
                            }
                            if analyzer is not None:
                                try:
                                    jd_result = loop.run_until_complete(analyzer.parse_from_text(jd_text_i))
                                    jd_for_db.update({
                                        "title": jd_result.get("title", ""),
                                        "company": jd_result.get("company", ""),
                                        "location": jd_result.get("location", ""),
                                        "salary_str": jd_result.get("salary_range"),
                                        "requirements": jd_result.get("core_requirements", []),
                                        "preferred_requirements": jd_result.get("preferred_requirements", []),
                                        "skills_required": jd_result.get("keywords", []),
                                        "implicit_requirements": jd_result.get("implicit_requirements", ""),
                                        "parsed_data": jd_result,
                                    })
                                except Exception as _ae:
                                    st.caption(f"⚠️ #{i+1} LLM 解析失败，仅按 raw_text 入库：{_ae}")
                            tags = bclf.classify(jd_for_db["title"], jd_text_i)
                            jd_for_db.update(tags)
                            jid = db.insert_jd(jd_for_db)
                            try:
                                from tools.jd_indexer import embed_and_store_jd_chunks
                                embed_and_store_jd_chunks(db, jid, jd_text_i)
                            except Exception as _ie:
                                st.caption(f"⚠️ #{i+1} 向量化失败：{_ie}")
                            ok += 1
                        except Exception as e:
                            fail += 1
                            st.caption(f"❌ #{i+1} 保存失败：{e}")
                        progress.progress((idx + 1) / len(selected))
                    loop.close()
                    st.success(f"批量保存完成：✅ {ok} 成功 / ❌ {fail} 失败")
                    st.caption(f"DB 当前 JD 总数：{len(db.list_jds())}")

    elif input_type == "上传 PDF 文件":
        st.markdown("上传 JD 相关的 PDF 文件（简历、职位描述等），系统将自动解析、分块并向量化入库。")

        uploaded_pdf = st.file_uploader("选择 PDF 文件", type=["pdf"])

        if uploaded_pdf is not None:
            pdf_path = PROJECT_ROOT / "data" / "uploads" / uploaded_pdf.name
            pdf_path.parent.mkdir(exist_ok=True, parents=True)
            with open(pdf_path, "wb") as f:
                f.write(uploaded_pdf.getvalue())
            st.info(f"✅ 文件已上传: {uploaded_pdf.name}")

            if st.button("解析并入库 PDF", type="primary"):
                with st.spinner("正在解析 PDF 并入库..."):
                    try:
                        db = get_db()
                        # 可选传入 classifier
                        clf = Classifier()
                        jd_id = db.insert_jd_from_parsed_pdf(str(pdf_path), classifier=clf)

                        # 获取 chunk 数量
                        chunks = db.get_chunks_by_jd(jd_id)
                        chunk_count = len(chunks)

                        st.success(f"✅ PDF 入库成功！")
                        st.info(f"JD ID: `{jd_id}` | 解析出 {chunk_count} 个知识块")

                        if chunk_count > 0:
                            st.caption("已自动完成语义分块 + 上下文生成 + 向量化存储。")

                    except Exception as e:
                        st.error(f"PDF 解析入库失败: {e}")
                        import traceback
                        st.error(traceback.format_exc())

    else:
        jd_url = st.text_input("职位 URL", placeholder="https://www.zhipin.com/job_detail/...")

        if st.button("从 URL 分析 JD", type="primary") and jd_url and st.session_state.agent:
            with st.spinner("正在从 URL 分析 JD..."):
                try:
                    llm_client = st.session_state.agent.llm_client
                    analyzer = JDAnalyzerEnhanced(llm_client=llm_client)

                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    jd_result = loop.run_until_complete(analyzer.parse_from_url(jd_url))

                    # 自动分类JD
                    classification = loop.run_until_complete(st.session_state.kb.classify_jd(jd_result))
                    loop.close()

                    st.session_state.jd_result = jd_result

                    # v2.1 M2: 同步落到 jobhunter_v2.db，供 Tab3 写 match_history
                    db = st.session_state.db
                    jd_for_db = {
                        "url": jd_url,
                        "title": jd_result.get("title", ""),
                        "company": jd_result.get("company", ""),
                        "location": jd_result.get("location", ""),
                        "salary_str": jd_result.get("salary_range"),
                        "raw_text": jd_result.get("raw_text", jd_url),
                        "source": "url",
                        "requirements": jd_result.get("core_requirements", []),
                        "preferred_requirements": jd_result.get("preferred_requirements", []),
                        "skills_required": jd_result.get("keywords", []),
                        "implicit_requirements": jd_result.get("implicit_requirements", ""),
                        "parsed_data": jd_result,
                    }
                    from database.classifier import Classifier as _Clf
                    _tags = _Clf().classify(jd_for_db["title"], jd_for_db["raw_text"])
                    jd_for_db.update(_tags)
                    st.session_state.jd_id = db.insert_jd(jd_for_db)

                    # v2.1 M3.4: JD 入库后语义切分 + 向量化
                    try:
                        from tools.jd_indexer import embed_and_store_jd_chunks
                        n_chunks = embed_and_store_jd_chunks(
                            db, st.session_state.jd_id, jd_for_db["raw_text"]
                        )
                        if n_chunks:
                            st.caption(f"🧩 已切分 {n_chunks} 个语义 chunk 并向量化")
                    except Exception as _ex:
                        st.caption(f"⚠️ 向量化失败：{_ex}")

                    # 显示分类结果
                    st.info(f"📋 自动分类: **{classification['category']}** (置信度: {int(classification['confidence']*100)}%)")
                    if classification['reasoning']:
                        st.caption(f"理由: {classification['reasoning']}")

                    # 自动入库
                    if st.session_state.auto_save:
                        kb = st.session_state.kb
                        kb.switch_database(classification['category'])
                        st.session_state.current_db = classification['category']

                        jd_id = kb.add_jd({
                            "raw_text": jd_url,
                            "parsed_data": jd_result,
                            "source": "url"
                        })
                        st.success(f"✅ JD 分析成功！已保存到「{classification['category']}」(ID: {jd_id})")
                    else:
                        st.success("✅ JD 分析成功！")
                except Exception as e:
                    # v2.1 M2.5: URL 抓取失败给出明确指引
                    err_msg = str(e)
                    st.error(f"❌ URL 分析失败：{err_msg}")
                    if "登录" in err_msg or "反爬" in err_msg or "Cloudflare" in err_msg or "未能" in err_msg:
                        st.info(
                            "💡 解决方案：\n"
                            "1. 改用「直接粘贴 JD」路径（推荐，最稳定）；\n"
                            "2. 或运行 `python scripts/collectors/login_jobsdb.py` 完成首次登录后重试；\n"
                            "3. 或在弹出的浏览器中手动过验证后再次尝试。"
                        )

    if st.session_state.jd_result:
        st.divider()
        st.markdown("### 📋 职位分析结果")

        jdr = st.session_state.jd_result

        col1, col2 = st.columns(2)

        with col1:
            with st.expander("🏢 职位信息", expanded=True):
                st.write(f"**职位**: {jdr.get('title', 'N/A')}")
                st.write(f"**公司**: {jdr.get('company', 'N/A')}")
                st.write(f"**地点**: {jdr.get('location', 'N/A')}")
                st.write(f"**薪资**: {jdr.get('salary', 'N/A')}")

        with col2:
            with st.expander("🎯 核心要求", expanded=True):
                reqs = jdr.get("core_requirements", [])
                for i, req in enumerate(reqs, 1):
                    st.write(f"{i}. {req}")

        with st.expander("🔑 技能关键词", expanded=True):
            keywords = jdr.get("keywords", [])
            for skill in keywords:
                st.markdown(f'<span class="skill-tag skill-neutral">{skill}</span>', unsafe_allow_html=True)

# =====================================================
# 标签页 3: 匹配度分析
# =====================================================
with tab3:
    st.header("匹配度分析")

    if not st.session_state.resume_data:
        st.warning("⚠️ 请先在第一个标签页上传并解析简历！")
    elif not st.session_state.jd_result:
        st.warning("⚠️ 请先在第二个标签页分析职位描述！")
    else:
        if st.button("分析匹配度", type="primary"):
            with st.spinner("正在分析匹配度 (使用 LLM)..."):
                try:
                    # 使用 CoordinatorAgent 执行匹配分析
                    agent = st.session_state.agent

                    # 先设置 agent 状态中的 resume_data 和 jd_result
                    agent.state['resume_data'] = st.session_state.resume_data
                    agent.state['jd_result'] = st.session_state.jd_result

                    # 重置 agent 的 LLM 调用统计
                    if hasattr(agent.llm_client, 'reset_stats'):
                        agent.llm_client.reset_stats()

                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)

                    # 执行匹配分析
                    match_result = loop.run_until_complete(agent._tool_analyze_match())

                    agent.state['match_result'] = match_result.get('match_result')

                    loop.close()

                    st.session_state.match_result = match_result.get('match_result')
                    st.success("✅ 匹配度分析成功！")

                    # v2.1 M2: 落库 match_history
                    mr_payload = match_result.get('match_result') or {}
                    rid = st.session_state.get('resume_id')
                    jid = st.session_state.get('jd_id')
                    if rid and jid:
                        try:
                            db = st.session_state.db
                            match_id = db.insert_match({
                                'resume_id': rid,
                                'jd_id': jid,
                                'score': int(mr_payload.get('score', 0) or 0),
                                'reasoning': mr_payload.get('reasoning', ''),
                                'matched_skills': mr_payload.get('matching_skills', []),
                                'missing_skills': mr_payload.get('missing_skills', []),
                                'gaps': mr_payload.get('gaps', []),
                                'recommendations': mr_payload.get('recommendations', []),
                                'skill_mapping': mr_payload.get('skill_mapping', []),
                                'should_apply': 1 if mr_payload.get('should_apply') else 0,
                            })
                            st.session_state.last_match_id = match_id
                            # v2.1 M6.A.3: 供 AI 浮窗上下文使用
                            st.session_state.last_match_score = mr_payload.get('score')
                            st.caption(f"💾 已记录匹配 ID: `{match_id[:8]}` (Tab6 投递历史可查)")

                            # v2.1 M2: 同步把每条 recommendation 写入 optimizations 表
                            opt_ids = []
                            for rec in mr_payload.get('recommendations', []) or []:
                                if not isinstance(rec, dict):
                                    continue
                                rec_type = rec.get('type', 'modify')
                                # 兼容三种 type：modify / delete / suggest_add
                                if rec_type == 'suggest_add':
                                    suggested = rec.get('suggestion', '')
                                    original = ''
                                else:
                                    suggested = rec.get('suggested', '')
                                    original = rec.get('original', '')
                                try:
                                    opt_id = db.insert_optimization({
                                        'resume_id': rid,
                                        'jd_id': jid,
                                        'optimization_type': rec_type,
                                        'section': rec.get('section', ''),
                                        'original_content': original,
                                        'suggested_content': suggested,
                                        'reason': rec.get('reason', ''),
                                    })
                                    opt_ids.append(opt_id)
                                except Exception as exc:
                                    logger.warning(f"optimization 写入失败: {exc}")
                            st.session_state.last_opt_ids = opt_ids
                            if opt_ids:
                                st.caption(f"💾 已记录 {len(opt_ids)} 条优化建议（可在下方勾选「采纳」）")
                        except Exception as exc:
                            logger.warning(f"match_history 写入失败: {exc}")
                    else:
                        st.warning("⚠️ resume_id 或 jd_id 缺失，跳过 match_history 落库（请重新解析简历/JD）")

                    # 显示 LLM 调用信息
                    if hasattr(agent.llm_client, 'get_stats'):
                        llm_stats = agent.llm_client.get_stats()
                        if llm_stats.get('total_calls', 0) > 0:
                            st.markdown("### 🤖 LLM 调用确认")
                            st.success(f"✅ **LLM 真实被调用！**")
                            st.info(f"调用次数: {llm_stats.get('total_calls', 0)}")
                            st.info(f"总 Token 数: {llm_stats.get('total_tokens', 0)}")
                        else:
                            st.warning("⚠️ **未检测到 LLM 调用**，可能使用的是规则匹配")
                    else:
                        st.info("LLM 统计不可用")

                except Exception as e:
                    st.error(f"分析失败: {e}")
                    import traceback
                    st.error(traceback.format_exc())

        if st.session_state.match_result:
            st.divider()

            mr = st.session_state.match_result
            score = mr.get("score", 0)

            # 显示匹配度分数
            col1, col2, col3 = st.columns([1, 2, 1])
            with col2:
                st.markdown("### 📊 匹配度")
                if score >= 70:
                    st.markdown(f'<div class="match-high">{score}%</div>', unsafe_allow_html=True)
                    st.success("高度匹配！建议投递！")
                elif score >= 50:
                    st.markdown(f'<div class="match-medium">{score}%</div>', unsafe_allow_html=True)
                    st.warning("基本匹配，建议优化后投递")
                else:
                    st.markdown(f'<div class="match-low">{score}%</div>', unsafe_allow_html=True)
                    st.error("匹配度较低，建议寻找更匹配的职位")

            st.divider()

            # ============ 技能映射展示 ============
            skill_mapping = mr.get("skill_mapping", [])
            if skill_mapping:
                st.markdown("### 🔄 技能映射（可迁移技能识别）")
                st.caption("你的经验如何映射到JD要求")

                for mapping in skill_mapping:
                    col1, col2, col3 = st.columns([2, 1, 2])
                    with col1:
                        st.markdown(f"**你的经验:** {mapping.get('resume_skill', '')}")
                    with col2:
                        confidence = mapping.get('confidence', 0)
                        st.markdown(f"<div style='text-align:center; font-weight:bold; color: #059669'>→ {int(confidence*100)}%</div>", unsafe_allow_html=True)
                    with col3:
                        st.markdown(f"**JD要求:** {mapping.get('jd_requirement', '')}")
                    if mapping.get('explanation'):
                        st.caption(f"💡 {mapping.get('explanation')}")
                    st.divider()

            # ============ 智能技能对比 ============
            st.markdown("### 🛠️ 技能对比")

            col1, col2 = st.columns(2)
            with col1:
                st.markdown("#### ✅ 已匹配/可迁移技能")
                matching_skills = mr.get("matching_skills", [])
                if matching_skills:
                    for skill in matching_skills:
                        st.markdown(f'<span class="skill-tag skill-match">{skill}</span>', unsafe_allow_html=True)
                else:
                    st.write("无")

            with col2:
                st.markdown("#### ⚠️ 确实缺失的技能")
                missing_skills = mr.get("missing_skills", [])
                if missing_skills:
                    for skill in missing_skills:
                        st.markdown(f'<span class="skill-tag skill-gap">{skill}</span>', unsafe_allow_html=True)
                else:
                    st.write("无")

            # 理由分析
            with st.expander("🤔 匹配度分析理由", expanded=True):
                st.write(mr.get("reasoning", "N/A"))

            # 差距分析
            gaps = mr.get("gaps", [])
            if gaps:
                with st.expander("📉 差距分析", expanded=True):
                    for gap in gaps:
                        importance = gap.get('importance', 'medium')
                        emoji = "🔴" if importance == 'high' else "🟡" if importance == 'medium' else "🟢"
                        st.write(f"{emoji} {gap.get('description', '')}")

            # ============ 详细优化建议 ============
            recs = mr.get("recommendations", [])
            opt_ids_for_recs = st.session_state.get('last_opt_ids', [])
            if recs and len(recs) > 0 and isinstance(recs[0], dict):
                st.markdown("### ✍️ 详细优化建议")
                st.caption("每一条建议都说明了「改什么」和「为什么这样改」。勾选「✅ 采纳」会落库到 optimizations.user_adopted")

                for i, rec in enumerate(recs):
                    rec_type = rec.get('type', 'modify')
                    type_label = {
                        'modify': '📝 修改',
                        'delete': '🗑️ 删除',
                        'suggest_add': '➕ 建议补充'
                    }.get(rec_type, '📝 修改')

                    with st.expander(f"建议 #{i+1}: {type_label} - {rec.get('section', '修改')}", expanded=True):
                        if rec_type == 'modify':
                            # 修改建议：左右对比
                            col1, col2 = st.columns(2)
                            with col1:
                                st.markdown("**原文:**")
                                st.markdown(f"<div style='background-color: #450a0a; color: white; padding:10px; border-radius:5px;'>{rec.get('original', '')}</div>", unsafe_allow_html=True)
                            with col2:
                                st.markdown("**建议修改为:**")
                                st.markdown(f"<div style='background-color: #052e16; color: white; padding:10px; border-radius:5px;'>{rec.get('suggested', '')}</div>", unsafe_allow_html=True)

                            st.markdown("**💡 为什么这样改:**")
                            st.info(rec.get('reason', ''))
                        elif rec_type == 'delete':
                            # 删除建议：只显示原文和理由
                            st.markdown("**建议删除:**")
                            st.markdown(f"<div style='background-color: #450a0a; color: white; padding:10px; border-radius:5px;'>{rec.get('original', '')}</div>", unsafe_allow_html=True)
                            st.markdown("**💡 为什么删除:**")
                            st.warning(rec.get('reason', ''))
                        elif rec_type == 'suggest_add':
                            # 补充建议：显示建议和理由
                            st.markdown("**建议补充:**")
                            st.markdown(f"<div style='background-color: #0c4a6e; color: white; padding:10px; border-radius:5px;'>{rec.get('suggestion', '')}</div>", unsafe_allow_html=True)
                            st.markdown("**💡 为什么补充:**")
                            st.info(rec.get('reason', ''))

                        # v2.1 M2: 采纳开关
                        if i < len(opt_ids_for_recs):
                            opt_id_local = opt_ids_for_recs[i]
                            adopted_now = st.toggle(
                                "✅ 采纳此建议",
                                value=False,
                                key=f"adopt_{opt_id_local}",
                                help=f"opt_id: {opt_id_local}",
                            )
                            if adopted_now != st.session_state.get(f"_adopted_state_{opt_id_local}", False):
                                try:
                                    st.session_state.db.update_optimization_adopted(
                                        opt_id_local, 1 if adopted_now else 0
                                    )
                                    st.session_state[f"_adopted_state_{opt_id_local}"] = adopted_now
                                except Exception as exc:
                                    logger.warning(f"采纳状态写库失败: {exc}")
            else:
                # 兼容旧格式
                if recs:
                    with st.expander("💡 优化建议", expanded=True):
                        for rec in recs:
                            st.write(f"• {rec}")

# =====================================================
# 标签页 4: 生成优化内容
# =====================================================
with tab4:
    st.header("生成优化内容")

    company_name = st.text_input("目标公司名称", value="目标公司")

    col1, col2 = st.columns(2)

    with col1:
        if st.button("生成优化简历", type="primary"):
            if not st.session_state.resume_data:
                st.error("请先解析简历！")
            elif not st.session_state.jd_result or not st.session_state.match_result:
                st.error("请先分析JD并进行匹配分析！")
            else:
                with st.spinner("正在生成优化简历..."):
                    try:
                        # 检索相关 JD chunks 作为参考知识
                        jd_query = st.session_state.jd_result.get("title", "")
                        reference_chunks = []
                        try:
                            from tools.retriever import Retriever
                            retriever = Retriever()
                            reference_chunks = retriever.retrieve(
                                jd_query, top_k=3, filter_chunk_type="responsibility"
                            )
                            if reference_chunks:
                                st.info(f"🔍 检索到 {len(reference_chunks)} 个相关 JD 知识块作为参考")
                        except Exception as exc:
                            logger.warning(f"向量检索失败: {exc}")
                        # 先用ResumeOptimizer优化内容
                        llm_client = st.session_state.agent.llm_client
                        optimizer = ResumeOptimizer(llm_client)

                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)

                        recommendations = st.session_state.match_result.get('recommendations', [])

                        optimized_resume_data = loop.run_until_complete(
                            optimizer.optimize(
                                st.session_state.resume_data,
                                st.session_state.jd_result,
                                recommendations
                            )
                        )
                        loop.close()

                        # 再用ResumeGenerator生成markdown
                        generator = ResumeGenerator()
                        md = generator.to_markdown(optimized_resume_data)
                        html = generator.to_html(optimized_resume_data)

                        st.session_state.optimized_resume = md
                        st.session_state.optimized_resume_html = html
                        st.success("✅ 简历优化并生成成功！")

                        # 显示参考知识（如果有）
                        if reference_chunks:
                            with st.expander("📚 参考的 JD 知识块", expanded=False):
                                for i, rc in enumerate(reference_chunks):
                                    st.markdown(f"**Chunk #{i+1}** (similarity: {rc.get('similarity', 0):.3f})")
                                    st.caption(f"上下文: {rc.get('context', '')}")
                                    st.code(rc.get('chunk_text', '')[:500], language=None)
                                    st.divider()
                        else:
                            st.caption("ℹ️ 未检索到相关参考知识，优化建议基于当前 JD 生成。")
                    except Exception as e:
                        st.error(f"生成失败: {e}")
                        import traceback
                        st.error(traceback.format_exc())

    with col2:
        if st.button("生成 Cover Letter", type="primary"):
            if not st.session_state.resume_data or not st.session_state.jd_result:
                st.error("请先解析简历和分析 JD！")
            else:
                with st.spinner("正在生成 Cover Letter..."):
                    try:
                        llm_client = st.session_state.agent.llm_client
                        cl_generator = CoverLetterGenerator(llm_client=llm_client)

                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        cl = loop.run_until_complete(cl_generator.generate(
                            st.session_state.resume_data,
                            st.session_state.jd_result,
                            company_name
                        ))
                        loop.close()

                        st.session_state.cover_letter = cl
                        st.success("✅ Cover Letter 生成成功！")
                    except Exception as e:
                        st.error(f"生成失败: {e}")

    if st.button("完整工作流 (简历优化 + Cover Letter)", type="primary"):
        if not st.session_state.resume_data or not st.session_state.jd_result:
            st.error("请先解析简历和分析 JD！")
        else:
            with st.spinner("正在执行完整工作流..."):
                try:
                    agent = st.session_state.agent
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)

                    result = loop.run_until_complete(agent.execute({
                        "company_name": company_name
                    }))
                    loop.close()

                    # 更新状态
                    st.session_state.match_result = result.get('match_result')
                    st.session_state.optimized_resume = result.get('resume_markdown')
                    st.session_state.cover_letter = result.get('cover_letter')

                    # 持久化匹配结果
                    match_data = result.get('match_result', {})
                    if match_data:
                        db = st.session_state.db
                        db.insert_match({
                            "resume_id": "",  # TODO: 从持久化 resume 取 id
                            "jd_id": "",      # TODO: 从持久化 jd 取 id
                            "score": match_data.get("match_result", {}).get("score", 0),
                            "reasoning": match_data.get("match_result", {}).get("reasoning", ""),
                            "should_apply": match_data.get("match_result", {}).get("should_apply", False),
                        })

                    st.success("✅ 完整工作流执行成功！")
                except Exception as e:
                    st.error(f"执行失败: {e}")

    st.divider()

    if st.session_state.optimized_resume:
        st.markdown("### 📄 优化后的简历")
        st.markdown(st.session_state.optimized_resume)

        dl_col1, dl_col2 = st.columns(2)
        with dl_col1:
            st.download_button(
                "下载简历 (Markdown)",
                st.session_state.optimized_resume,
                file_name=f"{company_name}_简历.md",
                mime="text/markdown"
            )
        with dl_col2:
            html_payload = st.session_state.get("optimized_resume_html")
            if html_payload:
                st.download_button(
                    "下载简历 (HTML，可浏览器打印 PDF)",
                    html_payload,
                    file_name=f"{company_name}_简历.html",
                    mime="text/html"
                )

    if st.session_state.cover_letter:
        st.divider()
        st.markdown("### ✉️ Cover Letter")
        st.write(st.session_state.cover_letter)

        st.download_button(
            "下载 Cover Letter",
            st.session_state.cover_letter,
            file_name=f"{company_name}_CoverLetter.txt",
            mime="text/plain"
        )

st.divider()
st.markdown("---")
st.markdown("*Powered by Job Hunter - 智能求职助手*")

# =====================================================
# 标签页 5: 知识库
# =====================================================
with tab5:
    st.header(f"📚 知识库管理 - {st.session_state.current_db}")

    kb = st.session_state.kb

    # 统计信息
    stats = kb.get_stats()
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("JD 总数", stats["total_jds"])
    with col2:
        st.metric("公司数", len(stats["companies"]))
    with col3:
        st.metric("技能种类", len(stats["top_skills"]))

    st.divider()

    # 热门技能
    if stats["top_skills"]:
        st.markdown("### 🔥 热门技能")
        for skill, count in stats["top_skills"]:
            st.markdown(f'<span class="skill-tag skill-neutral">{skill} ({count})</span>', unsafe_allow_html=True)
        st.divider()

    # 批量添加JD（主要功能）
    st.markdown("### 📥 添加职位到知识库")
    st.success("💡 **推荐方式**: 从招聘网站复制职位描述，粘贴到下方！这是最稳定可靠的方式。")

    input_method = st.radio("选择输入方式", ["批量粘贴JD", "上传文件"], horizontal=True)

    if input_method == "批量粘贴JD":
        st.markdown("将多个JD粘贴在下方，**用空行分隔**：")
        jd_input = st.text_area("多个JD（空行分隔）", height=300, placeholder="""Job 1: AI Product Manager @ Company 1
...

Job 2: AI Engineer @ Company 2
...

...""")

        col1, col2 = st.columns(2)
        with col1:
            auto_analyze = st.checkbox("自动分析并分类", value=True)
        with col2:
            auto_save = st.checkbox("自动保存到知识库", value=True)

        if st.button("处理JD", type="primary") and jd_input and st.session_state.agent:
            # 按空行分割
            jd_texts = [t.strip() for t in jd_input.split('\n\n') if t.strip()]

            if not jd_texts:
                st.warning("请输入至少一个JD！")
            else:
                success_count = 0
                progress_bar = st.progress(0)

                for idx, jd_text in enumerate(jd_texts):
                    try:
                        with st.spinner(f"正在处理第 {idx+1}/{len(jd_texts)} 个JD..."):
                            if auto_analyze:
                                # 分析JD
                                llm_client = st.session_state.agent.llm_client
                                analyzer = JDAnalyzerEnhanced(llm_client=llm_client)

                                loop = asyncio.new_event_loop()
                                asyncio.set_event_loop(loop)
                                jd_result = loop.run_until_complete(analyzer.parse_from_text(jd_text))

                                # 自动分类
                                classification = loop.run_until_complete(kb.classify_jd(jd_result))
                                loop.close()

                                st.info(f"  → 分类为: {classification['category']} (置信度: {int(classification['confidence']*100)}%)")

                                if auto_save:
                                    # 切换到对应数据库并保存
                                    kb.switch_database(classification['category'])
                                    jd_id = kb.add_jd({
                                        "raw_text": jd_text,
                                        "parsed_data": jd_result,
                                        "source": "batch_manual"
                                    })
                                    success_count += 1
                            else:
                                if auto_save:
                                    # 只保存不分析
                                    jd_id = kb.add_jd({
                                        "raw_text": jd_text,
                                        "parsed_data": {},
                                        "source": "batch_manual"
                                    })
                                    success_count += 1

                        progress_bar.progress((idx + 1) / len(jd_texts))

                    except Exception as e:
                        st.error(f"处理第 {idx+1} 个JD失败: {e}")

                st.success(f"✅ 批量处理完成！成功处理 {success_count}/{len(jd_texts)} 个JD")

    else:
        # 上传文件
        uploaded_file = st.file_uploader("上传 JD 文件 (JSON/Text)", type=["json", "txt"])
        if uploaded_file is not None:
            try:
                content = uploaded_file.getvalue().decode('utf-8')
                if uploaded_file.name.endswith('.json'):
                    import json
                    jd_list = json.loads(content)
                    if isinstance(jd_list, list):
                        for jd_data in jd_list:
                            kb.add_jd(jd_data)
                        st.success(f"✅ 成功导入 {len(jd_list)} 个 JD！")
                    else:
                        st.error("JSON格式错误，需要是数组格式")
                else:
                    # 文本文件，按空行分割
                    jd_texts = content.split('\n\n')
                    for jd_text in jd_texts:
                        if jd_text.strip():
                            kb.add_jd({
                                "raw_text": jd_text.strip(),
                                "parsed_data": {},
                                "source": "batch_upload"
                            })
                    st.success(f"✅ 成功导入 {len(jd_texts)} 个 JD！")
            except Exception as e:
                st.error(f"导入失败: {e}")

    st.divider()

    # 智能爬取JD（实验性功能，折叠面板）
    with st.expander("🤖 实验性功能: 智能爬取JD (可能遇到反爬限制)"):
        st.info("💡 **提示**: 爬虫功能作为实验性功能提供，如遇反爬限制，请使用上方的手动粘贴功能！")

        if not st.session_state.scraper_manager:
            st.warning("⚠️ 请先在侧边栏初始化Agent！")
        else:
            st.markdown("""
            #### 📝 使用前准备（首次使用请先登录）

            为了绕过反爬检测，请先运行登录助手：

            1. 在项目目录打开终端/命令行
            2. 运行: `python login_jobsdb.py`
            3. 在打开的浏览器中手动登录 JobsDB
            4. 登录成功后回到终端按回车
            5. 之后再使用此爬虫功能

            登录状态会自动保存，以后无需重复登录。
            """)

            # 平台选择
            scraper_manager = st.session_state.scraper_manager
            platforms = scraper_manager.get_supported_platforms()

            # 默认选择JobsDB（优先）
            platform = st.selectbox(
                "选择平台",
                platforms,
                index=0 if platforms and "jobsdb" in platforms else 0,
                help="JobsDB 是优先推荐的平台"
            )

            # 显示平台信息
            platform_info = scraper_manager.get_platform_info(platform)
            if platform_info:
                st.info(f"{platform_info.get('name', platform)} - {platform_info.get('region', '')}")

            # 搜索条件
            col1, col2 = st.columns(2)
            with col1:
                keyword = st.text_input("搜索关键词", placeholder="如: AI Product Manager, AI Engineer")
            with col2:
                location = st.text_input("地点（可选）", placeholder="如: Hong Kong Island, Kowloon")

            col3, col4 = st.columns(2)
            with col3:
                limit = st.number_input("爬取数量", min_value=1, max_value=50, value=5, help="最多爬取的职位数量")
            with col4:
                headless = st.checkbox("无头模式（后台运行）", value=False, help="选择后浏览器不会显示")

            # 爬取按钮
            if st.button("开始爬取JD", type="primary") and keyword:
                if not st.session_state.agent:
                    st.error("请先初始化Agent！")
                else:
                    # 创建异步事件循环
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)

                    try:
                        with st.spinner(f"正在从 {platform_info.get('name', platform)} 爬取JD..."):
                            # 爬取JD
                            result = loop.run_until_complete(
                                scraper_manager.search_jobs(
                                    platform=platform,
                                    keyword=keyword,
                                    location=location if location else None,
                                    limit=limit,
                                    headless=headless,
                                )
                            )

                            if result.get("success"):
                                jobs = result.get("jobs", [])
                                st.success(f"✅ 成功获取 {len(jobs)} 个职位！")

                                if jobs:
                                    # 显示预览
                                    st.markdown("#### 📋 职位预览（前5个）")
                                    for i, job in enumerate(jobs[:5]):
                                        with st.expander(f"{i+1}. {job.get('title', 'N/A')} @ {job.get('company', 'N/A')}"):
                                            st.markdown(f"**公司**: {job.get('company', 'N/A')}")
                                            st.markdown(f"**薪资**: {job.get('salary', 'N/A')}")
                                            st.markdown(f"**地点**: {job.get('location', 'N/A')}")
                                            st.markdown(f"**链接**: {job.get('url', '')}")

                                    # 保存按钮
                                    if st.button("分析并保存到知识库"):
                                        save_progress = st.progress(0)
                                        save_success = 0

                                        for i, job in enumerate(jobs):
                                            try:
                                                with st.spinner(f"正在分析第 {i+1}/{len(jobs)} 个职位..."):
                                                    # 分析并保存
                                                    analyze_result = loop.run_until_complete(
                                                        scraper_manager.analyze_and_classify_jd(
                                                            jd=job,
                                                            knowledge_base=kb,
                                                        )
                                                    )

                                                    if analyze_result.get("success"):
                                                        classification = analyze_result.get("classification", {})
                                                        st.info(f"{i+1}. {job.get('title')} → 分类为: {classification.get('category')}")
                                                        save_success += 1

                                                save_progress.progress((i + 1) / len(jobs))

                                            except Exception as e:
                                                st.error(f"处理第 {i+1} 个职位失败: {e}")

                                        st.success(f"✅ 完成！成功保存 {save_success}/{len(jobs)} 个职位到知识库！")

                            else:
                                st.error(f"❌ 爬取失败: {result.get('error', '未知错误')}")

                    except Exception as e:
                        st.error(f"爬取失败: {e}")
                        import traceback
                        st.error(traceback.format_exc())
                    finally:
                        loop.close()

    st.divider()

    # JD 列表
    st.markdown("### 📋 JD 列表")
    jds = kb.list_jds(limit=50)

    if not jds:
        st.info("知识库为空，先去分析职位或上传JD吧！")
    else:
        for idx, jd in enumerate(jds):
            parsed = jd.get("parsed_data", {})
            title = parsed.get("title", "未知职位")
            company = parsed.get("company", "未知公司")
            source = jd.get("source", "manual")
            jd_id = jd.get("id", "")

            with st.expander(f"📌 {title} @ {company} ({source})", expanded=False):
                st.markdown(f"**ID**: {jd_id}")
                if parsed.get("location"):
                    st.markdown(f"**地点**: {parsed.get('location')}")
                if parsed.get("salary"):
                    st.markdown(f"**薪资**: {parsed.get('salary')}")

                skills = parsed.get("skills", [])
                if skills:
                    st.markdown("**技能**:")
                    for skill in skills:
                        st.markdown(f'<span class="skill-tag skill-neutral">{skill}</span>', unsafe_allow_html=True)

                requirements = parsed.get("core_requirements", [])
                if requirements:
                    st.markdown("**核心要求**:")
                    for req in requirements[:5]:
                        st.markdown(f"- {req}")

                col1, col2 = st.columns(2)
                with col1:
                    st.text_area("原始内容", jd.get("raw_text", ""), height=150)
                with col2:
                    if st.button(f"删除此 JD", key=f"del_{idx}"):
                        kb.delete_jd(jd_id)
                        st.success(f"已删除 {jd_id}")
                        st.experimental_rerun()

    st.divider()

    # 清空库
    st.markdown("### ⚠️ 危险操作")
    if st.button("清空当前数据库", type="primary"):
        count = kb.clear_database()
        st.success(f"已清空数据库，删除了 {count} 个 JD")

# =====================================================
# 标签页 6: 投递历史 (v2.1 M2)
# =====================================================
with tab6:
    st.header("📈 投递历史")
    st.caption("所有匹配分析结果都在这里，可标记投递状态、记录反馈，复盘求职转化率。")

    db_t6 = st.session_state.db
    matches = db_t6.list_matches(limit=200)

    if not matches:
        st.info("还没有匹配记录。在 Tab3 完成一次匹配分析后，这里会出现条目。")
    else:
        # 总览统计
        total = len(matches)
        applied = sum(1 for m in matches if m.get("applied"))
        replied = sum(1 for m in matches if (m.get("user_feedback") or "") in ("replied", "interview", "offer"))
        col_a, col_b, col_c, col_d = st.columns(4)
        col_a.metric("总匹配数", total)
        col_b.metric("已投递", applied)
        col_c.metric("有回复", replied)
        col_d.metric("投递率", f"{(applied/total*100):.0f}%" if total else "0%")

        st.divider()

        for m in matches:
            jd_obj = db_t6.get_jd(m["jd_id"]) or {}
            title = jd_obj.get("title", "(JD 已删除)")
            company = jd_obj.get("company", "")
            score = m.get("score", 0)
            applied_flag = bool(m.get("applied"))
            feedback = m.get("user_feedback") or "未反馈"
            opts = db_t6.list_optimizations(jd_id=m["jd_id"])
            adopted = sum(1 for o in opts if o.get("user_adopted"))
            adopt_rate = f"{adopted}/{len(opts)}" if opts else "0/0"

            header = f"{'✅' if applied_flag else '⚪️'} {score}% · {title} @ {company} — 反馈: {feedback} · 采纳率 {adopt_rate}"
            with st.expander(header, expanded=False):
                col1, col2, col3 = st.columns([2, 2, 2])
                with col1:
                    st.markdown(f"**Match ID**: `{m['id'][:8]}`")
                    st.markdown(f"**创建时间**: {m.get('created_at', '')}")
                    if m.get("applied_at"):
                        st.markdown(f"**投递时间**: {m['applied_at']}")
                with col2:
                    st.markdown("**操作**:")
                    if not applied_flag:
                        if st.button("📮 标记已投递", key=f"apply_{m['id']}"):
                            db_t6.update_match_applied(m["id"], 1)
                            st.experimental_rerun()
                    else:
                        if st.button("↩️ 撤销投递", key=f"unapply_{m['id']}"):
                            db_t6.update_match_applied(m["id"], 0, applied_at=None)
                            st.experimental_rerun()
                with col3:
                    st.markdown("**反馈状态**:")
                    fb_options = ["未反馈", "已读未回", "已回复", "进入面试", "拿到 Offer", "拒绝"]
                    fb_map = {
                        "未反馈": None,
                        "已读未回": "read",
                        "已回复": "replied",
                        "进入面试": "interview",
                        "拿到 Offer": "offer",
                        "拒绝": "rejected",
                    }
                    rev_map = {v: k for k, v in fb_map.items()}
                    current_label = rev_map.get(m.get("user_feedback"), "未反馈")
                    new_label = st.selectbox(
                        "选择反馈",
                        fb_options,
                        index=fb_options.index(current_label),
                        key=f"fb_{m['id']}",
                        label_visibility="collapsed",
                    )
                    if new_label != current_label:
                        target = fb_map[new_label]
                        if target is None:
                            db_t6.update_match_feedback(m["id"], "")
                        else:
                            db_t6.update_match_feedback(m["id"], target)
                        st.experimental_rerun()

                if m.get("reasoning"):
                    st.markdown("**匹配理由**:")
                    st.caption(m["reasoning"])


# =====================================================
# v2.1 M6.A.3: 右下角 AI 聊天浮窗
# =====================================================
with st.sidebar:
    with st.expander("💬 AI 求职助手", expanded=False):
        st.caption("基于当前简历 / 最近 JD / 匹配分回答。无需切换 Tab。")

        # 初始化对话历史
        if "ai_chat_history" not in st.session_state:
            st.session_state.ai_chat_history = []

        # 历史气泡（仅展示最近 6 条避免侧栏爆长）
        for msg in st.session_state.ai_chat_history[-6:]:
            role = msg.get("role", "user")
            with st.chat_message(role):
                st.markdown(msg.get("content", ""))

        user_input = st.chat_input("问点关于求职的…")
        if user_input:
            if not st.session_state.get("agent"):
                st.error("⚠️ 请先在 Tab1 配置 LLM agent")
            else:
                st.session_state.ai_chat_history.append({"role": "user", "content": user_input})
                with st.chat_message("user"):
                    st.markdown(user_input)

                # 注入项目上下文
                ctx = {
                    "resume": st.session_state.get("resume_data"),
                    "jd": st.session_state.get("jd_result"),
                    "match_score": st.session_state.get("last_match_score"),
                    "history": st.session_state.ai_chat_history,
                }
                try:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    result = loop.run_until_complete(
                        st.session_state.agent.chat_assistant(user_input, context=ctx)
                    )
                    loop.close()
                    reply = result.get("reply", "(空)")
                except Exception as e:
                    reply = f"⚠️ 调用失败：{e}"

                st.session_state.ai_chat_history.append({"role": "assistant", "content": reply})
                with st.chat_message("assistant"):
                    st.markdown(reply)

                # 限制历史长度，避免无限增长
                if len(st.session_state.ai_chat_history) > 20:
                    st.session_state.ai_chat_history = st.session_state.ai_chat_history[-12:]
                st.experimental_rerun()

# =====================================================
# 标签页 7: 从零生成简历 (P2-3 Flow A)
# =====================================================
with tab7:
    st.header("从零生成简历")
    st.caption("没有现成简历？告诉我你的目标和经历，AI 帮你写一份。")

    from tools import taxonomy
    from agents.resume_flow_a import ResumeFlowA

    # --- Step 1: 行业 / 岗位选择 ---
    if not st.session_state.fa_position:
        st.markdown("### 第 1 步：选择目标岗位")
        col_i, col_f, col_p = st.columns(3)
        with col_i:
            industries = taxonomy.list_industries()
            industry = st.selectbox("行业", ["(请选择)"] + industries, key="fa_industry_select")
        with col_f:
            functions = taxonomy.list_functions(industry) if industry and industry != "(请选择)" else []
            function = st.selectbox("职能", ["(请选择)"] + functions if functions else ["(请先选行业)"], key="fa_function_select", disabled=not functions)
        with col_p:
            positions = taxonomy.list_positions(industry, function) if industry and industry != "(请选择)" and function and function != "(请选择)" else []
            position = st.selectbox("岗位", ["(请选择)"] + positions if positions else ["(请先选职能)"], key="fa_position_select", disabled=not positions)

        if st.button("确定，开始对话", type="primary", disabled=position == "(请选择)" or not positions):
            st.session_state.fa_industry = industry
            st.session_state.fa_function = function
            st.session_state.fa_position = position
            st.session_state.fa_messages = [
                {"role": "user", "content": f"我想申请{industry}行业的{position}岗位，请通过提问帮我整理简历。"}
            ]
            st.experimental_rerun()

    # --- Step 2: 多轮对话 ---
    elif not st.session_state.fa_chat_done:
        st.markdown(f"### 第 2 步：与 AI 对话（目标：{st.session_state.fa_industry} / {st.session_state.fa_position}）")
        if st.button("重新选择岗位", key="fa_reset_choose"):
            for k in ["fa_industry", "fa_function", "fa_position", "fa_messages", "fa_chat_done", "fa_resume_data", "fa_resume_md", "fa_resume_html"]:
                st.session_state[k] = None if k != "fa_messages" else []
            st.session_state.fa_chat_done = False
            st.experimental_rerun()

        for m in st.session_state.fa_messages[1:]:
            with st.chat_message("user" if m["role"] == "user" else "assistant"):
                st.markdown(m["content"])

        if st.session_state.fa_messages and st.session_state.fa_messages[-1]["role"] == "user":
            with st.spinner("AI 思考中..."):
                try:
                    llm_client = st.session_state.agent.llm_client
                    flow_a = ResumeFlowA(llm_client)
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    reply = loop.run_until_complete(
                        flow_a.chat(st.session_state.fa_messages, st.session_state.fa_industry, st.session_state.fa_position)
                    )
                    loop.close()
                    st.session_state.fa_messages.append({"role": "assistant", "content": reply["message"]})
                    if reply["type"] == "done":
                        st.session_state.fa_chat_done = True
                    st.experimental_rerun()
                except Exception as exc:
                    st.error(f"AI 响应失败：{exc}")

        user_input = st.chat_input("回复 AI...")
        if user_input:
            st.session_state.fa_messages.append({"role": "user", "content": user_input})
            st.experimental_rerun()

        if st.button("我说完了，直接生成简历", key="fa_force_done"):
            st.session_state.fa_chat_done = True
            st.experimental_rerun()

    # --- Step 3: 生成简历 ---
    else:
        st.markdown("### 第 3 步：生成简历")

        if st.session_state.fa_resume_md is None:
            with st.spinner("正在分析对话、检索行业要求、生成简历..."):
                try:
                    llm_client = st.session_state.agent.llm_client
                    flow_a = ResumeFlowA(llm_client)
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    extracted = loop.run_until_complete(flow_a.extract_resume(st.session_state.fa_messages))
                    skeleton = loop.run_until_complete(flow_a.build_skeleton(st.session_state.fa_position, st.session_state.fa_industry))
                    final_data = loop.run_until_complete(flow_a.generate_final(extracted, skeleton, st.session_state.fa_position))
                    loop.close()
                    st.session_state.fa_resume_data = final_data
                    st.session_state.fa_resume_md = flow_a.to_markdown(final_data)
                    st.session_state.fa_resume_html = flow_a.to_html(final_data)
                    st.success("简历生成成功！")
                except Exception as exc:
                    st.error(f"生成失败：{exc}")
                    import traceback
                    st.code(traceback.format_exc())

        if st.session_state.fa_resume_md:
            st.markdown("#### 生成的简历")
            st.markdown(st.session_state.fa_resume_md)

            dl1, dl2, dl3 = st.columns(3)
            with dl1:
                st.download_button("下载 Markdown", st.session_state.fa_resume_md, file_name=f"{st.session_state.fa_position}_简历.md", mime="text/markdown", key="fa_dl_md")
            with dl2:
                if st.session_state.fa_resume_html:
                    st.download_button("下载 HTML (可打印 PDF)", st.session_state.fa_resume_html, file_name=f"{st.session_state.fa_position}_简历.html", mime="text/html", key="fa_dl_html")
            with dl3:
                if st.button("保存到数据库", key="fa_save_db"):
                    try:
                        rd = st.session_state.fa_resume_data
                        resume_payload = {"name": rd.get("header", {}).get("name", ""), "phone": rd.get("header", {}).get("contact", {}).get("phone", ""), "email": rd.get("header", {}).get("contact", {}).get("email", ""), "summary": rd.get("header", {}).get("summary", ""), "skills": rd.get("skills", []), "education": rd.get("education", []), "projects": rd.get("projects", []), "target_roles": [st.session_state.fa_position]}
                        resume_id = st.session_state.db.insert_resume(resume_payload)
                        st.success(f"已保存，resume_id = {resume_id[:12]}...")
                    except Exception as exc:
                        st.error(f"保存失败：{exc}")

            if st.button("重新开始", key="fa_restart"):
                for k in ["fa_industry", "fa_function", "fa_position", "fa_messages", "fa_chat_done", "fa_resume_data", "fa_resume_md", "fa_resume_html"]:
                    st.session_state[k] = None if k != "fa_messages" else []
                st.session_state.fa_chat_done = False
                st.experimental_rerun()
