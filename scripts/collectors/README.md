# Collector Scripts

这些是浏览器辅助型 JD 收集工具，依赖人工与 Playwright 协同（不是全自动爬虫）。

| 脚本 | 用途 | 触发场景 |
|---|---|---|
| `smart_collector.py` | 持久化 Edge profile，你正常浏览 JobsDB，后台自动保存当前页 JD | 反爬严的站点首选 |
| `manual_collector.py` | 回车一次保存当前页 JD | 站点需手动确认时 |
| `login_jobsdb.py` | 仅做登录态 cookies 持久化 | 首次或登录态过期 |
| `import_collected.py` | 把 collector 落地的 JSON 批量导入知识库 | 收集后入库 |

### 推荐流程
```bash
# 1. 首次登录
python scripts/collectors/login_jobsdb.py

# 2. 边浏览边收集
python scripts/collectors/smart_collector.py

# 3. 入库
python scripts/collectors/import_collected.py
```

> 全自动爬虫（无需人工）见 `crawler/run_crawler.py --site {boss|lagou|indeed|jobsdb}`。
