# Job Hunter — 智能求职助手 v2.1

本地运行的 AI 求职闭环：简历解析 / JD 抓取 / 匹配评分 / 优化建议 / 投递追踪 / RAG 检索。
零云依赖，全部数据存本机。

![主界面](docs/screenshots/02_main_ui.png)

---

## 三步上手

### 1. 装依赖

```bash
git clone <this-repo>
cd job-hunter-agent
pip install -r requirements.txt
playwright install msedge   # 仅在你打算用浏览器爬虫时需要
```

> 依赖 Python ≥ 3.9。Windows 用户推荐用 `python -m venv .venv` 建虚拟环境。

### 2. 启动

```bash
streamlit run web_app.py
# 或者 Windows 双击 run_web.bat
```

**首次启动**会自动弹出"配置向导"页：
- 粘贴你自己的 API Key（[Agnes 申请入口](https://apihub.agnes-ai.com/) / [火山方舟](https://www.volcengine.com/product/ark)）
- 选数据库（默认 SQLite，零配置）
- 点保存 → 自动写入 `.env` → 进入主程序

![首次配置向导](docs/screenshots/01_setup_wizard.png)

> 我们**不内置任何 demo key**——既防 GitHub 抓取后被滥用，也确保你的额度只属于你。

### 3. （可选）启用 pre-commit 钩子

如果你打算改代码后提交：

```bash
bash tools/githooks/install.sh
```

钩子会拦截任何含 `sk-XXX` 形式硬编码 key 或 `.env` 真文件的提交。

---

## 主要功能

| Tab | 能力 |
|-----|------|
| 📄 上传简历 | PDF/Markdown 简历 → LLM 结构化抽取（姓名、技能、项目、经验年限） |
| 🌐 JD 来源 | 单条粘贴 / 批量粘贴（M6.A.2） / URL 抓取 / 站点爬虫（Boss、JobsDB、猎聘） |
| 🎯 匹配分析 | 简历 vs JD 匹配评分 + 缺口清单，结果落 `match_history` |
| ✏️ 优化建议 | 按段落生成改写建议；点"采纳"落 `optimizations.user_adopted` |
| 📈 投递历史 | 已匹配 JD 时间线 + 用户反馈（接受/已读/拒绝） |
| 💬 AI 求职助手 | 侧栏浮窗对话，自动注入当前简历/JD/匹配分作为上下文（M6.A.3） |

---

## 数据架构

| 项 | 说明 |
|---|---|
| 默认存储 | SQLite，文件：`data/jobhunter_v2.db` |
| 进阶存储 | PostgreSQL 14+ pgvector 0.8（`docker compose up -d postgres`） |
| 向量化 | BGE-small-zh（512 维），首启自动下载 ~95MB |
| 切分粒度 | overview / responsibility / requirement / nice_to_have |
| 检索 | pgvector cosine + chunk_type 加权（PG）；numpy fallback（SQLite） |

切换 PG：把 `.env` 里 `DATABASE_URL` 换成 `postgresql://jobhunter:jobhunter@localhost:5432/jobhunter`，跑 `python scripts/migrate_sqlite_to_pg.py` 迁数据。

---

## 爬虫

```bash
# Boss 直聘（推荐先 python scripts/collectors/login_jobsdb.py 同款流程登录）
python crawler/run_crawler.py --site boss --keyword "AI产品经理" --limit 20 --use-browser

# JobsDB（香港）
python crawler/run_crawler.py --site jobsdb --keyword "Product Manager" --limit 20

# 猎聘（M6.B.3.2 新增；先 python scripts/collectors/login_liepin.py 登录）
python crawler/run_crawler.py --site liepin --keyword "AI产品经理" --limit 10
```

爬虫的反爬策略（速率限制、并发上限、UA 轮换）在 `.env` 中配置，详见 `.env.example` 注释。
登录态失效时控制台会打印明确的"请重跑 login_xxx.py"提示，不会静默失败。

---

## 测试 & 治理

```bash
pytest tests/ -v --cov=database --cov=tools/embedder --cov=tools/chunker
# 期望：35/35 pass，repository/embedder/chunker 覆盖率 ≥60%
```

- 入口收敛：根目录只剩 `web_app.py` + `run_web.bat`，老脚本在 `scripts/legacy/`
- 日志轮转：loguru 20MB / 7 天，写到 `logs/`
- LLM 调用埋点：每次调用一行 `quality_checks` 记录（latency / tokens / 命中缓存 / 成功失败）
- 完整变更账本：见 `CHANGELOG_v2.1.md`

---

## 项目结构

```
job-hunter-agent/
├── web_app.py             # 主入口（Streamlit）
├── setup_wizard.py        # 首次运行配置向导（P0.5）
├── run_web.bat            # Windows 一键启动
├── .env.example           # 配置模板（无任何真 key）
├── requirements.txt       # 依赖
├── docker-compose.yml     # PG + pgvector
├── agents/                # CoordinatorAgent + 投递/分析/优化子 agent
├── tools/                 # llm / embedder / chunker / scraper / generator
│   └── githooks/          # pre-commit 防泄露钩子（仓库副本）
├── database/              # SQLite + Postgres 双后端 + factory
├── crawler/               # 爬虫流水线 & 站点适配器
├── scripts/
│   ├── collectors/        # login_*.py 登录助手
│   ├── legacy/            # v2.0 老脚本（保留参考）
│   └── migrate_sqlite_to_pg.py
├── tests/                 # pytest（unit + integration）
└── data/                  # 用户本地数据（gitignored）
```

---

## 给开发者的额外说明

- 代码风格：先读 `CLAUDE.md`（第一性原理 + 中文沟通）
- 提交前：`bash tools/githooks/install.sh` 一次即可
- 长程演进：每个里程碑追加到 `CHANGELOG_v2.1.md`，对照本文件修订项目结构图
- 升级 schema：在 `database/migrations/` 新增编号文件，更新 `schema_version` 表

---

## License & 免责声明

本仓库代码采用 [MIT License](LICENSE)，欢迎 fork、改造、二次分发。
想贡献回来？先看 [CONTRIBUTING.md](CONTRIBUTING.md)（三分钟读完）。

爬虫部分需遵守目标站点的 robots.txt / 服务条款，速率限制默认偏保守，请勿擅自调高 `CRAWLER_DAILY_LIMIT`。
