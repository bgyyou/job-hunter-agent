# Job Hunter — 评审标准（v1 FROZEN 2026-08-03）

> **状态**：🧊 **v1 FROZEN** by pingce skill，owner 2026-08-03 拍板。后续评审发现新问题进 `ISSUES.md` 的 P2 区，不动 P0/P1 结构。
> **用途**：新会话评审 agent 读本文件 + ISSUES.md，只发现不修复。
> **纪律**：每条标准必须可判定（命令 / 输出 / 文件），不写"待评估"。
> **基线**：本次评审目标 commit = `5b1897a`（M-v4-1 收口后 HEAD）。
> **下次评审节点**：M-v5 起点 / 公开内测启动 / SaaS 上线任一触发。

---

## 1. 红线（任一不过 = 不合格）

每条红线给"判定命令 + 通过条件"。评审 agent 必须实测。

### R1 · 测试基线 = 544 passed / 1 failed（real_llm）
- **判定命令**：`pytest tests/ -q --tb=no`
- **通过条件**：输出末行 = `544 passed, 1 failed`（或 `1 failed` 后跟 `544 passed`）；失败仅限 `tests/integration/test_flow_a_real_llm_3_scenarios.py::TestRealLLMScenarios::test_scenario_a_full_mode_a` 单条
- **不通过处置**：先按 R2 修复后重测

### R2 · 真 LLM flake 必须修复（P0 红线）
- **判定命令 1**：`grep -n "real_llm" pytest.ini`
  - 通过条件：`addopts` 或 markers 默认包含 `real_llm`，使其默认 deselect
- **判定命令 2**：`pytest tests/ -q -m "not real_llm and not slow and not requires_model"`
  - 通过条件：输出末行 = `544 passed`（无 fail）
- **判定命令 3**：读 `tests/integration/test_flow_a_real_llm_3_scenarios.py:186` 周围 30 行
  - 通过条件：断言不再是"模式 A 必须保留原数字 200"这种硬要求；改为"输出含 ≥1 个原简历关键数字"或"多 case 取并集后 ≥1 数字出现"
- **不通过处置**：标记 R2 未达；R1 即便数字对也判不合格

### R3 · README vs 代码裂缝必须收口
- **判定命令**：`grep -nE "侧栏浮窗|采纳优化|接受/已读/拒绝反馈|liepin.*--site|jobsdb.*--site" README.md`
- **通过条件**：上述 4 类关键词**不出现**在 README 任何一处"主要功能"或"爬虫"节；如需提及 liepin/jobsdb，必须改写为"登录态可用，爬虫适配器 M-v5 阶段补"
- **额外判定**：`grep -n "is yet implemented" crawler/run_crawler.py`
  - 若 README 改完，crawler 代码应一致
- **不通过处置**：标记 R3 未达

### R4 · 铁律违反必须清理（3 处）
- **判定命令 1**（dead schema）：`grep -n "rag_industry_function\|暂保留为 dead schema" database/ services/ agents/`
  - 通过条件：0 命中（或仅有 migration 文件中已硬切删除的引用）
- **判定命令 2**（Step2 legacy 兜底）：`grep -n "fa_section_data\|legacy.*session_state" pages/`
  - 通过条件：0 命中
- **判定命令 3**（knowledge_chunks.legacy 列）：`grep -n "knowledge_chunks.*legacy\|legacy.*1" database/ scripts/ services/`
  - 通过条件：所有 SQL 移除 `legacy = 0` 过滤，列被 DROP（migration 015）
- **额外判定**：`grep -rn "leave.*for.*compatibility\|temporarily.*kept\|暂保留" --include="*.py" .`
  - 通过条件：0 命中（或每条命中均在评审前必读节有例外豁免说明）
- **不通过处置**：标记 R4 未达

### R5 · 安全红线
- **判定命令 1**（明文 docker 密码）：`grep -n "POSTGRES_PASSWORD.*jobhunter\|PASSWORD.*=.*jobhunter" docker-compose.yml docker-compose.prod.yml`
  - 通过条件：`docker-compose.prod.yml` 必须走 `--env-file .env.production` 读 `POSTGRES_PASSWORD`；dev `docker-compose.yml` 可保留 dev 默认值但需注释说明
- **判定命令 2**（登录错误信息脱敏）：`grep -n "用户不存在\|密码错误" services/auth_service.py`
  - 通过条件：错误信息统一为"邮箱/手机号或密码错误"，不再区分账号存在性
- **判定命令 3**（硬编码 key）：`grep -rnE "sk-[a-zA-Z0-9]{20,}|sk-ant-[a-zA-Z0-9_-]{20,}" --include="*.py" .`
  - 通过条件：0 命中（除 gitleaks 白名单 `.env.example` / `tools/githooks/*` 等）
