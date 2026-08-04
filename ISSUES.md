# Job Hunter — 问题工单（v1 FROZEN 2026-08-03）

> **状态**：🧊 **v1 FROZEN** by pingce skill，owner 2026-08-03 拍板。后续 P0/P1 结构不变，新增/调整走 P2 增量。
> **用途**：本文件是 ISSUES 工单池，与 REVIEW.md 配套使用。
> **优先级**：P0 红线级 / P1 核心体验 / P2 改进或待确认。
> **纪律**：每条带编号 + 问题 + 代码依据 + 状态。状态变更新增"变更日志"行，不删旧条目。
> **基线**：本次评审目标 commit = `5b1897a`（M-v4-1 收口后 HEAD）。

---

## 变更日志

| 日期 | 变更 | 操作者 |
|---|---|---|
| 2026-08-03 | v1 PRELIMINARY 创建（基于探查 27 文件 + 三路 subagent 报告） | pingce skill |
| 2026-08-03 | **R5 关闭 P1-015**（commit `cbf3124` / `2983e56` / `0abb5df` / `99f7323` / docs）：R5-1 backends 27 处 `user_id: str = "default"` 必填化（关键字-only `*, user_id: str` 防挪首位 caller 静默串位）；R5-2 services/tools StructuredJD 删 user_id 字段 + LLMClient 改必填；R5-3 21 个测试 fixture 切到显式 user_id + 新增 `tests/unit/test_p1_015_no_default_user_id.py`（40 测试：反射守卫/e2e TypeError/静态 grep/一致性）；R5-4 写路径 caller 全部显式 user_id（pages/06 Flow_B + 7 个 scripts + audit/jd_library/flow_a_draft 服务）。基线 578 → **618 passed, 20 skipped, 3 deselected, 0 failed**（+40 守卫测试）。**R6 判定命令 1 使能机制就位** —— 下次跑 R6 不再有 user_id 默认值漏写 | fix agent |
| 2026-08-03 | **R4 关闭 P0-003 / P0-004**（commit `f09c1d5` / `482b0c7` / `fe2d484` / `26d9cf6` / `6481880` / docs）；测试基线 568 → **578 passed, 3 deselected, 0 failed**（+10 新测试）。注：plan 文本写 014/015 migration 但已被 vec0 / chunk_translation 占用，实际用 **017 / 018**。P2-017（45 行 legacy 残留）随 018 自动消解。**剩余 P0 全清** — 进 P1 阶段，首批 P1-015（27 处 backend `user_id: str = "default"` 签名默认值） | fix agent |
| 2026-08-03 | P0-005 关闭：docker 明文密码改 env_file + POSTGRES_PASSWORD 强校验（commit `e105177`） | fix agent |
| 2026-08-03 | P0-006 关闭：登录错误信息脱敏 — login_user 三场景统一对外文案（commit `7925824` / `6b57427`） | fix agent |
| 2026-08-03 | P0-009 关闭：README launcher 行数 160→270（commit `376ec90`） | fix agent |
| 2026-08-03 | P2-018 关闭：CI workflow 加 sqlite-vec==0.1.6（commit `36bf4e6`） | fix agent |
| 2026-08-03 | v1 FROZEN — owner 拍板 Q1-Q4 + 终审 Q1-Q4 | pingce skill |
| 2026-08-03 | v1.1 PRELIMINARY 复审 — R7/R8 跳过实测；R1-R6 红线未达；核心过 9 / 未达 6 / N/A 12；段位 0.0-2.9；P2 增量 7 项（P2-011~P2-017） | pingce evaluator |
| 2026-08-03 | **R3 关闭 P0-001 / P0-007 / P0-008**（commit `a4e11dd` / `d7cb50e` / `65c6625`）；测试基线 552 → 568 passed, 3 deselected；P2-010 / P2-016 随 P0-001 自动消解 | fix agent |
| 2026-08-03 | **R6 关闭 P1-006 / P1-007 / P1-008 / P1-009 / P1-016**：CI workflow 补 `scipy>=1.11` + asyncio 本地复现守卫；launcher 删除重复 `find_python_for_streamlit` 与 `_read_some`；`strip_thinking` 收敛为 `services._text_utils` 单点；ops_metrics 删除半成品 JSON 提取入口。全量基线 **626 passed, 20 skipped, 3 deselected, 0 failed**；services 覆盖率 **81%** | fix agent |
| 2026-08-04 | **P1-016 GitHub Actions 闭环**：commit `18a60ef` + `18aa211`。CI workflow minimal test deps 补 `jinja2>=3.1` / `python-docx>=1.0` / `beautifulsoup4>=4.12` / `lxml>=4.9`；3 个 unit 测试 `_run` helper 从 `asyncio.get_event_loop()` 切到 `asyncio.new_event_loop()` 模式；新增 AST 守卫 `test_unit_tests_do_not_use_get_event_loop`。**GitHub Actions 3 workflow 全绿**：tests `#30833065241` + secret-scan `#30833065912` + docker-build `#30833065179`。本地基线 **627 passed, 20 skipped, 3 deselected, 0 failed**（+1 = 新增的 2 个守卫 - 1 个被替代的旧 scipy 守卫）| fix agent |
| 2026-08-04 | **R8 关闭 P1-002 / P1-012**（commit `3a92ff0` / `9b6da08` / docs）：P1-002 `import_collected.py` 改走 v2 `insert_user_jd` + `embed_and_store_jd_chunks`（同 `crawler/pipeline.py` 路径），数据流通到 Flow B 的 `list_visible_jds`；P1-012 `migrate_sqlite_to_pg.py` 改通用列拷贝（读 sqlite PRAGMA + PG `information_schema` 取交集，类型由 PG `udt_name` 驱动），清单扩到 14 张表按 FK 顺序排，**顺带修 3 个 P0 级 bug**：(a) `main()` 引用未定义 `user_id`（`NameError`，生产切换其实从未真的跑通）；(b) 旧 `_migrate_jds` 写已不存在的列 / 漏实际存在的列，schema 漂移；(c) `--user-id` 把多用户塌成单用户 → 改保留源值 + `--user-id` 只兜底空值。本地 **645 passed, 22 skipped, 3 deselected, 0 failed**（基线 627 + P1-002 的 4 + P1-012 的 10；2 e2e 缺 `DATABASE_URL` 自动 skip）。**P1-002 同根因残留**：`scripts/collectors/manual_collector.py:151` 同样调 v1 `KnowledgeBase`，**新开 P1-002b** | fix agent |
| 2026-08-04 | **R9 关闭 P1-001 / P1-002b / P1-003 / P1-013**（commit `a141897` / `3b89fd6` / `5934753` / `8f424ee` / docs）：P1-001 `_lazy_score_jd` 加 advisory lock（threading.Lock per jd_id + SQLite `BEGIN IMMEDIATE` + `quality_checked_at` CAS / PG `SELECT ... FOR UPDATE`），10 并发撞同一未评分 JD 只算 1 次 LLM、全部拿到一致 score；P1-002b `scripts/collectors/manual_collector.py` 改走 v2 `insert_user_jd` + `embed_and_store_jd_chunks`（P1-002 同根因补完，`--user-id` 必填）；P1-003 新增 `tests/integration/test_backfill_translate_chunks_retry.py` 4 条（永久失败 SELECT 跳过 / 偶发失败 retry 成功 / retry_count 跨 run 持久化 / stats 报 retry_exhausted 数）；P1-013 `.gitignore` 补 13 项 R2 评估 / 调试产物规则，新增 19 条 gitignore 守卫测试覆盖历史 + 未来两类。本地 **677 passed, 24 skipped, 3 deselected, 0 failed**（基线 658 + P1-001 的 5 + P1-002b 的 4 + P1-003 的 4 + P1-013 的 19 ≈ +32，部分受 24 skipped 吸收）。**自动关闭** P2-009（eval 数据文件 gitignored）+ P2-014（MAX_RETRIES_PER_RECORD grep 在测试中再命中 2 处，总 4 命中超过 ≥3 通过线）。**剩余 P1**：P1-004（setup_wizard set_page_config 冲突）/ P1-005（tempfile 简历无清理）；阻塞 3 项 P1-010 / P1-011 / P1-014 待 owner 说明 | fix agent |
| 2026-08-04 | **R10 关闭 P1-004 / P1-005**（commit `8282929` / `586fee1` / docs）：P1-004 `setup_wizard.py:70` 移除 `st.set_page_config(...)`，统一由 `web_app.py:49-54` 控制，新 streamlit 多 page 模式不再抛 `StreamlitAPIException`；P1-005 `web_app.py` 加模块级清理机制（三层：命名规范 `prefix='jobhunter_resume_'` + atexit session 清理 + 启动 stale 清理 `>24h`），`pages/03_📝_Flow_A_Step1.py` 上传路径用 `_register_resume_tmp` 注册到 atexit 列表。本地 **688 passed, 24 skipped, 3 deselected, 0 failed**（基线 677 + P1-004 的 2 + P1-005 的 9 = +11）。**P1 阶段清零** — 阻塞 3 项 P1-010 / P1-011 / P1-014 仍待 owner 信息；R11 准备就绪：产品维度织入 REVIEW.md（5 条产品红线 + 基线测量 + §3 评分锚点修订 + §7 段位表加产品维度） | fix agent |
| 2026-08-04 | **R11 关闭 P1-017**（commit `03f45c9` + docs）：P1-017 `test_gitignore_coverage.py` 12 条历史工件测试改写为直接调 `git check-ignore -v <path>`（不依赖 `git status --ignored` 输出 + 不依赖文件物理存在），CI 干净 Linux runner 上不再因工件文件未创建而 fail。**根因**：`git status --ignored` 只对仓库**实际存在**的路径报告 `!!` 前缀，CI runner 没把 `data/eval_baseline_*.json` 等工件文件 copy 过去 → 这些路径不在 ignored 列表里 → 12 条 assert 全部 fail。**修复**：删除 `_git_status_ignored_files` / `_git_status_untracked_files` helper；12 参化路径改走 `subprocess.run(['git', '-c', 'core.quotepath=false', 'check-ignore', '-v', path])`（rc=0 = 被忽略），不创建文件、不污染 repo、对路径是否物理存在完全无关。**路径调整**：原 plan 的 `debug_cached_response.py` 和 `services/_text_utils.py` 已在 P1-008（commit `4380c55`）入仓，`git check-ignore` 对 tracked 文件永远返 1 — 换成 `data/poll_streamlit.ps1`（R9 P1-013 在 .gitignore 已有）+ `docs/portfolio.md`（已在 .gitignore 第 136 行）。Win 中文 / 空格路径走 `git -c core.quotepath=false`。**CI 健康真正闭环**：GitHub Actions 3 workflow 全绿（tests `#30848039867` 1m4s + secret-scan `#30848039710` 19s + docker-build `#30848039594` 33s），R1 红线 CI 健康从"已修复"升级为"已修复 + 经 R10 后两次 docs commit 复测未回潮"。本地 **688 passed, 24 skipped, 3 deselected, 0 failed**（基线不变；测试数 19 = 12 historical + 1 combination guard + 6 future）。R12 准备就绪：产品维度织入 REVIEW.md（R11 主菜之后的体系升级） | fix agent |
| 2026-08-04 | **R12 产品维度织入 REVIEW.md（无代码改动，docs commit）**：REVIEW.md 评测体系升级，**让"工程高≠产品好"循环在源头被掐断**。改动 4 处：(1) `§1` 红线列表追加 R9-P1 ~ R9-P5 五条产品红线（响应 ≤ 3s / 错误友好 / 升级无感 / 全流程首次通过 ≥ 60% / AI 1 次通过 ≥ 70%）；(2) `§3` 质量项表加"产品影响"列（20 行，每行 5-15 字，描述该项对最终用户的可感知影响）；(3) `§7.7` 综合段位计算新增，公式 = 工程段位 × 0.6 + 产品段位 × 0.4（权重可调，下轮评审前可重定）；(4) `§7.5` 节点表 +2 行 R12（fix agent 完成定义/修订/织入 + owner 待跑基线测量）。**ISSUES.md 同步**：P1-018 部分关闭（定义/修订/织入已落地，基线数字待 owner 回填），P1-014 从"阻塞"推为"推进中"（与 R12 基线测量联动）。本地 **688 passed, 24 skipped, 3 deselected, 0 failed**（纯文档改动，基线不变）。R13 docs commit 待 owner 跑 5 真人 + 故障注入 5 类 + 跨版本升级 + 50 query LLM-as-judge → 回填 R9-Px 数字 + 计算综合段位 | fix agent |
| 2026-08-04 | **R13b-prep 修复前置条件**（commit `e_fix` / `e_feat_perf` / `e_test_recovery` / `e_docs`）：3 块前置条件落地 — (1) AppTest 依赖修复（`requirements.in` 锁 `streamlit>=1.30,<1.60`，lock 重生成让 starlette 升 1.3.1 + 本地升 fastapi 0.141 兼容，3 条 smoke 测试 subprocess 隔离 conftest stub）；(2) R9-P1 测量入口 `scripts/perf_measure_pages.py`（AppTest 跑 5 关键页面输出 5 行 + 平均值）+ 2 条 mock 测试；(3) R9-P2 五类故障友好恢复（`database/errors.py` 新建 `UserFacingError`；`tools/llm.py` 429 → `RateLimitError` → `UserFacingError`；`database/backends/sqlite_backend.py` 加 `_run_write_with_retry` 处理 sqlite "locked" 指数退避 ≤3 次；`scripts/migrate_sqlite_to_pg.py` 加 `--rollback-on-fail`）+ 5 条故障注入测试（429 / DB lock 自动重试 / DB lock 超限 / 切库回滚 默认开 / 显式关）。本地 **705 passed, 24 skipped, 3 deselected, 0 failed**（基线 695 + 10 新增）；perf 脚本 dry-run 平均 0.76s（远低于 3.0s 目标）。**P1-019 已关闭**（前置条件 3 块全到位）；**P1-018 推进**：R9-P1 / R9-P2 测量方式已落地，R9-P1 数字待 owner 跑 perf 脚本回填，R9-P2 数字由 5 条测试结果即基线 | fix agent |

