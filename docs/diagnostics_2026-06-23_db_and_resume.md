# 诊断报告：数据库模块 + 简历生成模块

**日期**：2026-06-23
**触发**：用户表示"还没 100% 满意，离企业级有一段距离"，点名两块：
1. 一键生成简历功能还需测试
2. 数据库保存逻辑

本文档是当时的现状诊断，**不是设计文档**。后续 P0/P1/P2/P3 的改造按这份单子推进。

---

## 一、简历生成模块（用户需求澄清）

### 用户要的两条独立 flow

**Flow A：0→1（从零生成）**
- 用户打开 jobhunter → 选行业 → 与 Agent 聊过往经历 → Agent 按目标行业的 JD 模板针对性生成简历
- 体现 Agent 的自主性与"从 0 到 1"能力
- **当前代码库不存在这条 flow**

**Flow B：1→2（修改旧简历）**
- 用户上传简历 + 选 JD → 输出针对该 JD 改过的新简历
- 当前 `agents/resume_optimizer.py` (995 行) + `tools/generator/resume_generator.py` (415 行) 覆盖的是这条

### 简历相关代码现状

```
tools/generator/resume_optimizer.py    142 行 ← 早期小工具版（疑似废弃）
agents/resume_optimizer.py             995 行 ← Agent 版（主流）
agents/resume_analyzer.py              620 行
tools/resume_parser.py                 880 行
tools/generator/resume_generator.py    415 行  ← Markdown/HTML/PDF 输出
models/resume.py                        79 行
                                      ─────
                                      3131 行
```

**两套 `resume_optimizer.py`** 并存 —— 典型的"没经过端到端测试 → 旧代码没清"。

### 后续要做（task #9）

1. 决定 `tools/generator/resume_optimizer.py` 142 行版本是删还是合并
2. 设计 Flow A：行业选择 UI/API → 多轮对话 schema → 经历提取 → 行业 JD 模板做骨架 → 输出 PDF
3. 端到端测试 Flow B（用户原话："还需要进行测试"）

---

## 二、数据库模块评估（按 ABCDE 五维）

### A. 表结构（schema） — 7/10，可用但有坑

**做对了**：
- 11 张表统一在 `data/schema.sql` 单文件
- `user_id` 一开始就预留多租户字段
- 软删除 `deleted_at` 全表覆盖
- `UNIQUE(url, user_id)` 去重边界对（不同用户可各存一份同一 JD）
- 关键索引基本到位（platform / industry / company / crawled_at）
- 预留 `schema_version` 表

**坑**：
- **JSON 列泛滥**：`skills` / `requirements` / `skills_required` / `gaps` / `matched_skills` 等十几个字段塞 JSON 进 TEXT。SQLite 上无所谓，Postgres 上明明能用 `JSONB + GIN` 索引但没用
- **embedding 用 BLOB JSON**：`json.dumps(list)` 编码到 BLOB。Postgres 装了 pgvector **但 schema 里没用 vector 类型**，等于白搭
- **JD 重复字段语义不清**：`requirements` / `preferred_requirements` / `skills_required` / `implicit_requirements` / `parsed_data` / `raw_text` —— **6 个字段都在存"JD 内容的不同切片"**，谁填谁不填没强约束
- `salary_min/max` 是 `INTEGER` 但实际入库时全是空（batch_liepin/_map_to_jd_row 没解析），占两列没用
- `match_history` / `optimizations` 没建 `(user_id, created_at DESC)` 复合索引，列表查询全表扫

### B. 查询性能 — 6/10，原型够，量大会跪

- ✅ 单表索引基本齐
- ❌ `search_jds` 用 `LIKE '%keyword%'` 三连（title/company/raw_text），**前缀通配符让索引全废**。1000 条还行，10000 条就慢
- ❌ vector 搜索 SQLite 走全表 Python 循环算余弦相似度，10000 chunks 就要秒级。Postgres 上 pgvector 也没真用上
- ❌ 没有任何 EXPLAIN / 慢查询日志

### C. 代码组织 — **4/10，最大问题**

**铁证**：

```
database/repository.py             683 行  ← class JobHunterDB
database/backends/sqlite_backend.py  831 行  ← class SqliteBackend
```

两个文件**有 22 个方法名一模一样**：
`insert_resume / get_resume / list_resumes / insert_jd / get_jd / list_jds / get_jd_by_url / search_jds / soft_delete_jd / insert_match / list_matches / insert_optimization / list_optimizations / update_optimization_adopted / insert_chunk / insert_chunks_batch / get_chunks_by_jd / insert_quality_check / list_quality_checks / get_stats / ...`

调用方分两派：
- **新代码**（batch_jobsdb / batch_liepin / index_jds / retriever / pipeline / web_app）走 `get_db()` → SqliteBackend
- **旧代码**（web_app 一部分、scripts/migrate_v1、_legacy_smoke）走 `JobHunterDB()` → repository.py

