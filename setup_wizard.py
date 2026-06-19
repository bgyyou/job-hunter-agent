"""首次运行配置向导。

当 .env 缺失或 LLM_API_KEY 仍是占位符 (your_api_key_here) 时，
显示一个友好的 Streamlit 配置页让用户填 key + 选数据库后一键写入 .env。

设计原则（呼应 v2.1 P0.5）：
- 不内置 demo key（防 GitHub secret scanner 抓取后引发额度滥用）
- 提供清晰的申请链接 + 回填后自动 rerun
- 默认 SQLite（朋友分享场景零配置）；进阶可切 PG
"""
from __future__ import annotations

import os
from pathlib import Path

import streamlit as st


PROJECT_ROOT = Path(__file__).resolve().parent
ENV_PATH = PROJECT_ROOT / ".env"
ENV_EXAMPLE = PROJECT_ROOT / ".env.example"
PLACEHOLDER = "your_api_key_here"


def _is_configured() -> bool:
    key = (os.environ.get("LLM_API_KEY") or "").strip()
    return bool(key) and key != PLACEHOLDER


def _seed_env_from_example() -> None:
    """如果 .env 不存在，先按 .env.example 拷一份，保留所有非 key 默认值。"""
    if ENV_PATH.exists() or not ENV_EXAMPLE.exists():
        return
    ENV_PATH.write_text(ENV_EXAMPLE.read_text(encoding="utf-8"), encoding="utf-8")


def _patch_env(updates: dict[str, str]) -> None:
    """把 updates 写入 .env：已有同名键替换值，缺失键追加到末尾。"""
    _seed_env_from_example()
    text = ENV_PATH.read_text(encoding="utf-8") if ENV_PATH.exists() else ""
    lines = text.splitlines()
    seen: set[str] = set()
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key = stripped.split("=", 1)[0].strip()
        if key in updates:
            lines[i] = f"{key}={updates[key]}"
            seen.add(key)
    for key, val in updates.items():
        if key not in seen:
            lines.append(f"{key}={val}")
    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_if_needed() -> None:
    """主入口。已配置则直接 return，否则渲染向导并 st.stop()。"""
    if _is_configured():
        return

    st.set_page_config(page_title="JobHunter 首次配置", page_icon="🛠️", layout="centered")
    st.title("🛠️ 首次运行配置")
    st.caption("只需 2 分钟，配置完一次往后自动加载。")

    st.markdown(
        """
        **为什么需要这一步？**
        本项目调用大模型完成简历解析、JD 分析、匹配评分等核心能力。
        我们不在仓库中内置任何 API key（防止泄露和滥用），需要你用自己的 key。
        """
    )

    with st.expander("如何申请 API key？（点击展开）", expanded=False):
        st.markdown(
            """
            - **Agnes（推荐，国内可直连）**：[apihub.agnes-ai.com](https://apihub.agnes-ai.com/) 注册后在控制台 → API Keys 复制
            - **火山方舟**：[volcengine.com/product/ark](https://www.volcengine.com/product/ark) 开通 → 获取访问密钥
            - 任意 OpenAI 兼容接口都可（粘 base URL 到下面的"高级"区即可）
            """
        )

    api_key = st.text_input(
        "API Key（必填）",
        type="password",
        placeholder="sk-...",
        help="粘贴后会写入本机 .env 文件，不会上传到任何服务器",
    )

    db_choice = st.radio(
        "数据库",
        options=["SQLite（推荐：零配置，文件存本地）", "PostgreSQL（高级：需先 docker compose up -d postgres）"],
        index=0,
    )

    with st.expander("高级选项（可跳过）", expanded=False):
        api_url = st.text_input(
            "API Base URL",
            value=os.environ.get("LLM_BASE_URL", "https://apihub.agnes-ai.com/v1"),
        )
        model_name = st.text_input(
            "模型名",
            value=os.environ.get("LLM_MODEL", "agnes-2.0-flash"),
        )

    col1, col2 = st.columns([1, 1])
    with col1:
        save = st.button("💾 保存配置并启动", type="primary", use_container_width=True)
    with col2:
        st.caption("保存后页面会自动刷新进入主程序")

    if save:
        if not api_key.strip():
            st.error("API Key 不能为空。请回到 Agnes/火山方舟控制台复制后再粘贴。")
            st.stop()
        if api_key.strip() == PLACEHOLDER:
            st.error("不要直接保存占位符 your_api_key_here，请填真实 key。")
            st.stop()

        db_url = (
            "sqlite:///data/jobhunter_v2.db"
            if db_choice.startswith("SQLite")
            else "postgresql://jobhunter:jobhunter@localhost:5432/jobhunter"
        )

        _patch_env(
            {
                "LLM_API_KEY": api_key.strip(),
                "LLM_BASE_URL": api_url.strip(),
                "LLM_MODEL": model_name.strip(),
                "DATABASE_URL": db_url,
            }
        )
        os.environ["LLM_API_KEY"] = api_key.strip()
        os.environ["LLM_BASE_URL"] = api_url.strip()
        os.environ["LLM_MODEL"] = model_name.strip()
        os.environ["DATABASE_URL"] = db_url

        st.success("✅ 配置已写入 .env，3 秒后自动进入主程序…")
        st.balloons()
        import time

        time.sleep(2)
        st.rerun()

    st.stop()