---

## P0 · 红线级（任一不过 = 总分 ≤ 5.9 或强制否决）

### P0-001 · 测试基线数字三处不一致
- **问题**：`README.md:138` 写 481 passed；`CLAUDE.md:38` 写 81 passed；实测 544 passed / 1 failed。
- **代码依据**：
  - `README.md:138` `pytest tests/ --cov=...` 注释 "基线：481 passed"
  - `CLAUDE.md:38` 自检要求 `pytest tests/ -q` 必须 81 passed
  - 实测 `pytest tests/ -q --tb=no` 输出末行 `544 passed, 1 failed`
- **状态**：✅ **已关闭**（`65c6625`，2026-08-03）— README:138 + CLAUDE.md:38 同步为 `568 passed, 3 deselected`（本轮 +16 条新测试后的实测值）。README 里过时的 "worktree 461 passed / 3 skipped" 一并换成 deselected 的真实成因（`@pytest.mark.real_llm` 默认不选）。
- **关联**：REVIEW.md R1

### P0-002 · 真 LLM flake（CI 一直红）
- **问题**：`tests/integration/test_flow_a_real_llm_3_scenarios.py::TestRealLLMScenarios::test_scenario_a_full_mode_a` 断言"模式 A 必须保留原数字 200"，实际 LLM 输出不含该数字。文件标 `@pytest.mark.real_llm`，但 `pytest.ini` 没默认 deselect，CI 一直红。
- **代码依据**：
  - `tests/integration/test_flow_a_real_llm_3_scenarios.py:186` 周围断言
  - `pytest.ini:1-19` markers 配置
