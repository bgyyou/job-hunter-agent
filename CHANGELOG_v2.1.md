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
