# Job Hunter - 智能求职助手

一个本地运行的网页版求职助手系统，提供简历优化、Cover Letter生成功能。

## 项目特点

- 🎯 **简历精准优化** - 针对单个职位深度优化，生成高质量 Markdown/HTML 简历
- 📄 **Cover Letter 生成** - 根据岗位和简历自动生成针对性求职信
- 🌐 **Web UI** - 现代简洁的网页界面 (Streamlit)
- 🛡️ **安全可靠** - 用户确认修改，保持真实性

## 快速开始

### Windows 用户

**最简单的方式**：直接双击 `run_web.bat`

或者：
```bash
streamlit run web_app.py
```

### 首次运行

确保：
1. 已安装 Python 3.8+
2. 配置好 `.env` 文件中的火山引擎 API

安装依赖：
```bash
pip install -r requirements.txt
```

---

## 核心功能

### 1. 简历优化

针对单个职位优化简历，流程如下：

```
上传简历 → 输入 JD → 匹配度分析 → 生成优化简历
```

### 2. Cover Letter 生成

根据简历和目标职位自动生成针对性求职信。

## Prompt 优化记录（2026-06-13）

对 6 个 LLM Prompt 进行了全面重构：

| Prompt | 改动 |
|--------|------|
| 简历解析 | 拆出 system prompt；区分硬技能/软技能；temperature 0.7→0.0 |
| 匹配度分析 | 拆出 system prompt；移除 LLM 的逻辑判断（should_apply）；temperature 0.7→0.1 |
| 优化建议 | 拆出 system prompt；temperature 0.7→0.2；精简冗余字段 |
| 简历定制 | 拆出 system prompt；temperature 0.7→0.2；schema 增加描述 |
| 详细建议 | 精简 prompt 结构；temperature 0.2 |
| 简历整体优化 | 拆出 system prompt；删除"编造"暗示；temperature 0.7→0.3 |

统一原则：system prompt 定义角色和约束，user message 放数据；temperature 按场景分级（0.0 提取 / 0.1 分析 / 0.2 建议 / 0.3 重写）。

---

## 数据架构

### 数据库选型与位置

- **引擎**：SQLite 3（零配置、文件级数据库）
- **文件位置**：`data/jobhunter_v2.db`
- **Schema**：`data/schema.sql`（7 张表，含索引和外键）
- **访问层**：`database/repository.py`（`JobHunterDB` 类）

### ER 关系图

```
resumes (1) ── (N) match_history (N) ── (1) jds
    │                                           │
    └──── (N) optimizations                     └──── (N) knowledge_chunks
```

### 核心表一览

| 表 | 用途 | 关键字段 |
|----|------|---------|
| `resumes` | 简历画像持久化 | name, skills(JSON), experience_years, projects(JSON) |
| `jds` | 职位描述（所有来源合并） | url(UNIQUE), title, company, industry_tag, position_tag |
| `match_history` | 匹配记录 | resume_id(FK), jd_id(FK), score, matched_skills(JSON) |
| `optimizations` | 优化建议 | jd_id(FK), chunk_id(FK), user_adopted, user_rating |
| `knowledge_chunks` | RAG 文本块 | jd_id(FK), chunk_type, embedding(BLOB) |
| `schema_version` | 迁移版本 | version, description |
| `quality_checks` | 质量评测 | check_type, target_table, score |

### RAG 知识库运作原理

1. **Chunking**：JD 入库时按语义段落切分为 `overview/responsibility/requirement/nice_to_have` 类型
2. **Embedding**：每个 chunk 向量化，以 BLOB 格式存储（兼容未来 sqlite-vec）
3. **检索**：用户查询向量化 → 余弦相似度排序 → Top-K 返回 + 按 chunk_type 加权

### JD 自动分类原理

三层 fallback 机制，无需 LLM 即可完成分类：

| 层级 | 方法 | 阈值 | 触发条件 |
|------|------|------|---------|
| Layer 1 | 规则匹配 | N/A | title 中关键词直接命中分类树 |
| Layer 2 | TF-IDF + Embedding | cosine ≥ 0.6 | 标题 + 前 200 字符向量化匹配 |
| Layer 3 | LLM 兜底 | N/A | 前两层均未命中，标记需人工复核 |

分类树覆盖 14 个行业、约 340 个岗位名，详见 `data/job_taxonomy.json`。

### 数据迁移指南

已有数据（crawler.db + knowledge_bases JSON 文件）可通过迁移脚本合并到新库：

```bash
# 预演（不写入）
python scripts/migrate_v1.py --dry-run

# 正式迁移（自动备份旧文件）
python scripts/migrate_v1.py
```

迁移完成后旧文件自动重命名为 `.backup`，不删除。

---

## 爬虫模块

### 基本用法