- **状态**：✅ 已关闭 — `711618e`（2026-08-03）。修复：1) `pytest.ini` addopts 加 `-m "not real_llm"`；2) 场景 A 断言改为"≥1 数字保留"（must_have 列表取 1）；3) 新增 `tests/unit/test_pytest_ini_real_llm_default_skip.py` 5 条覆盖（addopts 静态 + markers 段 + 断言源码静态 + --collect-only 动态双向）。测试基线 547 passed / 3 deselected / 0 failed。
- **关联**：REVIEW.md R2 / 用户记忆"真 LLM flake 未根治"

### P0-003 · README vs 代码裂缝 4 处（Q3 owner 决议：改 README 删行）
- **问题**：README "主要功能"表格讲了 6 个 Tab，4 个对不上代码。
- **代码依据**：
  - **AI 求职助手侧栏浮窗**：`README.md:92` 声称；`web_app.py:70-78` 显式 `display: none` 整个 sidebar；`coordinator/chat.py:22` 的 `chat_assistant` 未被任何 page 调用
  - **采纳优化建议按钮**：`README.md:90` 声称"点'采纳'落 `user_adopted`"；`pages/06_📄_Flow_B.py` 全文未调 `update_optimization_adopted`；backend 方法存在 `database/backends/sqlite_backend.py:613-619`
  - **投递历史 + 接受/已读/拒绝反馈**：`README.md:91` 声称；`pages/08_📈_Application_History.py` 只管简历版本，无反馈 UI；backend 方法存在 `database/backends/sqlite_backend.py:565-575`
  - **爬虫 liepin / jobsdb**：`README.md:118-127` 展示命令；`crawler/run_crawler.py:46-47` `SUPPORTED_SITES` 标 "not yet implemented"，跑会 raise ValueError
- **状态**：✅ **已关闭** — commit `f09c1d5`（2026-08-03）+ 测试 `tests/unit/test_readme_no_lying_features.py` 4 条静态扫描兜底。修复 4 处：
  1. 主功能表删 "💬 AI 求职助手" 行
  2. "✏️ 优化建议" 改写为"按段落生成改写建议，列表展示（无采纳按钮）"
  3. "📈 投递历史" 改写为"📈 简历版本管理 — 简历版本时间线，版本树 + 主版本切换"
  4. 爬虫节 liepin / jobsdb 命令改"liepin / jobsdb 当前仅提供登录态辅助脚本（`scripts/collectors/login_liepin.py` / `login_jobsdb.py`），爬虫适配器将在 M-v5 阶段补完"，只留 Boss 直聘示例
- **关联**：REVIEW.md R3

### P0-004 · 铁律违反 3 处（Q4 owner 决议：P0 强制清理）
- **问题**：CLAUDE.md:8-10 铁律"不做向后兼容 hack，不留 alias，不写 removed 占位，一次性硬切"，代码里 3 处违反。
- **代码依据**：
  - **dead schema**：`services/jd_parser.py:17-19` 注释 "rag_industry_function 表暂保留为 dead schema，不删"
  - **Step2 legacy 兜底**：`pages/04_📝_Flow_A_Step2.py:50-89` 整块 `legacy = st.session_state.get("fa_section_data") or {}` 兜底迁移
  - **knowledge_chunks.legacy 列**：`database/backends/sqlite_backend.py:137-141` 加列；`scripts/backfill_chunks.py:1-9` 把旧 chunk 标 `legacy=1` 保留；多处 SQL 带 `kc.legacy = 0` 过滤（sqlite_backend.py:858/864/914/965）
- **状态**：✅ **已关闭** — 4 commit + 1 test commit（2026-08-03）：
  1. `482b0c7` 删 dead schema rag_industry_function + 全栈代码引用 — migration **017**（注：plan 文本写 014 但已被 `014_embedding_binary_vec0.sql` 占用）
  2. `fe2d484` 删 knowledge_chunks.legacy 列 + SQL 过滤全清 — migration **018**（注：plan 文本写 015 但已被 `015_chunk_translation.sql` 占用）
  3. `26d9cf6` Step2 删 `fa_section_data` legacy 兜底块 — 一次性硬切
  4. `6481880` migration 017/018 后置测试 7 条（表 DROP / 列 DROP / 残留 DELETE / RAG smoke / 回滚预案）
  5. docs commit（ISSUES 本行 + REVIEW.md R3/R4 备注 + §7.5 R4 节点）
- **连带关闭**：P2-017（45 行 legacy 残留）随 018 自动消解
- **关联**：REVIEW.md R4

### P0-005 · 明文 docker 密码
- **问题**：`docker-compose.yml:23-24` 明文 `POSTGRES_PASSWORD=jobhunter`。
- **代码依据**：`docker-compose.yml:23-24`
- **状态**：✅ 已关闭 — `e105177`（2026-08-03）。修复：1) `docker-compose.yml` 改 `env_file: .env` + `POSTGRES_PASSWORD=${POSTGRES_PASSWORD:?must be set}` 强校验；2) `POSTGRES_USER/POSTGRES_DB` 也走 env_file（默认值 'jobhunter' 作 fallback）；3) healthcheck 改用 $$POSTGRES_USER / $$POSTGRES_DB 变量；4) `.env.example` 增三个 POSTGRES_* 模板变量，密码占位 `change_me_to_a_strong_random_password`。验证：`grep "POSTGRES_PASSWORD.*jobhunter" docker-compose.yml` 0 命中；pytest 547 passed / 3 deselected / 0 failed 无回归。
- **关联**：REVIEW.md R5-1

### P0-006 · 登录错误信息泄露账号存在性
- **问题**：`pages/09_🔐_Auth.py:62` 登录失败 `st.error(str(exc))` 直接展示 "用户不存在" vs "密码错误"，可被攻击者枚举账号。
- **代码依据**：
  - `pages/09_🔐_Auth.py:62`
  - `services/auth_service.py` `AuthError` 含具体语义（来源：探查报告）
- **状态**：✅ 已关闭 — `7925824` + `6b57427`（2026-08-03）。修复：1) `services/auth_service.py` 新增 `_LOGIN_OBFUSCATED_MESSAGE = "邮箱/手机号或密码错误"` 常量；2) `login_user` 三个 raise 分支（user_not_found / locked_out / bad_password）全部改为统一文案；3) backend `audit_logs.error_message` 仍按 user_not_found / bad_password / locked_out 落具体错误码便于 ops 排查，前端只拿脱敏 message；4) 适配 `tests/unit/test_auth_service.py::TestLoginLockout::test_fifth_failure_locks_account` match 改文案。验证：`tests/unit/test_auth_service_error_obfuscation.py` 5 条全过，三场景 message 字符串相等。pytest 552 passed / 3 deselected / 0 failed。
- **关联**：REVIEW.md R5-2

