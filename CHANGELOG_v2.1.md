# CHANGELOG v2.1

> 本文件追溯 2.1 升级的所有结构性优化。每个里程碑（M1–M6）完成后追加一节。

---

## [M1 治理底座] 2026-06-17

### 范围
为 2.1 后续模块铺平地基：版本控制、密钥隔离、入口收敛、依赖瘦身、日志治理。

### 改动清单

| 类别 | 改动 | 影响文件 |
|---|---|---|
| 版本控制 | `git init`（main 分支）；baseline commit `af29e4b`，149 个文件入库 | `.git/` |
| 安全 | 强化 `.gitignore`：`.env*`（白名单 `.env.example`）、`*.db*`、`*.pkl`、`data/screenshots/`、`data/llm_cache/`、`data/agent_states/` 等 11 个数据/缓存目录 | `.gitignore` |
| 安全 | 删除 `.env.test_bak`（与 `.env` 内容重复，密钥重复落盘） | `.env.test_bak` |
| 入口收敛 | 7 个根目录脚本归档到 `scripts/legacy/`：`job_hunter_cli.py`、`jd_crawler_main.py`、`start_crawler.py`、`check_db_structure.py`、`fix_db.py`、`test_integration.py`、`test_jobsdb.py` | `scripts/legacy/` |
| 入口收敛 | 4 个浏览器协同 collector 归档到 `scripts/collectors/`：`smart_collector.py`、`manual_collector.py`、`import_collected.py`、`login_jobsdb.py` | `scripts/collectors/` |
| 入口收敛 | 根目录仅保留生产入口 `web_app.py` + `run_web.bat` | 根目录 |
| 入口收敛 | 新增 `scripts/legacy/README.md`、`scripts/collectors/README.md` 标注用途与替代方案 | 同上 |
| 依赖治理 | `requirements.txt` 移除 `PyQt5>=5.15.0`（桌面版已弃用）；新增 `sentence-transformers>=2.7.0`、`numpy>=1.26.0`（M3 用）、`alembic>=1.13.0`（M5 用） | `requirements.txt` |
| 日志 | `config/settings.py` 新增 `log_rotation`、`log_retention` 字段与 `setup_logging()` 方法；loguru 启用 20MB 滚动 / 7 天保留 | `config/settings.py` |
| 日志 | `web_app.py` 启动时调用 `settings.setup_logging()`，确保所有 logger 共享配置 | `web_app.py` |

### 影响范围
- **生产路径**：仅根目录入口与 `web_app.py` 启动行为变化；不动业务逻辑。
- **历史脚本**：路径变更，外部如有引用需更新为 `scripts/legacy/...` 或 `scripts/collectors/...`。
- **依赖安装**：需 `pip install -r requirements.txt --upgrade`，新增包 ~150MB（sentence-transformers + 模型权重在 M3 启用时下载）。

### 已知遗留
- `jd_crawler/` 子项目（24MB，含独立 db）暂未归档，留待 M5 评估是否合入主库或删除。
- `.env` 中明文密钥仍留本地，gitignore 已保护，但用户应自行轮换并保管。
- 日志现存 `logs/resume_parser.log`（4.5MB）下次启动后开始按 20MB 阈值轮转，旧文件不动。

---

## [M2 写入闭环] 2026-06-17

### 范围
打通匹配→优化→投递的数据持久化闭环。修复 v2.0 遗留的"三表零行"问题：`match_history`、`optimizations` 不再只是占位表，并新增「投递历史」Tab 实现转化率复盘。

### 改动清单