- **判定命令 4**（简历粘贴长度上限）：`grep -n "st.text_area.*resume\|max_chars" pages/06_📄_Flow_B.py`
  - 通过条件：text_area 设 `max_chars`（建议 ≤ 20000 字符），超出截断并提示
- **不通过处置**：任一未达 → R5 未达

### R6 · 跨用户隔离（v4 多用户）
- **判定命令 1**：`grep -n "list_resumes.*default" database/ pages/`
  - 通过条件：0 命中（除 tests/ 中的 fixture）
- **判定命令 2**：读 `pages/08_📈_Application_History.py:159-176` 周围 30 行
  - 通过条件：用户无简历时**不再回退到 `"default"`**，显示空态 + 引导上传
- **不通过处置**：标记 R6 未达

### R7 · RAG 评测基线不退化
- **判定命令 1**：`pytest tests/integration/test_eval_rag.py -q --tb=no`（如存在）
- **判定命令 2**：`python eval/run_eval.py --baseline eval/queries.jsonl --limit 50 --judge-model <JUDGE_MODEL>`
  - 通过条件：NDCG@10 ≥ 0.646，Recall@10 ≥ 0.538，Hit Rate ≥ 0.96（portfolio.md L267-270 实测值，**基线值不是 fixed limit，是 M-v4-1 末态**）
- **判定命令 3**：mock fallback rate
  - 通过条件：`< 3%`（且逐步趋近 0%）
- **不通过处置**：任一指标退化 ≥5pp → 标记 R7 未达

### R8 · 编译/打包可复现
- **判定命令**：`bash scripts/build_launcher.bat`（或 `pyinstaller --onefile --name JobHunter --distpath dist scripts/jobhunter_launcher.py`）
- **通过条件**：进程退出码 = 0，`dist/JobHunter.exe` 重新生成且大小在 8.0-9.5 MB 区间
- **不通过处置**：构建失败 → R8 未达

---

## 2. 核心指标（考试卷：带数值目标）

按 AI 项目品类拆分：

### 2.1 RAG 检索类（Job Hunter = RAG-heavy）

| 指标 | 目标值 | 判定方法 |
|---|---|---|
| NDCG@10 | ≥ 0.646（portfolio.md L267 实测） | `python eval/run_eval.py --judge-model <JUDGE_MODEL>` 末行打印 |
| Recall@10 | ≥ 0.538 | 同上 |
| Hit Rate | ≥ 0.96 | 同上 |
| Mock Fallback Rate | < 3% | Ops 面板读 7 日均值（pages/99_📊_Ops.py panel 1） |
| 翻译覆盖 | ≥ 99.99% | `sqlite3 data/jobhunter_v2.db "SELECT COUNT(*) FROM knowledge_chunks WHERE chunk_text NOT LIKE '%[a-z]%' OR translation_status='done'"` 与 total 比 |
| 永久卡死 chunk | = 0 | 评测 retry_count 字段无 `>= MAX_RETRIES_PER_RECORD` 行 |
| 检索充分性（证据可追溯） | 100% | 评测结果每行必须有 `evidence_chunk_id` 非空 |
| 好源误杀率 | < 5% | golden 30 集命中率 ≥ 28/30 |

### 2.2 Agent 工具调用类（Coordinator + Applicant + Flow A/B）

| 指标 | 目标值 | 判定方法 |
|---|---|---|
| 工具调用干净完成率（无 retry / 无 fallback） | ≥ 90% | Ops 面板 panel 3（LLM 成功率 7 日均值） |
| 任务成功率（Flow A 5 步完成率） | ≥ 70%（manual 实测） | 用户内测 5 人次 × 10 次任务完成率 |
| 任务成功率（Flow B 端到端：上传→匹配→优化→导出） | ≥ 85%（manual 实测） | 同上 |
| Coordinator 工具调用无 exception 退出率 | ≥ 95% | `pytest tests/integration/test_coordinator_tools.py -q`（如存在） |
| Applicant 子流程完成率 | ≥ 80% | `pytest tests/integration/test_applicant_apply.py -q`（如存在） |

### 2.3 简历生成类（核心交付物）