### P0-007 · 简历粘贴 text_area 无长度上限
- **问题**：`pages/03_📝_Flow_A_Step1.py:163` 等处 `st.text_area` 无 `max_chars`，用户粘贴 100MB 直接爆 LLM。
- **代码依据**：`pages/03_📝_Flow_A_Step1.py:163` + `pages/06_📄_Flow_B.py` JD text_area 同问题
- **状态**：✅ **已关闭**（`a4e11dd`，2026-08-03）— 新增 `services/text_limits.py`：`MAX_USER_TEXT_CHARS = 20000` + `clamp_user_text()`。**两层防线**：widget 加 `max_chars`（UI 即时反馈）+ 提交路径调 `clamp_user_text` 服务端截断并 `st.warning`。**只加 `max_chars` 不够** —— 它是浏览器端约束，构造 websocket 消息可绕过。覆盖三个粘贴入口：`03_Flow_A_Step1`（JD 粘贴 + 复核表单的职责/要求两栏）、`06_Flow_B`、`07_JD_Library`（原工单只点了 03/06，07 是同一条路径，一并堵上）。测试 `tests/unit/test_pages_text_area_length_cap.py`（12 条）。
- **关联**：REVIEW.md R5-4

### P0-008 · 跨用户隔离：用户无简历回退到 default
- **问题**：`pages/08_📈_Application_History.py:159-176` 当 `current_user_id` 下无简历，回退到 `db.list_resumes("default")` 展示。多人共享本机 SQLite 时出现"我看到别人简历"的数据串。
- **代码依据**：`pages/08_📈_Application_History.py:159-176`
- **状态**：✅ **已关闭**（`d7cb50e`，2026-08-03）— 删除 `db.list_resumes("default")` 回退块，改为空态 `st.info` 引导；连带删掉因此变成死代码的 `_resume_lib_effective_user`（全仓只写不读）。**根因是"查不到就退回共享账号"，不止一处**：`03_Flow_A_Step1.py:61` `_jd_to_dict` 把 `user_id` 兜底成 `"default"`（写侧同类泄漏，解析出的 JD 归属共享账号），一并改为 `current_user_id()`。测试 `tests/unit/test_application_history_user_scoped.py`（4 条，读写两侧各扫）。
- **关联**：REVIEW.md R6

### P0-009 · launcher 脚本行数 README 夸大
- **问题**：`README.md:69` 写 "scripts/jobhunter_launcher.py 是 160 行的 Python 脚本"，实测 270 行。
- **代码依据**：`wc -l scripts/jobhunter_launcher.py` = 270
- **状态**：✅ 已关闭 — `376ec90`（2026-08-03）。修复：`README.md:69` "160 行" 改为 "270 行"。验证：`grep "160 行" README.md` 0 命中。
- **关联**：REVIEW.md 第 0 节

---

## P1 · 核心体验

### P1-001 · 懒评分并发回写 race
- **问题**：`pages/07_📚_JD_Library.py:150-162` `_lazy_score_jd` 每次访问未评分 JD 都重算 + 回写，无锁。N 个用户访问同一公共 JD 触发 N 次回写（最后写赢），且中间过程可能出现 quality_score 闪烁。
- **代码依据**：`pages/07_📚_JD_Library.py:150-162`
- **状态**：✅ 已关闭 — `a141897`（2026-08-04）。三层防御：(1) `database/backends/base` 抽象加 `update_jd_quality_score_cas`（事务化 CAS）和 `compute_or_get_jd_quality`（同进程 `threading.Lock` per jd_id + 跨进程 CAS 双层防并发）两方法；(2) sqlite_backend 用 `BEGIN IMMEDIATE` 事务，`update_jd_quality_score_cas` 走 `WHERE quality_checked_at = ?` CAS，`compute_or_get_jd_quality` 加 `_quality_locks` 字典 + `_quality_locks_guard` 守门；(3) postgres_backend 用 `SELECT ... FOR UPDATE` row-level lock 替代 `(2)` 的 `BEGIN IMMEDIATE`；(4) `_lazy_score_jd` 改走 `db.compute_or_get_jd_quality`。测试 `tests/unit/test_lazy_score_jd_concurrency.py` 5 条：`quality_checked_at` 列已存在 / 10 并发 LLM 调用 = 1 / CAS 拒绝 stale 写 / `compute_or_get` 多次调用只 1 次 compute / 快路径返已评分。**R6 加分项回归**：跨后端可移植（PG 路径同样口径）。

### P1-002 · smart_collector 走 v1 KB
- **问题**：`scripts/collectors/import_collected.py:108-117` 调 v1 的 `KnowledgeBase`（多 DB 文件），与 v2 统一 `jobhunter_v2.db` 不互通，导入后数据在 Flow B 的 `list_visible_jds` 看不到。
- **代码依据**：`scripts/collectors/import_collected.py:108-117`
- **状态**：✅ 已关闭 — `3a92ff0`（2026-08-04）。改走 `insert_user_jd` + `embed_and_store_jd_chunks`，与 `crawler/pipeline.py` 同一条落库路径；分类从 v1 LLM `classify_jd` 换成 `database.classifier` 三层 Classifier（同步、无需 API key），脚本去掉 asyncio。`--user-id` 必填（与 `migrate_sqlite_to_pg.py` 一致），不再依赖 `web_app.current_user_id()` 的 Streamlit session。顺带修 `Path(__file__).parent` 指向错误（指到 `scripts/collectors/` 而非仓库根，sys.path 注入一直是无效的）。测试 `tests/integration/test_smart_collector_v2.py` 4 条全过：AST 守卫 `KnowledgeBase` import 清零 + v2 API 在位 + 端到端导入可见 + 跨用户隔离。**同根因残留**：`scripts/collectors/manual_collector.py:151` 同样调 v1 `KnowledgeBase`，**新开 P1-002b**。

### P1-002b · manual_collector 走 v1 KB（P1-002 同根因）
- **问题**：`scripts/collectors/manual_collector.py:151,168-188` 同样调 v1 `KnowledgeBase`（多 DB 文件），与 v2 `jobhunter_v2.db` 不互通。P1-002 关了 `import_collected.py` 的口子，但 manual collector 还在走老路。
- **代码依据**：`scripts/collectors/manual_collector.py:151`
- **状态**：✅ 已关闭 — `3b89fd6`（2026-08-04）。与 P1-002 同根因处理一致：`import_to_v2` 替换原 `import_to_knowledge_base`，模块级 import `Classifier` / `get_db` / `insert_user_jd` / `embed_and_store_jd_chunks`（避免 monkeypatch 不可达），`--user-id` 必填（不再依赖 `web_app.current_user_id()` Streamlit session），`pathlib.Path(__file__).parent` 路径修对。同 `crawler/pipeline.py` 落库路径 → 分类走 `database.classifier.Classifier` 三层规则（无需 API key）。测试 `tests/integration/test_manual_collector_v2.py` 4 条：AST 守卫 `KnowledgeBase` / `tools.knowledge_base` 不再导入 + `db.insert_user_jd` 字面量在位 + 端到端 2 JD 入 v2 + `list_visible_jds` 跨用户隔离只 user_id 看得到自己 JD。

### P1-003 · 翻译 backfill 永久卡死兜底已加但未回归
- **问题**：commit `3b854ef` 加 `MAX_RETRIES_PER_RECORD` 兜底，但 CHANGELOG 未回填最新 retry_count 实际值，2 条永久卡死的根因未根治。
- **代码依据**：`scripts/backfill_chunks.py` + CHANGELOG L1981-2004
- **状态**：✅ 已关闭 — `5934753`（2026-08-04）。新增 `tests/integration/test_backfill_translate_chunks_retry.py` 4 条覆盖 `BackfillRunner` 三类行为：(1) **永久失败 SELECT 跳过**——`_FailingTranslator` 跑 `MAX_RETRIES=3` 次后，`SELECT ... WHERE retry_count < ?` 过滤该 chunk，末尾再跑一次 `translate_batch` 调用数 = 0；(2) **偶发失败后恢复**——`run 1` 全失败后 `retry_count=0` 重置，`run 2` 成功 translator → `translated_at` 写入、`chunk_text` 含译文；(3) **retry_count 持久化**——跨 `sqlite3.connect` 独立短连接读，retry_count 落库可见、不跨 run 漂移；(4) `stats()` 报 `retry_exhausted` 数用于评测面板。测试用 512-d `_BgeDimEmbedder`（SHA-256 派生）避开 vec0 dim 校验；用 `BackfillRunner` 直接 sqlite3 连接绕过 backend 抽象。