| 类别 | 改动 | 影响文件 |
|---|---|---|
| Backend API | 新增 `update_match_applied(match_id, applied, applied_at)`：投递成功回写 `applied=1` + 时间戳；`applied_at=None` 自动填当前时间 | `database/backends/__init__.py`、`sqlite_backend.py`、`postgres_backend.py` |
| Backend API | 新增 `update_match_feedback(match_id, feedback)`：用户反馈状态（`read`/`replied`/`interview`/`offer`/`rejected`） | 同上 |
| Tab1 上传简历 | `db.insert_resume()` 返回值落 `st.session_state.resume_id`，供后续 match 关联 | `web_app.py` |
| Tab2 分析职位 | `db.insert_jd()` 返回值落 `st.session_state.jd_id`；URL 路径补 `db.insert_jd` 调用，与文本路径对齐 | `web_app.py` |
| Tab3 匹配度分析 | 分析成功后立即 `db.insert_match()`，写入 score/reasoning/skills/gaps/recommendations 全字段；同步把每条 recommendation 调 `db.insert_optimization()` 落库；UI 给每条建议增加「✅ 采纳」toggle，状态变化触发 `update_optimization_adopted` | `web_app.py` |
| Tab6（新） | 📈 投递历史：从 `match_history` 倒序展示，含总览指标（总匹配数 / 已投递 / 有回复 / 投递率）；每条可手动「📮 标记已投递」/「↩️ 撤销投递」/选择反馈状态；展示对应 JD 的优化采纳率 `n/m` | `web_app.py` |
| Session State | 新增 4 个键：`resume_id`、`jd_id`、`last_match_id`、`last_opt_ids`，作为 UI ↔ DB 的关联锚 | `web_app.py` |

### 影响范围
- **数据流**：所有匹配分析结果都会自动落库；优化建议每次生成都新插一批（不会自动覆盖旧记录，便于历史复盘）。
- **历史数据**：v2.0 时期已有的 `db.insert_match` 占位调用（Tab4 完整工作流，行 818 旧版）保留为兼容；新流程优先走 Tab3 实时落库。
- **UI 行为**：Tab3 在分析后会出现两条 caption（match_id + 优化数）；Tab6 是新 Tab，需手动操作才会改 DB。
- **未自动接入**：自动投递器（`agents/applicant.py`）尚未在投递成功后回调 `update_match_applied`——本次 M2 只提供手动按钮路径。M3 之后如启用自动投递再做。

### 已知遗留
- 老 v0 路径（Tab4「完整工作流」按钮内行 818 的 `resume_id=""`/`jd_id=""` 调用）暂未删除，因尚未完整测试 coordinator.execute 的返回结构；M4 测试覆盖后再清理。
- 采纳状态的 toggle 在用户切换其他 Tab 后会被 Streamlit 重渲染重置，但 DB 已落值，下次进入 Tab3 显示旧匹配时仍能从 `last_opt_ids` 重建（限本会话）。跨会话的采纳状态展示在 Tab6 用「采纳率 n/m」体现。

---

## [M2.5 质量修复] 2026-06-17

### 范围
M2 验证暴露三个 v2.0 遗留 bug，与 M2 写入闭环无关但影响首次跑通的用户体验。本次集中修掉，不展开做 RAG 之前先把根上的解析问题清掉。

### 改动清单

| 类别 | 改动 | 影响文件 |
|---|---|---|
| 简历解析 | `ResumeParser.__init__(llm_client=None)` 接受可选 LLM 客户端；`parse()` 优先走 LLM 结构化抽取（schema 含 header/experience/projects/skills/education），失败自动降级到原正则路径 | `tools/resume_parser.py` |
| 简历解析 | 新增 `_parse_with_llm(text)`：用 `analyze_with_structured_output(max_tokens=8000, temp=0.1)`，prompt 强制 LLM 把每条 bullet 都抽进 description、不允许翻译、不允许瞎编 | 同上 |
| 简历解析 | `web_app.py` Tab1 把 `st.session_state.agent.llm_client` 传进 `ResumeParser` | `web_app.py` |
| 简历解析 | 移除 `ResumeParser.__init__` 里 `logger.add()` 重复挂载（与 M1 全局 setup_logging 冲突） | `tools/resume_parser.py` |
| URL JD bug 修复 | `_fetch_jd_text` 抓不到内容时由 `return ""` 改为 `raise RuntimeError`，UI 才能显示真实失败原因（之前用户看到的是"成功但全空"） | `tools/scraper/jd_analyzer_enhanced.py` |
| URL JD bug 修复 | `_fetch_jobsdb_jd` 调用了**不存在**的 `scraper.get_jd_text(url)`（AttributeError 被外层 try 吞掉）→ 改为正确的 `scraper.parse_job(url)` 然后 `_format_jd_text` 拼接 | 同上 |
| URL JD bug 修复 | JobsDB 默认 `headless=False`（之前 True 几乎必中 Cloudflare 反爬）；`JobsDBScraper.__init__` 新增 `user_data_dir="data/browser_profiles/jobsdb"`，复用首次登录后的会话/cookie | `tools/scraper/jobsdb_scraper.py` |
| UI 报错 | Tab2 URL 路径捕获异常后给出明确指引：建议用文本路径 / 跑 `scripts/collectors/login_jobsdb.py` / 在弹出浏览器中过验证 | `web_app.py` |
| **LLM 客户端** | **修复关键 bug**：`VolcanoClient` OpenAI 模式直接 POST `self.api_url`（如 `/v1`），返回 `404 Invalid URL`。`__init__` 自动补全为 `/v1/chat/completions`。**这才是 M2.5.1 LLM 抽取真正生效的前提条件**——之前用户报"匹配/优化质量有待商榷"很可能也是缓存假象 | `tools/llm.py` |
| URL JD 假 200 | JobsDB 对失效 URL 不返 404 而是重定向到首页/404 页，`parse_job` 抓到 821 字符"成功"内容。新增 sentinel title 检查（`jobsdb`/`page not found`/`unknown position` 等），命中即 raise | `tools/scraper/jd_analyzer_enhanced.py` |
| 验证脚本 | 新增 `scripts/verify_m2_5.py`：对比 LLM vs 正则路径的简历抽取完整度，验证 URL 失败必 raise。无需 Streamlit UI 即可端到端跑通 | `scripts/verify_m2_5.py` |