| 指标 | 目标值 | 判定方法 |
|---|---|---|
| 一页纸约束（docx/pdf）达成率 | 100% | `OnePageEstimator` 输出 + 实际导出对比（10 抽样） |
| 文件名格式正确率 | 100% | `{姓名}_{岗位}_{公司}.{ext}`，缺一即失败 |
| 模式 A 保留原简历数字 | ≥ 80% | `pytest tests/integration/test_flow_a_real_llm_3_scenarios.py::test_scenario_a_full_mode_a`（R2 修复后） |
| Cover Letter 可用率 | ≥ 85% | `pytest tests/integration/test_cover_letter.py -q`（如存在） |
| LLM-as-judge 评分（生成质量） | ≥ 0.7 | `eval/judge.py` 对 50 query 跑分 |

### 2.4 系统质量

| 指标 | 目标值 | 判定方法 |
|---|---|---|
| 测试基线 | 544 passed / 1 failed（R2 修复后转 545 passed） | `pytest tests/ -q` |
| 模块覆盖率 | database ≥ 65% / services ≥ 80% / agents ≥ 16% / tools ≥ 25% / crawler ≥ 5% | `pytest --cov=<module> --cov-report=term` |
| 集成测试覆盖率 | ≥ 60% | 同上 --cov=tests/integration 间接 |
| pytest 耗时 | ≤ 90s | `pytest tests/ -q` 实测 wall time |
| Streamlit 启动耗时 | ≤ 5s（到首个页面渲染） | 手动计时 |
| 打包大小 | ≤ 9.5 MB | `ls -lh dist/JobHunter.exe` |
| 启动器脚本行数 | ≤ 300 行 | `wc -l scripts/jobhunter_launcher.py` |
| gitleaks scan | 0 命中 | `gitleaks detect --source . --config .gitleaks.toml` |
| 翻译 backfill 永不死循环 | 已实现 MAX_RETRIES_PER_RECORD | `grep -n "MAX_RETRIES_PER_RECORD" scripts/ services/` ≥ 3 命中 |

---

## 3. 质量项（只记录不扣分）

供评审 agent 了解项目当前做得好的地方 + 后续可能的优化方向。每项给"出处"便于交叉验证。

| 类别 | 项 | 出处 |
|---|---|---|
| 架构 | 子模块化无 shim（coordinator 1390→5 子模块，applicant 883→5 子模块） | commit `723ea16` + `67b44ea` |
| 架构 | Streamlit multipage 拆分（web_app 3865→1174 + pages/ 10 文件） | commit `ca219e4` + `861f162` |
| 架构 | provider-neutral LLM（4 env 切 4 家） | `config/settings.py:23-29` + `CLAUDE.md:49-50` |
| 架构 | SQLite 默认 + PG 可选双后端 | `database/factory.py` + `CLAUDE.md:52-54` |
| 数据 | v3→v4 schema 平滑迁移（13 个 migration 文件） | `database/migrations/002-016` |
| 数据 | 一次性硬切模式（CLAUDE.md 铁律执行） | 多处 commit message "无 shim" |
| 检索 | sqlite-vec vec0 HNSW + cross-encoder rerank | commit `05df45e` + `services/retrieval_service.py` |
| 检索 | chunk_type 加权（responsibility 1.2 / requirement 1.3） | `portfolio.md:125-156` |
| 评测 | LLM-as-judge + 50 query baseline + Spearman 校准 | `eval/README.md` + commit `94af037` |
| 可观测性 | Ops 面板 4 panel + 19 测试 | commit `3f96e25` + `pages/99_📊_Ops.py` |
| 可观测性 | loguru 20MB/7d 轮转 | `config/settings.py:152-153` |
| 可观测性 | 每次 LLM 调用埋点（latency / tokens / cache_hit / status） | `data/schema.sql:268-288` |
| 安全 | pre-commit 防硬编码 key | `.gitleaks.toml` + `tools/githooks/install.sh` |
| 安全 | internal_keys.json 内测机制 | `config/internal_keys.py:36-99` |
| 安全 | PBKDF2 + 15min 锁定 + 配额熔断（v4 多用户） | `services/auth_service.py` + `services/quota_service.py` |
| 工程 | `_text_utils.py` 等重复函数清理（在 R4 修复中） | R4 关联 |
| 工程 | 类型注解覆盖（pydantic v2） | 多数 services/ + agents/ 子模块 |
| 工程 | CI 跑 tests + secret-scan | `.github/workflows/` |
| 部署 | Docker compose 3 服务（app + pgvector + caddy） | `docker-compose.prod.yml` |
| 部署 | 一键 .exe（pyinstaller --onefile） | `scripts/build_launcher.bat` + `dist/JobHunter.exe` |

---

## 4. 质量改进项（建议但非强制，记录 P2）