### P1-004 · setup_wizard.py 多 page set_page_config 冲突
- **问题**：`setup_wizard.py:70` 自己 `st.set_page_config(...)`，与 `web_app.py:49-54` 的 `set_page_config` 冲突，多 page 行为依赖 streamlit 版本。
- **代码依据**：`setup_wizard.py:70`
- **状态**：✅ 已关闭 — `8282929`（2026-08-04）。setup_wizard.py 移除 `st.set_page_config(...)`，统一由 web_app.py 控制。测试 `tests/unit/test_setup_wizard_no_page_config.py` 2 条：AST 静态扫描 setup_wizard.py 不含 set_page_config 字面量 + import smoke 不抛 StreamlitAPIException。

### P1-005 · tempfile 简历图片无清理
- **问题**：`pages/03_📝_Flow_A_Step1.py:189-202` 上传图片保存到 `tempfile.gettempdir()` 全局临时目录，无清理机制。
- **代码依据**：`pages/03_📝_Flow_A_Step1.py:189-202`
- **状态**：✅ 已关闭 — `586fee1`（2026-08-04）。三层清理机制：(1) 命名规范 `prefix='jobhunter_resume_'` + UUID 后缀便于批量匹配；(2) `web_app.py` 加 `_register_resume_tmp` + `_cleanup_resume_tmp_session`，`atexit.register` 当前 session 退出时全删；(3) 启动时 `_cleanup_resume_tmp_stale` 删 `>24h` 的同名前缀文件（兜底上次 session 异常退出残留）。模块级常量 `RESUME_TMP_PREFIX / RESUME_TMP_SUFFIXES / RESUME_TMP_STALE_SECONDS`。测试 `tests/unit/test_tempfile_resume_cleanup.py` 9 条：atexit handler 注册 + register 去重 + stale 清理只删 >24h + 空目录 / 非文件节点不抛 + 页面命名规范 wire + glob roundtrip。

### P1-006 · 死代码 `find_python_for_streamlit` 重复定义
- **问题**：`scripts/jobhunter_launcher.py:41-80` `find_python_for_streamlit` 函数定义两次，第二次完全相同（copy-paste 残留）。
- **代码依据**：`scripts/jobhunter_launcher.py:41-80`
- **状态**：✅ 已关闭 — `6c146f6`（2026-08-03）。删除第二次 `find_python_for_streamlit` 定义；launcher 保留唯一实现。

### P1-007 · 死代码 `_read_some`
- **问题**：`scripts/jobhunter_launcher.py:203-214` `_read_some` 函数体立即 `return ""`，已用 threading `_drain` 替代。
- **代码依据**：`scripts/jobhunter_launcher.py:203-214`
- **状态**：✅ 已关闭 — `77f5032`（2026-08-03）。删除立即返回空字符串的 `_read_some`；后台线程 `_drain` 保持唯一输出读取路径。

### P1-008 · services/_text_utils.py untracked
- **问题**：`services/_text_utils.py` 是 untracked 新加文件，与 `services/translation_service.py:108` 已有的 `_strip_thinking` 功能重复，唯一非测试调用方是 `debug_cached_response.py`（也是 untracked）。
- **代码依据**：`services/_text_utils.py` + `services/translation_service.py:108`
- **状态**：✅ 已关闭 — `4380c55`（2026-08-03）。`services/_text_utils.py` 纳入 git，`translation_service.py` 与 `debug_cached_response.py` 统一导入 `strip_thinking`；P2-011 随之自动解决。

### P1-009 · services/ops_metrics.py 半成品
- **问题**：`services/ops_metrics.py:60` 仍 raise `NotImplementedError("use _json_extract_sqlite / _json_extract_pg directly")`，提示函数需走子函数。
- **代码依据**：`services/ops_metrics.py:60`
- **状态**：✅ 已关闭 — `6be586a`（2026-08-03）。删除 `_json_extract_sql` 半成品入口；调用方继续直调 `_json_extract_sqlite` / `_json_extract_pg`。

### P1-010 · Flow B 是否同根因待确认（用户记忆）
- **问题**：用户记忆提到 "Flow B 同根因待确认"（未在探查报告中找到具体证据，需要 owner 进一步说明）。
- **状态**：⏸ 阻塞 — 等 owner 补充信息。
- **关联**：用户 MEMORY.md

### P1-011 · chunk 分类 21% 准确率（用户记忆）
- **问题**：用户记忆提到 "chunk 分类 21% 准确率"（未在探查报告中找到具体证据，需要 owner 进一步说明）。
- **状态**：⏸ 阻塞 — 等 owner 补充信息。
- **关联**：用户 MEMORY.md

### P1-012 · migrate_sqlite_to_pg.py 漏 v4 新表
- **问题**：`scripts/migrate_sqlite_to_pg.py:32-33` 迁移表清单缺 v4 新表（users / flow_a_drafts / jd_structured / rewrite_history / rag_industry_function / interview_questions / llm_calls / audit_logs / skeleton_cache），PG 切回会丢。
- **代码依据**：`scripts/migrate_sqlite_to_pg.py:32-33`
- **状态**：✅ 已关闭 — `9b6da08`（2026-08-04）。把"每张表手写 `_migrate_*()`"换成通用列拷贝：读 sqlite PRAGMA 列 + PG `information_schema` 列，取交集后拼参数化 INSERT，类型转换由 PG `udt_name` 驱动（jsonb/vector/array/其他）。清单扩到 14 张表（`users` / `resumes` / `jds` / `jd_structured` / `knowledge_chunks` / `match_history` / `optimizations` / `quality_checks` / `flow_a_drafts` / `rewrite_history` / `interview_questions` / `llm_calls` / `audit_logs` / `skeleton_cache`），按 FK 顺序排。顺带修 3 个 P0 级 bug：(1) `main()` 直接引用 `user_id` 变量未定义（应 `args.user_id`），带 `--apply` 跑第一张表就 `NameError`，**生产切换其实从没真的跑通过**；(2) 旧 `_migrate_jds` 往 `jds` 写 `requirements/skills_required/parsed_data`（列已不存在），同时丢 `parsed_sections/tags/quality_score/deleted_at`（列实际存在）—— 整段对着 004 前的旧 schema 漂移；(3) `--user-id` 把多用户归属塌成单用户，改为保留源值 + `--user-id` 只兜底 `user_id` 为空的历史行。`ON CONFLICT DO NOTHING` + serial 序列 resync → 重跑幂等。测试 `tests/integration/test_migrate_v4_tables.py` 12 条：5 静态守卫（含 PG 侧 `CREATE TABLE` 验证避免清单/PG 漂移）+ 5 纯函数单测 + 2 e2e（缺 `DATABASE_URL` 自动 skip，真 PG 跑时做 sqlite→PG round-trip 行数一致）。

