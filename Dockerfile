# syntax=docker/dockerfile:1
# ============================================================
# JobHunter app 镜像（v4 Phase 0 / T0.2）
# 单容器跑 Streamlit + playwright chromium + 本地 embedding。
# 数据库走外部 PG（docker-compose.prod.yml 的 postgres 服务）。
# ============================================================
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    # embedding 模型（BGE-small-zh ~95MB）落到 data volume，重建容器不重复下载
    HF_HOME=/app/data/hf_cache \
    # playwright 浏览器装到共享路径，非 root 用户可读
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

# 依赖层：锁文件优先复制，最大化 docker layer 缓存
COPY requirements.lock ./

# torch 先装 CPU-only wheel（lock 里 torch==2.12.0 按 PEP 440 匹配 2.12.0+cpu），
# 避免 PyPI linux 版默认拉 2GB+ CUDA 依赖；其余依赖走 requirements.lock 全量锁定。
# build-essential 只在构建期用，装完即清，控制镜像体积。
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl \
    && pip install --index-url https://download.pytorch.org/whl/cpu "torch==2.12.0" \
    && pip install -r requirements.lock \
    && playwright install --with-deps chromium \
    && apt-get purge -y build-essential \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

# 应用代码
COPY . .

# 非 root 运行
RUN useradd --create-home jobhunter \
    && mkdir -p /app/data \
    && chown -R jobhunter:jobhunter /app /ms-playwright
USER jobhunter

EXPOSE 8501

# Streamlit 自带 /healthz（tornado 层，无需应用代码），容器级健康检查直接用它
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD curl -fsS http://localhost:8501/healthz || exit 1

CMD ["streamlit", "run", "web_app.py", \
     "--server.address=0.0.0.0", \
     "--server.port=8501", \
     "--server.headless=true", \
     "--browser.gatherUsageStats=false"]