| 类别 | 项 | 建议方向 | 来源 |
|---|---|---|---|
| 工程 | docs/portfolio.md 进 git | 改造成 README 的"作品集"子页 | owner 默认 |
| 工程 | docs/portfolio.md 数字夸大（"545 passed / 1500%"） | 与 CHANGELOG 对齐 | owner 默认 |
| 工程 | launch timing dashboard | 增加首屏渲染耗时监控 | Ops 扩展 |
| 工程 | Streamlit `set_page_config` 多 page 冲突 | 统一在 web_app.py 设，其他删 | `setup_wizard.py:70` |
| 数据 | lazy_score 锁（pages/07 race） | 加 advisory lock 或 version 字段 | `pages/07_📚_JD_Library.py:150-162` |
| 工程 | untracked 调试产物（eval_baseline_*.json / miss_analysis_*.md） | 加 .gitignore | git status |
| 工程 | tempfile 简历图片清理（pages/03） | 加定时清理 / 注册到 atexit | `pages/03_📝_Flow_A_Step1.py:189-202` |
| 工程 | smart_collector.py 走 v1 KB | 迁移到 v2 jobhunter_v2.db | `scripts/collectors/import_collected.py:108-117` |
| 检索 | Flow A 信息评分阈值（mode auto 切换） | 加 A/B 边界回测 | `services/information_scorer.py` |
| Agent | chat_assistant 浮窗（README 声称，代码未实现） | Q3 owner 决议改 README，不补 | Q3 决议 |
| Agent | update_optimization_adopted UI 入口 | Q3 owner 决议改 README，不补 | Q3 决议 |
| Agent | update_match_feedback / update_match_applied UI 入口 | Q3 owner 决议改 README，不补 | Q3 决议 |
| 爬虫 | liepin / jobsdb 适配器补完 | Q3 owner 决议改 README，标 M-v5 | Q3 决议 |
| 工程 | prompts/ 目录只有 1 文件，多数 prompt 内联 | 评估是否抽离 | `prompts/round-2-phase3-4.md` |

---

## 5. 打分锚点（不许裸刻度）

总分 = 红线 7 项（每项 × 1，过 = +1，不过 = -2）+ 核心指标 25 项（每项 × 0.5，过 = +0.5，未达 = -0.5，N/A = 0）+ 质量项（只展示不扣分）+ 质量改进项（只展示）。

| 分数段 | 定义 |
|---|---|
| **9.0-10.0** | 红线全过 + 核心指标 ≥95% + 质量改进项全部完成 |
| **7.5-8.9** | 红线全过 + 核心指标 ≥85% + 质量改进项 ≤3 项未做 |
| **6.0-7.4** | 红线全过 + 核心指标 ≥70% + 质量改进项 ≤6 项未做 |
| **4.5-5.9** | 红线 1 项未过 + 核心指标 ≥60% + 质量改进项 ≤10 项未做 |
| **3.0-4.4** | 红线 ≥2 项未过 + 核心指标 ≥50% |
| **0.0-2.9** | 红线 ≥3 项未过 或 核心指标 <50% |

**否决项**（独立于分数）：
- R5 安全红线任意一条不过 → 总分强制 ≤ 5.9
- R1 测试基线 < 540 passed → 总分强制 ≤ 5.9
- R7 RAG 评测指标退化 ≥10pp → 总分强制 ≤ 4.4

---

## 6. 评审 agent 工作流（建议）

1. 读本文件 + `ISSUES.md`
2. 对照 R1-R8 各跑判定命令，记录实测结果
3. 对照核心指标 25 项各跑判定方法，记录实测
4. 写评审结论：每项给"过 / 未达 / N/A"，未达项填入 `ISSUES.md` 的 P2 区
5. 不修复代码，只发现
6. 评审结束更新本文件第 0 节"评审前必读"的"评审节点"

---

## 附录 A · 文件索引（评审快速跳转）

- 主入口：`web_app.py`（1174 行）+ `setup_wizard.py`（155 行）+ `run_web.bat`（25 行）
- Streamlit 页面：`pages/01-09_*.py` + `pages/99_📊_Ops.py`（共 10 文件）
- 业务服务：`services/`（20 文件）
- Agent 子模块：`agents/coordinator/{chat,match_analysis,orchestrator,state,tools}.py` + `agents/applicant/{apply,retry,submit,tools}.py`
- 数据层：`database/`（17 migration + 双后端 + factory + classifier）
- 爬虫：`crawler/run_crawler.py`（248 行）+ `crawler/sites/{boss,indeed,lagou}.py` + `crawler/pipeline.py`
- 工具层：`tools/{llm,embedder,chunker,retriever,reranker,parser,scraper/*,generator/*}.py`
- 评测：`eval/{judge,run_eval,miss_analysis,sample_golden,sqlite_vec_perf,_extract_50_to_jsonl,_report_50,pick_baseline_50,dump_golden_candidates,build_queries}.py` + `README.md` + `annotation_guide.md`
- 测试：`tests/unit/`（38 文件）+ `tests/integration/`（17 文件）
- 脚本：`scripts/{build_launcher.bat, jobhunter_launcher.py, migrate_*.py}` + `scripts/collectors/{login_jobsdb, login_liepin, smart_collector, import_collected}.py`
- 配置：`config/{settings.py, internal_keys.py, internal_keys.example.json}`