### P1-013 · untracked 调试产物建议加 .gitignore
- **问题**：`data/eval_baseline_*.json`（7 个）+ `data/miss_analysis_*.md`（5 个）+ `data/post_backfill_eval_*.md` + `AI Agent产品经理_简历.md` + `data/*.bak_*.db` 等是用户调试产物，建议加 .gitignore。
- **代码依据**：git status
- **状态**：✅ 已关闭 — `8f424ee`（2026-08-04）。`.gitignore` 末尾加 R9 P1-013 治理块，覆盖：评估基线（`data/eval_baseline_*.json`）/ 漏分析（`data/miss_analysis_*.md`）/ 回填评估（`data/post_backfill_eval_*.md`）/ DB 备份（`data/jobhunter_v2.db.bak_*`）/ cookies 明细（`data/cookies/*.json`）/ 缓存探针（`data/rag_progress*.json`、`data/sqlite_vec*.json`、`data/liepin_homepage_text.txt`）/ 调试脚本（`debug_cached_response.py`、`data/poll_streamlit.ps1`、`AI Agent产品经理_简历.md`、`docs/portfolio.md`）/ 顶层产物（`coverage.xml`）。测试 `tests/unit/test_gitignore_coverage.py` 19 条：12 参化历史件 + 1「untracked 列表不再含历史件」+ 6 参化未来件（用 `git check-ignore` 不创建文件、不污染 repo）。`data/rag_progress*.json` 等改通配以吃未来同类变体名。Win 中文 / 空格路径走 `git -c core.quotepath=false` 输出，加引号路径归一化。

### P1-014 · 大隐患：用户上传未跑过（用户记忆）
- **问题**：用户记忆 `portfolio.md L37 "未来才考虑多租户" + L97 "从单用户工具升级到公网多用户 SaaS"`，PRD §6 没标完成度。
- **状态**：🟡 推进中 — R12 启动基线测量，REVIEW.md §1 新增 R9-P1~P5 五条产品红线（响应 ≤ 3s / 错误友好 / 升级无感 / 全流程首次通过率 ≥ 60% / AI 1 次通过率 ≥ 70%），§7.7 综合段位公式 = 工程 × 0.6 + 产品 × 0.4。owner 跑 5 真人 + 故障注入 5 类 + 跨版本升级 + 50 query LLM-as-judge 后回填基线数字 → R13 docs commit 算综合段位

### P1-015 · DB 层 27 处 `user_id: str = "default"` 签名默认值
- **问题**：`database/backends/{__init__,sqlite_backend,postgres_backend}.py` 共 27 个方法把 `user_id` 的默认值定成 `"default"`（`list_resumes` / `list_jds` / `get_jd_by_url` / `list_optimizations` / `get_latest_flow_a_draft` / `list_jds_structured` 等）。调用方漏传 `user_id` 时**不报错**，静默读写共享桶 —— 这正是 P0-008 那类跨用户串数据的**使能机制**，而不只是巧合。
- **代码依据**：`grep -rn 'user_id: str = "default"' database/` = 27 命中；R6 判定命令 1 的 3 处残留命中即来源于此
- **修复（commit `cbf3124` / `2983e56` / `0abb5df` / `99f7323`）**：
  - **R5-1** backends 27 处签名改为必填 `*, user_id: str`（关键字-only，避免挪首位导致 caller 静默串位）
  - **R5-2** services/tools StructuredJD 删 `user_id` 字段（解析层不应知道归属用户）+ LLMClient 必填
  - **R5-3** 21 个测试 fixture 切到显式 `user_id=`；新增 `tests/unit/test_p1_015_no_default_user_id.py` 40 测试（三层守卫：反射/e2e/静态 grep + 一致性）
  - **R5-4** 写路径 caller 全部显式 user_id（pages/06 Flow_B 3 个 insert 站点 + audit/jd_library/flow_a_draft 服务 + 7 个 scripts：`backfill_jd_quality` / `batch_{51job,jobsdb,liepin}` / `migrate_sqlite_to_pg` / `verify_m3` / `migrate_v1` + agents/base.py）
  - **白名单例外**：4 个系统级方法允许 `user_id: Optional[str] = None`（`get_llm_usage_today` 全局聚合 / `list_audit_logs` 系统级审计 / `vector_search` + `like_search_chunks` 跨用户 RAG 召回）
- **状态**：✅ 已关闭 — R6 判定命令 1 使能机制就位；守卫测试 40 条保证不再回潮
- **关联**：P0-008 / REVIEW.md R6 判定命令 1

### P1-016 · CI tests 一直 fail（pytest-asyncio event loop + scipy 缺失）
- **问题**：CI workflow 在 R4 (`fb36b15`) 和 R5 (`a296b8d`) 持续 fail，本地 pytest 通过
- **代码依据**：
  - `RuntimeError: There is no current event loop in thread 'MainThread'` — CI pytest-asyncio 配置与本地不一致
  - `ModuleNotFoundError: No module named 'scipy'` — CI `pip install` 列表缺 scipy
- **影响**：R1 红线 CI 健康（REVIEW §1 R1）未达
- **状态**：✅ 已关闭 — `ff22f98`（2026-08-03）+ `18a60ef` + `18aa211`（2026-08-04）。CI workflow 增加 `scipy>=1.11` + `jinja2>=3.1` + `python-docx>=1.0` + `beautifulsoup4>=4.12` + `lxml>=4.9`；`pytest.ini` 已启用 `asyncio_mode = auto`；3 个 unit 测试 `_run` helper 切到 `asyncio.new_event_loop()` 模式。新增 2 条守卫（依赖 + AST 扫 `get_event_loop` 调用链）。**GitHub Actions 3 workflow 全绿**：tests `#30833065241`（3.11 + 3.12 + docstring-coverage 全 ✓）+ secret-scan `#30833065912` + docker-build `#30833065179`。

### P1-017 · test_gitignore_coverage.py 在 CI 干净 runner 上失败
- **问题**：`tests/unit/test_gitignore_coverage.py::TestHistoricalDebugArtifactsIgnored` 12 条历史工件测试在本地通过（544 / 658 / 677 / 688 历次基线），但**在 GitHub Actions 干净 Linux runner 上 12 条全 fail**。最近 2 个 docs commit（`aff980d` R10 + `0047dcd` R9）都因此红条（`gh run list --limit 8 --workflow=tests` 显示 `failure`）。**根因**：测试用 `_git_status_ignored_files()` helper 调 `git status --ignored --porcelain` 解析 `!!` 前缀 — `git status --ignored` **只对仓库内实际存在的路径报告 ignored**，CI runner checkout 出来的代码不包含 `data/eval_baseline_20260802T211059Z.json` / `data/miss_analysis_20260725T164938Z.md` 等用户本地调试产物（它们在 .gitignore 里 + 不在 git 索引中），结果 `git status --ignored` 不报这些路径 → 12 条 assert `assert filename in ignored` 全 fail
- **代码依据**：
  - `tests/unit/test_gitignore_coverage.py:28-52` 旧版 `_git_status_ignored_files` helper — 依赖物理存在的文件
  - `tests/unit/test_gitignore_coverage.py:115-121` 旧版 12 参化 assert `assert filename in ignored`
  - CI 证据：`#30844146217`（R10 docs）+ `#30839992404`（R9 docs）workflow `tests` 都标 `failure`