### 影响范围
- **简历解析准确率**：依赖 LLM 时质量大幅提升（中英文混排、非常规排版、bullet 长描述都能完整抽出）；副作用是每次解析多调一次 LLM（约 2-5K tokens，按当前火山定价 < ¥0.01）。
- **URL 路径首次使用**：用户首次解析 JobsDB URL 会看到 Edge 浏览器自动打开，需要手动过 Cloudflare 验证一次。验证完后会话存到 `data/browser_profiles/jobsdb/`，之后该平台的 URL 抓取直接复用，不再弹窗。
- **LLM 调用副作用**：endpoint 修复后所有 `VolcanoClient` 新 prompt 才能真正打通——之前命中缓存的请求继续可用，但任何新 prompt（新简历、新 JD、新匹配）现在才走真实 API。预计 LLM 调用量短期会上升、但功能质量与稳定性同步上升。
- **Tab6 决策**：保留 v2.0 完成的「📈 投递历史」原貌，作为用户手动打卡的工具。投递率/反馈状态语义保持不变。

### 自动化验证结果（脚本：scripts/verify_m2_5.py）

样本简历：`data/temp/Zheng Haowen CV(AI PM) .pdf`

| 指标 | 正则路径 | LLM 路径 | 提升 |
|---|---|---|---|
| name 抽到 | ✓ | ✓ | 持平 |
| email 抽到 | ✓ | ✓ | 持平 |
| summary 字符数 | 0 | **134** | ↑ |
| experience 数量 | 3 | 3 | 持平 |
| 首条 description 字符数 | 77 | **115** | ↑ |
| experience.title 是否纯净 | ❌（含时间） | ✅ | ↑ |
| projects 数量 | 0 | **3** | ↑ |
| technical skills 数量 | 4 | **16** | ↑ |
| education 数量 | 0 | **1** | ↑ |

URL 失败路径：通用 404 → ✅ raise；JobsDB 失效 URL → ✅ raise（sentinel 命中）。

### 已知遗留
- Boss 直聘 URL 路径：`BossScraper` 仍基于 requests/BeautifulSoup（非 Playwright），反爬下基本拿不到内容。修复方案归到 M6 B.3.3「Boss 完善」，本次不动。
- 通用平台（猎聘 / 51job / Linkedin / 其他）仍走 `_fetch_generic_jd` 的 BeautifulSoup 路径，遇到 SPA 或反爬会 raise；M6 B.3.2 上线猎聘专用爬虫后会接入。
- LLM 简历解析返回的 `validation` 字段是事后从结构化数据反推的，不再来自正则路径的"是否找到关键词"，准确性略弱；下一次评估如有需要再调。
- LLM endpoint 修复后，旧 cache 仍能命中并复用历史结果——若怀疑某次结果质量异常，可清空 `data/llm_cache/` 强制重打 API。

---

