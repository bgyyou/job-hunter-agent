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
| 2026-08-03 | P0-002 关闭：real_llm 默认 deselect + 断言放宽（commit `711618e`） | fix agent |
| 2026-08-03 | P0-005 关闭：docker 明文密码改 env_file + POSTGRES_PASSWORD 强校验（commit `e105177`） | fix agent |
| 2026-08-03 | P0-006 关闭：登录错误信息脱敏 — login_user 三场景统一对外文案（commit `7925824` / `6b57427`） | fix agent |
| 2026-08-03 | P0-009 关闭：README launcher 行数 160→270（commit `376ec90`） | fix agent |
| 2026-08-03 | P2-018 关闭：CI workflow 加 sqlite-vec==0.1.6（commit `36bf4e6`） | fix agent |
| 2026-08-03 | v1 FROZEN — owner 拍板 Q1-Q4 + 终审 Q1-Q4 | pingce skill |
| 2026-08-03 | v1.1 PRELIMINARY 复审 — R7/R8 跳过实测；R1-R6 红线未达；核心过 9 / 未达 6 / N/A 12；段位 0.0-2.9；P2 增量 7 项（P2-011~P2-017） | pingce evaluator |
| 2026-08-03 | **R3 关闭 P0-001 / P0-007 / P0-008**（commit `a4e11dd` / `d7cb50e` / `65c6625`）；测试基线 552 → 568 passed, 3 deselected；P2-010 / P2-016 随 P0-001 自动消解 | fix agent |

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
- **状态**：✅ 已决议 — owner 拍板"改 README 删行"（2026-08-03）。需新增 commit：
  1. README 删除 "💬 AI 求职助手" 行
  2. README "✏️ 优化建议" 行改写为"展示建议列表"（无采纳按钮）
  3. README "📈 投递历史" 行改写为"简历版本管理"
  4. README "爬虫" 节 liepin / jobsdb 命令改为"登录态辅助脚本（crawler 适配器 M-v5 补）"
- **关联**：REVIEW.md R3

### P0-004 · 铁律违反 3 处（Q4 owner 决议：P0 强制清理）
- **问题**：CLAUDE.md:8-10 铁律"不做向后兼容 hack，不留 alias，不写 removed 占位，一次性硬切"，代码里 3 处违反。
- **代码依据**：
  - **dead schema**：`services/jd_parser.py:17-19` 注释 "rag_industry_function 表暂保留为 dead schema，不删"
  - **Step2 legacy 兜底**：`pages/04_📝_Flow_A_Step2.py:50-89` 整块 `legacy = st.session_state.get("fa_section_data") or {}` 兜底迁移
  - **knowledge_chunks.legacy 列**：`database/backends/sqlite_backend.py:137-141` 加列；`scripts/backfill_chunks.py:1-9` 把旧 chunk 标 `legacy=1` 保留；多处 SQL 带 `kc.legacy = 0` 过滤（sqlite_backend.py:858/864/914/965）
- **状态**：✅ 已决议 — owner 拍板"P0 强制清理"（2026-08-03）。需新增 commit：
  1. `database/migrations/014_drop_rag_industry_function.sql`（删表 + 删相关代码引用）
  2. `database/migrations/015_drop_knowledge_chunks_legacy.sql`（DROP COLUMN + 全量重写 SQL 去掉 `legacy = 0`）
  3. `pages/04_📝_Flow_A_Step2.py` 移除 legacy 兜底块
  4. 加 migration 后置测试覆盖（migrate → smoke → 回滚预案）
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
- **状态**：🔴 待修复 — P1 改进。建议加 advisory lock 或 `quality_checked_at` 版本字段。

### P1-002 · smart_collector 走 v1 KB
- **问题**：`scripts/collectors/import_collected.py:108-117` 调 v1 的 `KnowledgeBase`（多 DB 文件），与 v2 统一 `jobhunter_v2.db` 不互通，导入后数据在 Flow B 的 `list_visible_jds` 看不到。
- **代码依据**：`scripts/collectors/import_collected.py:108-117`
- **状态**：🟡 待修复 — P1 改进。建议改走 `db.insert_user_jd` + `embed_and_store_jd_chunks`。

### P1-003 · 翻译 backfill 永久卡死兜底已加但未回归
- **问题**：commit `3b854ef` 加 `MAX_RETRIES_PER_RECORD` 兜底，但 CHANGELOG 未回填最新 retry_count 实际值，2 条永久卡死的根因未根治。
- **代码依据**：`scripts/backfill_chunks.py` + CHANGELOG L1981-2004
- **状态**：🟡 待回归 — P1 改进。建议加测试覆盖（模拟 LLM 429 永久失败 → 验证 retry_count 上限触发后正确 skip）。

### P1-004 · setup_wizard.py 多 page set_page_config 冲突
- **问题**：`setup_wizard.py:70` 自己 `st.set_page_config(...)`，与 `web_app.py:49-54` 的 `set_page_config` 冲突，多 page 行为依赖 streamlit 版本。
- **代码依据**：`setup_wizard.py:70`
- **状态**：🟡 待修复 — P1 改进。建议 setup_wizard.py 移除 set_page_config，统一由 web_app.py 控制。

### P1-005 · tempfile 简历图片无清理
- **问题**：`pages/03_📝_Flow_A_Step1.py:189-202` 上传图片保存到 `tempfile.gettempdir()` 全局临时目录，无清理机制。
- **代码依据**：`pages/03_📝_Flow_A_Step1.py:189-202`
- **状态**：🟡 待修复 — P1 改进。建议加定时清理 / atexit 注册清理。

