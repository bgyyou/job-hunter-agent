# JobHunter 爬虫集成

## 概述

已将 JobsDB 爬虫完整集成到 JobHunter 架构中。

## 文件结构

### 新增/修改的文件

```
job-hunter-agent/
├── job_hunter_cli.py           # 统一命令行入口（新增）
├── test_integration.py         # 集成测试脚本（新增）
├── tools/scraper/
│   ├── jobsdb_scraper.py       # JobsDB爬虫重写（继承BaseScraper）
│   ├── job_database.py         # 统一数据库模块（新增）
│   └── __init__.py             # 更新导出
└── agents/
    └── job_searcher.py         # 更新支持JobsDB平台
```

## 功能特性

### 1. JobsDBScraper

继承 `BaseScraper`，提供：
- 搜索职位（支持关键词 + 时间范围）
- 解析职位详情（薪资、技能、描述）
- 异步上下文管理器支持 (`async with`)
- Playwright 浏览器自动化

### 2. JobDatabase

统一的 SQLite 数据库模块：
- 职位存储与去重
- 按平台/时间查询
- 统计信息
- 数据库自动迁移

### 3. JobSearcher Agent 更新

- 支持 "jobsdb" 平台
- 延迟导入避免依赖问题
- 保留原有的 Boss 直聘支持

### 4. CLI 入口

提供两种模式：

**直接爬取模式（推荐）**
```bash
python job_hunter_cli.py --keywords "AI Product Manager" --time 7 --max 30
```

**Agent 模式**
```bash
python job_hunter_cli.py --agent --keywords "AI Product Manager"
```

**查看数据库**
```bash
python job_hunter_cli.py --show
```

## 使用示例

### 基本使用

```python
import asyncio
from tools.scraper.jobsdb_scraper import JobsDBScraper
from tools.scraper.job_database import JobDatabase

async def main():
    # 爬取职位
    async with JobsDBScraper(headless=False, human_speed=0.5) as scraper:
        jobs = await scraper.search_jobs("AI Product Manager", posted_within=7)
        for job in jobs:
            detail = await scraper.parse_job(job["url"])
            print(detail["title"])

    # 使用数据库
    db = JobDatabase()
    print(f"总职位数: {db.get_count()}")

asyncio.run(main())
```

### 使用 Agent

```python
import asyncio
from agents.job_searcher import JobSearcher

async def main():
    searcher = JobSearcher()
    result = await searcher.execute({
        "keyword": "AI Product Manager",
        "platforms": ["jobsdb"],
        "pages": 1
    })
    print(result)

asyncio.run(main())
```

## 数据库结构

表: `crawled_jobs`

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER | 主键 |
| url | TEXT | 职位URL (唯一) |
| title | TEXT | 标题 |
| company | TEXT | 公司 |
| raw_text | TEXT | 完整页面内容 |
| location | TEXT | 地点 |
| salary_str | TEXT | 薪资原始字符串 |
| salary_min | INTEGER | 最低薪资(K) |
| salary_max | INTEGER | 最高薪资(K) |
| source | TEXT | 来源 |
| search_keyword | TEXT | 搜索关键词 |
| days_old | INTEGER | 发布天数 |
| crawled_at | TEXT | 爬取时间 |
| platform | TEXT | 平台 |
| job_id | TEXT | 职位ID |

## 向后兼容

保留了原有的爬虫文件：
- `jd_crawler_main.py`
- `jd_crawler/` 目录
- `start_crawler.py`

新旧代码可以共存使用。