---

**REVIEW.md 状态**：🧊 **v1 FROZEN 2026-08-03**
**关联**：`ISSUES.md`（同目录）

---

## 7. 评审前必读（v1 冻结时的口径记录）

> 本节是 v1 冻结时刻的所有未解决口径问题 / 默认决议 / 阻塞项。评审 agent 必读，避免对同一问题反复讨论。

### 7.1 owner 拍板项（已决议）

| 项 | 决议 | 时间 |
|---|---|---|
| 测试基线 | **544 passed / 1 failed**（实测 pytest，R2 修复后转 545 passed） | 2026-08-03 Q1 |
| 真 LLM flake | **P0 红线**：real_llm marker 默认 deselect + 改断言"保留数字"为更宽松条件 | 2026-08-03 Q2 |
| README vs 代码裂缝 4 处 | **改 README 删行**（不是补代码）：AI 助手浮窗/采纳按钮/反馈按钮/liepin 爬虫 | 2026-08-03 Q3 |
| 铁律违反 3 处 | **P0 强制清理**：migration 014 删 rag_industry_function 表 + migration 015 删 knowledge_chunks.legacy 列 + 删 Step2 legacy 兜底 | 2026-08-03 Q4 |
| 文件位置 | 项目根（与 README/CLAUDE.md 并排） | 2026-08-03 Q3 |
| 是否 commit | commit + push | 2026-08-03 Q4 |

### 7.2 owner 默认决议项（未走投票）

| 项 | 默认决议 | 备注 |
|---|---|---|
| launcher 行数 | README 写 160，实测 270 → **修 README**（不验证项目结构） | 小事 |
| docs/portfolio.md | **不进 git，评审不考虑其数字** | 叙事文件 |
| 死代码 / 小隐患 | 默认 P1 改进（launcher 重复函数 / _text_utils.py / docker 明文密码 / 懒评分 race） | 不进红线 |
| 数字小幅误差 | 打包 8.3 vs 8.6 MB，**容差内不扣分** | ±5% |

### 7.3 阻塞项（owner 未补充信息，等下次评审前补）

- **P1-010**："Flow B 同根因待确认" — 用户记忆，未在探查报告中找到具体证据
- **P1-011**："chunk 分类 21% 准确率" — 用户记忆，未指明具体文件/指标
- **P1-014**："5 个真实用户跑通全流程现状" — v4 多用户内测状态不明

### 7.4 跨文件口径记录

- `MEMORY.md` 第 3 行写 "544/1"（实测），与 README:138 的 "481" 不一致 — **以 544 为准**
- `CHANGELOG.md` 多个里程碑的测试基线（487 / 481 / 478 / 520 / 542）— 历史快照，不作准
- `docs/portfolio.md` 数字（"545 passed / 1500%"）— **不可信**，评审忽略

### 7.5 评审节点

每次会话结束 或 里程碑（M-v5 起点 / 公开内测启动 / SaaS 上线）跑一次评审，更新 `ISSUES.md`，不修改 `REVIEW.md` 的 P0/P1 结构（除非 owner 决议升级）。

| 日期 | 节点 | 关键结论 | 操作 |
|---|---|---|---|
| 2026-08-03 | v1.1 PRELIMINARY 复审 | R7/R8 跳过实测（R7 命令过时 / R8 用户决策）；R1-R6 红线未达（6 项）；核心过 9 / 未达 6 / N/A 12；段位 0.0-2.9（≥3 红线未过触发下限）；P2 增量 7 项（P2-011~P2-017） | pingce evaluator |

### 7.6 评审 agent 工作流

1. 读本文件 + `ISSUES.md`
2. 对照第 1 节 R1-R8 各跑判定命令，记录实测结果
3. 对照第 2 节核心指标 25 项各跑判定方法，记录实测
4. 对照第 5 节打分锚点计算总分
5. 写评审结论：每项"过 / 未达 / N/A"，未达项填入 `ISSUES.md` 的 P2 区
6. 不修复代码，只发现
7. 评审结束更新本节"评审节点"行（追加，不删旧）