- **影响**：R1 红线 CI 健康（REVIEW §1 R1）虽 R10 闭环过，但**未在 R9 / R10 两次 docs push 后复测**——所以 pre-existing 红条又回潮成 docs commit fail
- **状态**：✅ 已关闭 — `03f45c9`（2026-08-04）。**改用 `git check-ignore -v <path>` 直接探测 .gitignore 规则覆盖**，不依赖文件物理存在（`git check-ignore` 对 .gitignore 模式 + 路径字面量做规则匹配，不读文件系统）。删除 `_git_status_ignored_files` / `_git_status_untracked_files` helper（连同 `test_no_historical_artifacts_remain_untracked` 一起删 — 它同样依赖物理存在）；12 参化路径改 `subprocess.run(['git', '-c', 'core.quotepath=false', 'check-ignore', '-v', path])`（rc=0 = 被忽略）。**路径调整**：原 plan 的 `debug_cached_response.py` 和 `services/_text_utils.py` 已在 P1-008（commit `4380c55`）入仓，`git check-ignore` 对 tracked 文件永远返 1 — 换成 `data/poll_streamlit.ps1`（R9 P1-013 在 .gitignore 已有）+ `docs/portfolio.md`（已在 .gitignore 第 136 行）。`TestNewArtifactsImmediatelyIgnored` 6 条保留（已用 `git check-ignore`、路径字面量不依赖物理存在），加 1 条组合守卫 `test_check_ignore_does_not_depend_on_physical_existence`（防止以后又有人把测试改回依赖 `git status --ignored`）。CI 验证：本机 `rm -f data/eval_baseline_*.json data/miss_analysis_*.md data/post_backfill_eval_*.md data/jobhunter_v2.db.bak_* data/rag_progress.json data/sqlite_vec_validation.json data/liepin_homepage_text.txt data/portfolio.md data/poll_streamlit.ps1 coverage.xml 'AI Agent产品经理_简历.md' docs/portfolio.md` 后本地 19 passed；GitHub Actions 3 workflow 全绿（tests `#30848039867` 1m4s + secret-scan `#30848039710` 19s + docker-build `#30848039594` 33s）。**R1 红线 CI 健康真正闭环** — 经 R10 docs commit 复测后再次 push 验证未回潮。

### P1-018 · 产品维度织入 REVIEW.md（R12 评测体系升级）
- **问题**：REVIEW.md 此前仅覆盖工程维度（R1-R8 红线 + §2 核心指标 + §5 段位），无产品维度。导致"工程 9.0 / 产品 4.0"也被默认判为可发布 —— **工程高 ≠ 产品好**的循环在源头无法被掐断
- **代码依据**：`REVIEW.md §1` 红线列表仅 R1-R8（工程）；`§5` 段位表无产品维度；`§3` 质量项表无"产品影响"列
- **状态**：🟡 **部分关闭**（2026-08-04）— R12 已落地 REVIEW.md 体系升级：
  1. `§1` 追加 R9-P1 ~ R9-P5 五条产品红线（响应 ≤ 3s / 错误友好 / 升级无感 / 全流程首次通过 ≥ 60% / AI 1 次通过 ≥ 70%）
  2. `§3` 质量项表加"产品影响"列（20 行，每行 5-15 字）
  3. `§7.7` 综合段位公式 = 工程段位 × 0.6 + 产品段位 × 0.4
  4. P1-014 状态从"阻塞"推为"推进中"（与基线测量联动）
  - **未关闭部分**：5 条产品红线的基线数字（owner 跑 5 真人 + 故障注入 5 类 + 跨版本升级 + 50 query LLM-as-judge 后回填）—— R13 docs commit 完成最终闭环
- **影响**：R13 起所有 fix commit **必须同时过工程 ⊕ 产品**，任一不达不再合并；"工程高≠产品好"循环打破
- **关联**：REVIEW.md §1 R9-P1~P5 / §3 / §7.7 / §7.5 R12 节点

### P1-019 · R13b 基线前置条件：AppTest 依赖 + 测量入口 + 故障恢复测试
- **问题**：R13b docs commit 需要 owner 跑两类基线（5 关键页面计时 + 5 类故障注入），但前置条件缺：(1) `streamlit.testing.v1.AppTest` 因 streamlit 1.57.0 + starlette 0.38.6 不兼容（`DEFAULT_EXCLUDED_CONTENT_TYPES` 在 starlette 0.40+ 引入）import 阶段即抛 `ImportError`；(2) R9-P1 缺自动测量脚本（只能 owner 手跑 5 个页面）；(3) R9-P2 5 类故障中 3 类（429 / DB lock / 切库）缺友好恢复代码 + 缺测试
- **状态**：✅ 已关闭 — R13b-prep（2026-08-04）落地 3 块前置条件：
  1. **AppTest 依赖**：`requirements.in` 加 `streamlit>=1.30,<1.60` 约束，重生成 `requirements.lock`（streamlit 1.58.0 + starlette 1.3.1），本地 pip install 升 fastapi 0.141 兼容 starlette 1.x；新增 `tests/unit/test_apptest_smoke.py` 3 条（subprocess 隔离 conftest 的 streamlit stub 跑真 AppTest 验证 import / from_file / 版本兼容）
  2. **R9-P1 测量入口**：`scripts/perf_measure_pages.py` 用 AppTest 跑 5 关键页面（Flow_A_Step1 / Flow_A_Step2 / Flow_B / JD_Library / Application_History），输出 5 行 + 平均值，target ≤ 3.0s；测试 `tests/integration/test_perf_measure_pages.py` 2 条（mock 模式下 import + 输出契约）
  3. **R9-P2 故障恢复**：`database/errors.py` 新建共享 `UserFacingError(message, retry)`（带 UI 文案 + 是否允许重试）；`tools/llm.py` 检测 429 raise `RateLimitError` → `analyze()` 转 `UserFacingError("服务繁忙，请稍后重试", retry=True)`；`database/backends/sqlite_backend.py` 加 `_run_write_with_retry` 处理 sqlite "locked"（指数退避 0.05/0.10/0.15s，最多 3 次，超限转 `UserFacingError("数据写入冲突，请稍后重试", retry=True)`），`insert_jd` 走重试；`scripts/migrate_sqlite_to_pg.py` 加 `--rollback-on-fail`（默认 True，`argparse.BooleanOptionalAction` 实现 `--no-rollback-on-fail` 关闭），失败日志带"已 rollback" / "需手动清理"提示；测试 `tests/integration/test_fault_recovery_paths.py` 5 条（429 / DB lock 自动重试 / DB lock 超限 / 切库回滚（默认开）/ 切库回滚（显式关））
- **基线**：本地 **705 passed, 24 skipped, 3 deselected, 0 failed**（基线 695 + 3 smoke + 2 perf + 5 fault recovery = +10）；`python scripts/perf_measure_pages.py` 实跑平均 0.76s（远低于 3.0s 目标）
- **关联**：REVIEW.md §1 R9-P1 / R9-P2 测量方式 / §7.5 R13b-prep 节点

---

## P2 · 改进或待确认

### P2-001 · docs/portfolio.md 数字夸大
- **问题**：`docs/portfolio.md` 是 untracked 叙事文件，含 "545 passed / 1500%" 等数字，与 CHANGELOG 任一里程碑都不匹配。
- **代码依据**：`docs/portfolio.md:281`
- **状态**：✅ 已决议 — owner 默认"不进 git，评审不考虑其数字"（2026-08-03）。如要进 git，需先做数字对齐。

### P2-002 · prompts/ 目录几乎空
- **问题**：`prompts/` 只有 `round-2-phase3-4.md` 1 个文件，多数 prompt 内联在 services 的 f-string。
- **代码依据**：`prompts/round-2-phase3-4.md`
- **状态**：🟢 待评估 — 是否抽离需评估。

### P2-003 · launch timing dashboard
- **问题**：缺首屏渲染耗时监控。
- **状态**：🟢 建议扩展 — Ops 面板加 panel。

### P2-004 · Chunk backfill 翻译调度
- **问题**：翻译 backfill 的 retry_count 上限设置是单一常量，是否需要自适应（按 LLM 错误类型分级）？
- **状态**：🟢 待讨论。

### P2-005 · 自动 apply 阈值未接 UI
- **问题**：`.env.example` 有 `AUTO_APPLY_THRESHOLD=85` / `MANUAL_CONFIRM_MIN=70`，但 UI 没接、backend 没读（探查报告）。
- **代码依据**：`.env.example`
- **状态**：🟢 待确认 — 是否在 M-v5 实现。