**后果**：两套实现 + 两份测试 + 两条 bug 入口。改 schema 要改两遍，忘一边就有静默漂移。

Backend 也不"薄"：sqlite_backend 831 行 + postgres_backend 775 行 —— `search_similar_chunks` / `insert_jd_from_parsed_pdf` 这些**业务逻辑**塞在 backend 里，方言差异+业务混在一起，导致两个 backend 必然漂移。

### D. 数据一致性 — 6/10

**做了**：
- `UNIQUE(url, user_id)`
- `batch_jobsdb._normalize_jobsdb_url` 处理 URL 参数去重（踩过坑学到的）

**没做**：
- **真 bug**：`INSERT OR IGNORE` 但返回的 ID 是新生成的 UUID —— 第二次插同一 URL 时返回的 ID **数据库里根本不存在**（实际行用旧 ID），下游拿这个 ID 查会 None。`batch_liepin.py:131` 注释 "inserted 计数会偏高" 就是这个问题
- 没有 schema migration 系统（`scripts/migrate_v1.py` 是一次性脚本不是框架），`schema_version` 永远 = 1
- `match_history.resume_id` 外键引用 `resumes(id)` 但 resumes 软删除后没级联策略，会出现 match 引用 deleted resume 的孤儿数据
- 没有事务包多步：`insert_jd + insert_chunks_batch` 不是同一事务，中间挂了会留半个 JD

### E. 双 backend 维护成本 — **3/10**

```
sqlite_backend.py     831 行
postgres_backend.py   775 行
repository.py         683 行（第三套）
─────────────────────────────
                     2289 行做同一件事
```

且：
- 两个 backend **共同实现了** vector search、PDF ingestion、迁移、JSON 序列化 —— 每加一个功能要写三遍
- Postgres backend 装了 pgvector 但 schema 里没用 vector 类型，等于装了不开
- 没有 backend 接口测试套件确保两边行为一致 —— sqlite 上去重正常 Postgres 上出 bug 你都不知道

---

## 三、综合诊断（根因）

**所有 ABCDE 问题的根因不是 5 个独立问题，是 1 个**：

当初从 v1 → v2 重构时，**没把 v1 的 `JobHunterDB` 删干净**，又加了 backend 层，结果三套并存。schema 设计也跟着将就（embedding BLOB、JSON 列泛滥），因为不想动 v1 代码。

---

## 四、修复优先级表

按"痛感 × 影响 ÷ 成本"排序。

| 优先级 | 改动 | 收益 | 成本 | 关联 task |
|---|---|---|---|---|
| **P0-1** | **删 `database/repository.py`，全切 SqliteBackend** | 一套代码、改 bug 一处、测试少一半 | 4-8h（先迁 5 个调用方） | #10 |
| **P0-2** | **修 `INSERT OR IGNORE` 返回假 ID 的 bug** | 下游再没有"幽灵 ID"问题 | 1h | #11 |
| **P1-1** | 给 `match_history(user_id, created_at)` 等加复合索引 | 列表查询不全表扫 | 0.5h | #12 |
| **P1-2** | 端到端测试简历 Flow B（修改简历→生成 PDF） | 用户痛点，找出已有 flow 的 bug | 2-4h | #13 |
| **P2-1** | Postgres 用真 `vector` 类型 + pgvector 索引 | 向量搜索 O(n) → O(log n) | 4-6h，要写迁移 | #14 |
| **P2-2** | 把 6 个 JD 重复字段收成 3 个（raw / parsed_sections / tags） | schema 自解释 | 8-12h，改写入/读取/测试 | #15 |
| **P2-3** | 实现简历 Flow A（行业选择 → 对话 → 0→1 生成） | 用户原话核心需求 | 12-20h | #9 |
| **P3-1** | 把 backend 做薄，业务逻辑（vector search / PDF ingest）拎到 service 层 | 真正的"换 backend 只改方言" | 12-20h | #16 |

---

## 五、推进原则

1. **不一次性大重构**。P0 先做完跑 81 tests 验证，确认没破再推 GitHub
2. **每个 P 都按 CLAUDE.md 铁律**：pytest → git add 具体文件 → commit → push（用户确认后）
3. **P0 → P1 → P2 顺序**。P2 里的简历 Flow A (#9) 和 schema 重构 (#15) 可以并行，因为不互相影响
4. P3 是长期，等 P0-P2 沉淀后再启动

---

## 六、当前未列入 ABCDE 但相关的遗留任务

- task #6：诊断 liepin check_login selector 过时（首页 webfont 反爬干扰）
- task #7：放量跑猎聘（已暂停，待 #8 完成）
- task #8：人类化节奏改造 liepin scraper（防封号）

这些和简历/数据库无直接关系，但都是"项目还没到企业级"的同类遗留问题，会在 P1/P2 阶段一并解决。
