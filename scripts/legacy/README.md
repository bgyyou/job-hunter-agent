# Legacy Scripts

这些脚本在 v2.0 阶段是分散的独立入口，2.1 治理时统一归档。**不在生产路径**，仅保留以备查阅或临时复用。

| 脚本 | 原作用 | 替代方案 |
|---|---|---|
| `job_hunter_cli.py` | 命令行求职 CLI | `streamlit run web_app.py` |
| `jd_crawler_main.py` | JobsDB 爬虫主程序 | `python crawler/run_crawler.py --site jobsdb ...` |
| `start_crawler.py` | 交互式爬虫入口 | 同上 |
| `check_db_structure.py` | 检查 SQLite schema | `python -c "from database.factory import get_db; print(get_db().get_stats())"` |
| `fix_db.py` | 一次性 schema 修复 | 已并入 `data/schema.sql` 与 alembic（M5） |
| `test_integration.py` | 早期集成测试脚本 | 迁移为 `tests/integration/`（M4） |
| `test_jobsdb.py` | JobsDB 联通测试 | 同上 |

如未来需要复活某条入口，请先评估能否折叠到 `web_app.py` 或 `crawler/run_crawler.py` 现有命令中。