```bash
# 爬取 Boss直聘（需要 cookies）
python crawler/run_crawler.py --site boss --keyword "AI产品经理" --limit 20

# 指定 cookies 文件
python crawler/run_crawler.py --site boss --keyword "Python" --limit 10 \
    --cookies data/cookies/boss.json

# 爬取拉勾网（需要 cookies）
python crawler/run_crawler.py --site lagou --keyword "AI产品经理" --limit 20

# 爬取 Indeed 中国
python crawler/run_crawler.py --site indeed --keyword "AI产品经理" --limit 20

# 交互模式
python crawler/run_crawler.py --interactive
```

### 支持的数据源

| 站点 | 标识 | 认证方式 | 说明 |
|------|------|---------|------|
| Boss直聘 | `boss` | cookies / Edge 浏览器复用 | 推荐，API 返回 JSON 效率高 |
| 拉勾网 | `lagou` | cookies | 移动端 API，需 LGSUID + gatekeeper |
| Indeed 中国 | `indeed` | 无需认证 | HTML 解析，每页 10 条 |

### Edge 浏览器复用模式

当没有有效 cookies 时，可以使用 `--use-browser` 参数复用本机 Edge 的登录态：

```bash
python crawler/run_crawler.py --site boss --keyword "AI产品经理" --limit 1 --use-browser
```

**前置条件：**

1. 本机已安装 Microsoft Edge
2. 在 Edge 中已登录 boss 直聘账号
3. **关闭所有 Edge 窗口**（包括后台进程）
   - 运行前日志会检测残留 `msedge.exe` 进程，如有会列出 PID 并提示关闭
   - 如果日志显示 "Launched WITHOUT user-data dir"，说明 Edge 仍在运行或路径不存在
4. 已安装 Playwright：`pip install playwright && playwright install msedge`

**常见问题排查：**

| 症状 | 原因 | 解决 |
|------|------|------|
| "user-data dir DOES NOT EXIST" | Edge 未安装或未启动过 | 手动打开一次 Edge，然后关闭所有窗口 |
| "Found X leftover msedge.exe" | 后台进程占用目录锁 | 关闭所有 Edge 窗口，或在任务管理器结束 msedge.exe |
| "Browser data directory is locked" | Edge 正在使用用户数据 | 同上，关闭所有 Edge 窗口 |
| "Launched WITHOUT user-data dir" | 路径不存在或 Playwright 启动失败 | 检查日志中显示的完整路径，确认目录存在 |

**工作原理：**

1. 优先使用 `channel="msedge"` 启动 Edge（Playwright 内置支持）
2. 如果 channel 不可用，则用 Chromium 加载 Edge 的 `User Data` 目录
3. 自动注入脚本移除 `navigator.webdriver` 属性，降低被检测概率
4. 尝试清除 "受自动化软件控制" 提示横幅
5. 在搜索页解析渲染后的 DOM，提取岗位卡片信息

**自定义 Edge 用户数据目录：**

在 `.env` 中设置：

```env
CRAWLER_EDGE_USER_DATA=C:/Users/你的用户名/AppData/Local/Microsoft/Edge/User Data
CRAWLER_EDGE_PROFILE=Default
```

留空则自动从 `%LOCALAPPDATA%` 检测。

**注意事项：**

- Playwright 启动时会显示浏览器窗口（headless=False），方便观察过程
- 如果页面提示需要登录，截图会保存到 `data/cache/boss_crawler_screenshot.png`
- 同一时间只能有一个爬虫实例使用 Edge 用户目录

---

### 未来扩展方向

- **多租户**：`user_id` 字段已预留，可从 'default' 升级为 UUID/email
- **向量库升级**：embedding BLOB 兼容 sqlite-vec / sqlite-vss
- **公共 JD 池**：`is_public` 字段已预留，支持 JD 共享
- **版本迁移**：`schema_version` 表支持后续 schema 升级

---

## 项目结构

```
job-hunter-agent/
├── web_app.py           # 网页版主程序
├── run_web.bat         # Windows一键启动
├── requirements.txt    # 依赖
├── database/           # 数据访问层（新架构）
│   ├── repository.py   # JobHunterDB 统一访问层
│   └── classifier.py   # JD 自动分类器
├── agents/             # Agent核心逻辑
├── tools/              # 工具模块
├── models/             # Pydantic数据模型
├── config/             # 配置
├── data/               # 用户数据
│   ├── schema.sql      # 数据库schema
│   ├── job_taxonomy.json  # JD分类树
│   └── knowledge_bases/    # 旧版知识BASE
├── scripts/            # 运维脚本
│   └── migrate_v1.py   # 数据迁移
├── crawler/            # 招聘网站爬虫模块
│   ├── base_crawler.py # 基础爬虫类（UA轮换、速率限制、重试）
│   ├── pipeline.py     # 爬取→清洗→分类→入库流水线
│   ├── run_crawler.py  # CLI入口（支持 --use-browser Edge复用）
│   └── sites/          # 站点爬虫实现
│       └── boss.py     # Boss直聘（API + Playwright Edge回退）
├── docs/               # 文档
│   └── data_model.md   # 数据模型文档
└── templates/          # 模板文件
```