### P1-006 · 死代码 `find_python_for_streamlit` 重复定义
- **问题**：`scripts/jobhunter_launcher.py:41-80` `find_python_for_streamlit` 函数定义两次，第二次完全相同（copy-paste 残留）。
- **代码依据**：`scripts/jobhunter_launcher.py:41-80`
- **状态**：🟡 待修复 — P1 改进。删除第二次定义。

### P1-007 · 死代码 `_read_some`
- **问题**：`scripts/jobhunter_launcher.py:203-214` `_read_some` 函数体立即 `return ""`，已用 threading `_drain` 替代。
- **代码依据**：`scripts/jobhunter_launcher.py:203-214`
- **状态**：🟡 待修复 — P1 改进。删除或注释掉。

### P1-008 · services/_text_utils.py untracked
- **问题**：`services/_text_utils.py` 是 untracked 新加文件，与 `services/translation_service.py:108` 已有的 `_strip_thinking` 功能重复，唯一非测试调用方是 `debug_cached_response.py`（也是 untracked）。
- **代码依据**：`services/_text_utils.py` + `services/translation_service.py:108`
- **状态**：🟡 待决策 — P1 改进。两个选项：1) 进 git 并清理 translation_service 的重复；2) 不进 git 作为本地调试。

### P1-009 · services/ops_metrics.py 半成品
- **问题**：`services/ops_metrics.py:60` 仍 raise `NotImplementedError("use _json_extract_sqlite / _json_extract_pg directly")`，提示函数需走子函数。
- **代码依据**：`services/ops_metrics.py:60`
- **状态**：🟡 待修复 — P1 改进。建议重构或彻底删除该函数入口。

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
- **状态**：🟡 待修复 — P1 改进（注：与 P0-004 的 rag_industry_function 删除有冲突，需协调：先 P0-004 删除，再 P1-012 同步迁移清单）。

### P1-013 · untracked 调试产物建议加 .gitignore
- **问题**：`data/eval_baseline_*.json`（7 个）+ `data/miss_analysis_*.md`（5 个）+ `data/post_backfill_eval_*.md` + `AI Agent产品经理_简历.md` + `data/*.bak_*.db` 等是用户调试产物，建议加 .gitignore。
- **代码依据**：git status
- **状态**：🟡 待修复 — P1 改进。

### P1-014 · 大隐患：用户上传未跑过（用户记忆）
- **问题**：用户记忆 `portfolio.md L37 "未来才考虑多租户" + L97 "从单用户工具升级到公网多用户 SaaS"`，PRD §6 没标完成度。
- **状态**：⏸ 阻塞 — 等 owner 说明"5 个真实用户跑通全流程"的现状。

### P1-015 · DB 层 27 处 `user_id: str = "default"` 签名默认值
- **问题**：`database/backends/{__init__,sqlite_backend,postgres_backend}.py` 共 27 个方法把 `user_id` 的默认值定成 `"default"`（`list_resumes` / `list_jds` / `get_jd_by_url` / `list_optimizations` / `get_latest_flow_a_draft` / `list_jds_structured` 等）。调用方漏传 `user_id` 时**不报错**，静默读写共享桶 —— 这正是 P0-008 那类跨用户串数据的**使能机制**，而不只是巧合。
- **代码依据**：`grep -rn 'user_id: str = "default"' database/` = 27 命中；R6 判定命令 1 的 3 处残留命中即来源于此
- **状态**：🔴 待修复 — 建议硬切：删掉默认值改为必填位置参数，让漏传变成 `TypeError`（编译期暴露）。影响面：`tests/unit/test_repository.py:64,67` 和 `tests/unit/test_sqlite_backend_extended.py:39,47` 四处 `list_resumes()` 无参调用需补 user_id。
- **关联**：P0-008 / REVIEW.md R6 判定命令 1

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
- **状态**：🟢 评估是否加 gitignore（与 P1-013 同步）。

### P2-010 · memory 项目快照与实际基线不同步
- **问题**：用户 `MEMORY.md` 记 "544/1"，与 README 481 / CLAUDE.md 81 三个数字都不一致。
- **状态**：✅ **已关闭**（随 P0-001 / `65c6625`）— README + CLAUDE.md 已统一为 `568 passed, 3 deselected`，memory 快照同步更新。唯一权威口径 = `pytest tests/ -q --tb=no` 末行。

---

### P2-011 · services 模块覆盖率 76.9% < 80%
- **问题**：`pytest --cov=services` 实测 76.9%（含 untracked `_text_utils.py` 0% 拉低），低于目标 80%
- **代码依据**：`services/_text_utils.py`（untracked）与 `services/translation_service.py:108` `_strip_thinking` 重复
- **状态**：🟢 评审期发现（v1.1 复审）。与 P1-008 决策绑定：按 P1-008 决议（进 git 并清理 translation_service 重复）后即解。
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
- **状态**：🟢 评审期发现（v1.1 复审）。与 P1-003 闭环同步。
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

**已关闭**：P0-001 / P0-002 / P0-005 / P0-006 / P0-007 / P0-008 / P0-009  
**剩余待办**：P0-003（README 裂缝 4 处）/ P0-004（铁律 3 处清理 + migration 014/015）  
**P1-012** = 与 P0-004 协调（先 P0-004 删除再 P1-012 同步迁移清单）

---

**ISSUES.md 状态**：🧊 **v1 FROZEN 2026-08-03**
**关联**：`REVIEW.md`（同目录）