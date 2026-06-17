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