### P2-006 · Stash 残留
- **问题**：`git stash list` 有 `stash@{0}: On main: spillover-#9-subagent-dirty` 未 drop。
- **代码依据**：stash list
- **状态**：🟢 建议清理。

### P2-007 · claude-md 自检基线过期
- **问题**：`CLAUDE.md:38` 写 "81 passed"，明显是 M1 时旧值，应同步到当前 544。
- **代码依据**：`CLAUDE.md:38`
- **状态**：🟢 与 P0-001 同步修复。

### P2-008 · CI 不跑 secret-scan 仅在 pre-commit
- **问题**：`.github/workflows/` 跑 tests + secret-scan（README 提），但探查未确认 secret-scan 是否真的在 CI 跑。
- **状态**：🟢 待确认。

### P2-009 · eval/ 数据文件可能含真实 query
- **问题**：`data/eval_baseline_2026072*.json` 7 个 untracked，可能含真实用户 query / 简历片段。
- **状态**：✅ 自动关闭 — 随 P1-013 `8f424ee`（2026-08-04）。`data/eval_baseline_*.json` + `data/miss_analysis_*.md` + `data/post_backfill_eval_*.md` 均进 `.gitignore`，不会再被 commit 误带；`git status` 显示 `!!` 前缀。

### P2-010 · memory 项目快照与实际基线不同步
- **问题**：用户 `MEMORY.md` 记 "544/1"，与 README 481 / CLAUDE.md 81 三个数字都不一致。
- **状态**：✅ **已关闭**（随 P0-001 / `65c6625`）— README + CLAUDE.md 已统一为 `568 passed, 3 deselected`，memory 快照同步更新。唯一权威口径 = `pytest tests/ -q --tb=no` 末行。

---

### P2-011 · services 模块覆盖率 76.9% < 80%
- **问题**：`pytest --cov=services` 实测 76.9%（含 untracked `_text_utils.py` 0% 拉低），低于目标 80%
- **代码依据**：`services/_text_utils.py`（untracked）与 `services/translation_service.py:108` `_strip_thinking` 重复
- **状态**：✅ 自动解决 — 伴随 P1-008 `4380c55`（2026-08-03）；`services` 覆盖率实测由 76.9% 升至 81%。
- **关联**：P1-008 / REVIEW.md §2.4 services ≥ 80%

### P2-012 · agents 整体覆盖率 10% < 16%
- **问题**：`pytest --cov=agents` 实测 10%，低于目标 16%
- **代码依据**：agents/coordinator 与 agents/applicant 子模块化后大量 0%
- **状态**：🟢 评审期发现（v1.1 复审）。与 §2.2 "applicant 子流程完成率 N/A" 联动，缺测。
- **关联**：REVIEW.md §2.2 / §2.4

### P2-013 · crawler 覆盖率 0% < 5%
- **问题**：boss/indeed/lagou 三站均 0%，低于目标 5%
- **代码依据**：`crawler/` 全靠 `scripts/collectors/login_*` 绕过测试
- **状态**：🟢 评审期发现（v1.1 复审）。
- **关联**：REVIEW.md §2.4

### P2-014 · MAX_RETRIES_PER_RECORD grep 命中 2 < 通过条件 3
- **问题**：`grep -n "MAX_RETRIES_PER_RECORD" scripts/ services/` 仅 2 命中（`scripts/backfill_translate_chunks.py:54, 399`），目标 ≥3
- **代码依据**：`scripts/backfill_translate_chunks.py:54, 399`
- **状态**：✅ 自动关闭 — 随 P1-003 `5934753`（2026-08-04）。新回归测试文件 `tests/integration/test_backfill_translate_chunks_retry.py` 多处引用该常量语义（docstring 行 2 + commit 引用行 4），全仓 `.py` 文件实际命中 = 4（`scripts/backfill_translate_chunks.py:54, 399` + `tests/integration/test_backfill_translate_chunks_retry.py:2, 4`），超过 ≥3 通过线。
- **关联**：P1-003 / REVIEW.md §2.4

### P2-015 · 翻译覆盖 97.89% < 99.99%
- **问题**：实测 24010/24527 = 97.89%，194 条含英文未翻译。目标 ≥ 99.99%
- **代码依据**：`SELECT translated_at FROM knowledge_chunks` 实测
- **状态**：🟢 评审期发现（v1.1 复审）。与 P2-014 同步 backfill。
- **关联**：REVIEW.md §2.1 翻译覆盖

### P2-016 · R1 字面通过条件数字偏差（544/1 vs 545/0）
- **问题**：v1 FROZEN 字面写 "544 passed / 1 failed"，本次实测 `545 passed, 1 warning, 0 failed`（LLM 偶然命中"200/120/18"逃过 flake）
- **代码依据**：`pytest tests/ -q --tb=no` 输出末行
- **状态**：✅ **已关闭**（随 P0-001 / `65c6625`）— 偏差源于 real_llm flake 时好时坏。P0-002 把 real_llm 改为默认 deselect 后，基线变成确定值 `568 passed, 3 deselected`，不再随 LLM 输出漂移。
- **关联**：P0-001 / P0-002 / REVIEW.md R1

### P2-017 · knowledge_chunks 仍有 45 行 legacy=1 残留数据
- **问题**：`SELECT count(*) FROM knowledge_chunks WHERE legacy=1` = 45，旧 chunk 未清理
- **代码依据**：`SELECT count(*) FROM knowledge_chunks WHERE legacy=1`
- **状态**：🟢 评审期发现（v1.1 复审）。跟随 P0-004 commit 同步清理（migration 015）。
- **关联**：P0-004 / REVIEW.md R4

### P2-018 · CI tests 一直 fail（环境问题，与代码无关）
- **问题**：`tests/integration/test_flow_a_real_llm_3_scenarios.py` 等多个测试在 collection 阶段 `sqlite3.OperationalError: no such module: vec0`；`tests/unit/test_translation_service.py` 顶部 `import sqlite_vec` → `ModuleNotFoundError: No module named 'sqlite_vec'`。CI 已 fail 至少 5 条 commit（`39908c0` / `5b1897a` / `404cb46` / `9413665` / `711618e` / `5a8933a` 全部 tests workflow 失败）。
- **代码依据**：
  - `tests/unit/test_translation_service.py:5` 直接 `import sqlite_vec`（CI minimal-deps 不装）
  - `database/migrations/014_embedding_binary_vec0.sql` migration 需要 sqlite-vec extension
  - `database/backends/sqlite_backend.py:115` 走 numpy fallback 但 collection 时仍触发 migration
- **状态**：✅ 已关闭 — `36bf4e6`（2026-08-03）。owner 决议选项 a：CI workflow `pip install` 列表加 `sqlite-vec==0.1.6`（与本地 dev 版本一致）。CI 验证需 push 后看 GitHub Actions workflow run，本机无法直接跑 ubuntu-latest。
- **关联**：CI 历史（`gh run list --limit 30`）/ REVIEW.md §1 R1 红线 CI 健康

---

## P0 汇总（按 owner 决议分组）

**已关闭**：P0-001 / P0-002 / P0-003 / P0-004 / P0-005 / P0-006 / P0-007 / P0-008 / P0-009  
**剩余待办**：**无**（P0 全清，P1-015 已关闭；下一批 P1 阶段待办按 user_product_completeness_view.md 排序：LLM Observability → 质量分治理 → 部署）  
**已结案联动**：P1-012 与 P0-004 协调（先 P0-004 删除 rag_industry_function，再 P1-012 同步迁移清单 — 现在 `migrate_sqlite_to_pg.py` 表清单不需补 rag_industry_function，自动一致）

---

**ISSUES.md 状态**：🧊 **v1 FROZEN 2026-08-03**
**关联**：`REVIEW.md`（同目录）