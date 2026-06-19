"""
JobHunter JD Crawler - Streamlit UI
"""
import sys
from pathlib import Path

# 添加项目根目录，引用原有的爬虫代码
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import streamlit as st
import asyncio
import json
from datetime import datetime
from loguru import logger

# 引用原有的爬虫
from tools.scraper.jobsdb_scraper import JobsDBScraper


# ============ 页面配置 ============
st.set_page_config(
    page_title="JobHunter - JD Crawler",
    page_icon="🕷️",
    layout="wide"
)

st.title("🕷️ JobHunter - JD Crawler")


# ============ 状态管理 ============
if "crawling" not in st.session_state:
    st.session_state.crawling = False
if "crawled_jobs" not in st.session_state:
    st.session_state.crawled_jobs = []
if "log_messages" not in st.session_state:
    st.session_state.log_messages = []


def add_log(message: str, level: str = "INFO"):
    """添加日志"""
    timestamp = datetime.now().strftime("%H:%M:%S")
    st.session_state.log_messages.append(f"[{timestamp}] [{level}] {message}")


# ============ 侧边栏设置 ============
with st.sidebar:
    st.header("Settings")

    keyword = st.text_input("Search Keyword", value="AI Product Manager")
    location = st.text_input("Location", value="Hong Kong")
    max_jobs = st.number_input("Max Jobs", min_value=1, max_value=500, value=30)
    human_speed = st.slider("Human Speed", min_value=0.3, max_value=2.0, value=0.5, step=0.1,
                           help="1.0 = normal human speed, lower = slower (more stealth)")

    st.divider()

    # 控制按钮
    col1, col2 = st.columns(2)
    with col1:
        start_btn = st.button("🚀 Start Crawling", disabled=st.session_state.crawling, type="primary", use_container_width=True)
    with col2:
        stop_btn = st.button("⏹️ Stop", disabled=not st.session_state.crawling, use_container_width=True)

    st.divider()

    # 统计信息
    st.subheader("Stats")
    st.metric("Crawled Jobs", len(st.session_state.crawled_jobs))


# ============ 主区域 ============
col1, col2 = st.columns([1, 1])

with col1:
    st.subheader("Log")
    log_placeholder = st.empty()

with col2:
    st.subheader("Crawled Jobs")
    jobs_placeholder = st.empty()


# ============ 爬虫逻辑 ============
async def run_crawler():
    """运行爬虫"""
    st.session_state.crawling = True
    st.session_state.crawled_jobs = []
    st.session_state.log_messages = []

    add_log(f"Starting crawler for keyword: {keyword}")
    add_log(f"Using human speed: {human_speed}x")

    try:
        async with JobsDBScraper(headless=False, human_speed=human_speed) as scraper:
            add_log("Browser started, navigating to JobsDB...")

            # 搜索职位
            jobs = await scraper.search_jobs(keyword=keyword, location=location)
            add_log(f"Found {len(jobs)} job listings")

            # 爬取详情
            for i, job in enumerate(jobs[:max_jobs]):
                if not st.session_state.crawling:
                    add_log("Crawling stopped by user")
                    break

                url = job.get("url", "")
                title = job.get("title", f"Job {i+1}")

                add_log(f"Crawling {i+1}/{min(len(jobs), max_jobs)}: {title[:50]}...")

                if url:
                    try:
                        job_detail = await scraper.get_job_detail(url)
                        job_detail["title"] = title
                        job_detail["crawled_at"] = datetime.now().isoformat()

                        st.session_state.crawled_jobs.append(job_detail)

                        # 更新 UI
                        _update_ui()

                    except Exception as e:
                        add_log(f"Failed to crawl {url}: {e}", "ERROR")

            add_log(f"Crawling completed! Total: {len(st.session_state.crawled_jobs)} jobs")

    except Exception as e:
        add_log(f"Crawler error: {e}", "ERROR")
        logger.exception(e)

    finally:
        st.session_state.crawling = False


def _update_ui():
    """更新 UI"""
    # 更新日志
    with log_placeholder.container():
        for msg in st.session_state.log_messages[-20:]:  # 只显示最近20条
            st.text(msg)

    # 更新职位列表
    with jobs_placeholder.container():
        for job in st.session_state.crawled_jobs[-10:]:  # 只显示最近10个
            with st.expander(job.get("title", "Unknown")[:60]):
                st.write(f"URL: {job.get('url', 'N/A')}")
                st.text(job.get("raw_text", "")[:500] + "...")


# ============ 按钮事件 ============
if start_btn:
    # 直接运行（Streamlit 不支持 async 事件，这里简化处理）
    st.warning("请在命令行运行爬虫，Streamlit 中暂不支持直接启动浏览器")
    st.code("cd jd_crawler\npython simple_crawler.py")

if stop_btn:
    st.session_state.crawling = False
    add_log("Stopping crawler...")


# ============ 初始显示 ============
if not st.session_state.log_messages:
    add_log("Ready! Configure settings and click Start Crawling")

_update_ui()


# ============ 导出功能 ============
if st.session_state.crawled_jobs:
    st.divider()
    st.subheader("Export")

    col1, col2 = st.columns(2)
    with col1:
        # JSON 导出
        json_data = json.dumps(st.session_state.crawled_jobs, ensure_ascii=False, indent=2)
        st.download_button(
            "📥 Download JSON",
            data=json_data,
            file_name=f"crawled_jobs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
            mime="application/json"
        )
