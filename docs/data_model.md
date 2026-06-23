# 数据模型文档 — Job Hunter v2

## 1. 概述

Job Hunter v2 使用单一 SQLite 数据库 `data/jobhunter_v2.db` 统一管理所有数据。
所有业务表均支持多租户（`user_id`）、软删除（`deleted_at`）和 JSON 存储的复杂字段。

## 2. ER 关系图

```mermaid
erDiagram
    resumes ||--o{ match_history : "1:N"
    resumes ||--o{ optimizations : "1:N (optional)"
    jds ||--o{ match_history : "1:N"
    jds ||--o{ optimizations : "1:N"
    jds ||--o{ knowledge_chunks : "1:N"
    knowledge_chunks ||--o{ optimizations : "1:N (optional)"
    schema_version ||--|| resumes : "singleton"

    resumes {
        TEXT id PK
        TEXT user_id
        TEXT name
        TEXT phone
        TEXT email
        TEXT summary
        TEXT skills JSON
        INT experience_years
        TEXT domains JSON
        TEXT target_roles JSON
        TEXT preferred_locations JSON
        TEXT education JSON
        TEXT projects JSON
        TEXT created_at
        TEXT updated_at
        TEXT deleted_at
    }

    jds {
        TEXT id PK
        TEXT user_id
        TEXT url UNIQUE
        TEXT title
        TEXT company
        TEXT location
        TEXT salary_str
        INT salary_min
        INT salary_max
        TEXT requirements JSON
        TEXT preferred_requirements JSON
        TEXT skills_required JSON
        TEXT implicit_requirements
        TEXT raw_text
        TEXT parsed_data JSON
        TEXT source
        TEXT search_keyword
        TEXT platform
        TEXT job_id
        TEXT language
        TEXT industry_tag
        TEXT function_tag
        TEXT position_tag
        INT auto_classified
        INT is_public
        TEXT crawled_at
        TEXT created_at
        TEXT updated_at
        TEXT deleted_at
    }

    match_history {
        TEXT id PK
        TEXT user_id
        TEXT resume_id FK -> resumes.id
        TEXT jd_id FK -> jds.id
        REAL score
        TEXT reasoning
        TEXT matched_skills JSON
        TEXT missing_skills JSON
        TEXT gaps JSON
        TEXT recommendations JSON
        TEXT skill_mapping JSON
        INT should_apply
        TEXT user_feedback
        INT applied
        TEXT applied_at
        TEXT created_at
        TEXT deleted_at
    }

    optimizations {
        TEXT id PK
        TEXT user_id
        TEXT resume_id FK -> resumes.id
        TEXT jd_id FK -> jds.id
        TEXT chunk_id FK -> knowledge_chunks.id
        TEXT optimization_type
        TEXT section
        TEXT original_content
        TEXT suggested_content
        TEXT reason
        INT user_adopted
        INT user_rating
        TEXT created_at
        TEXT deleted_at
    }

    knowledge_chunks {
        TEXT id PK
        TEXT user_id
        TEXT jd_id FK -> jds.id
        INT chunk_index
        TEXT chunk_text
        TEXT chunk_type
        TEXT keywords JSON
        BLOB embedding
        INT embedding_dim
        TEXT created_at
        TEXT deleted_at
    }

    schema_version {
        INT id PK
        INT version
        TEXT description
        TEXT applied_at
    }

    quality_checks {
        INT id PK
        TEXT check_type
        TEXT target_table
        INT target_id
        REAL score
        TEXT details JSON
        TEXT checked_at
        TEXT user_id
    }
```

## 3. 各表详细说明

### 3.1 `resumes` — 简历画像持久化

存储所有上传并解析后的简历。支持同一用户多版本简历。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | TEXT (UUID) | 主键 |
| user_id | TEXT | 默认 'default' |
| name | TEXT | 姓名 |
| phone | TEXT | 电话 |
| email | TEXT | 邮箱 |
| summary | TEXT | 个人陈述 |
| skills | TEXT (JSON array) | 硬技能列表 |
| experience_years | INT | 工作年限 |
| domains | TEXT (JSON array) | 技术领域 |
| target_roles | TEXT (JSON array) | 目标岗位 |
| preferred_locations | TEXT (JSON array) | 偏好城市 |
| education | TEXT (JSON array) | 教育背景对象数组 |
| projects | TEXT (JSON array) | 项目经验对象数组 |

### 3.2 `jds` — 职位描述统一存储

所有来源的 JD 合并到此表，通过 `(url, user_id)` 唯一约束去重。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | TEXT (UUID) | 主键 |
| user_id | TEXT | 默认 'default' |
| url | TEXT | 规范化 URL，用于去重 |
| title | TEXT | 职位名称 |
| company | TEXT | 公司名称 |
| location | TEXT | 工作地点 |
| salary_str | TEXT | 原始薪资文本 |
| salary_min/max | INT | 解析后薪资数值 |
| requirements | TEXT (JSON) | 核心要求数组 |
| preferred_requirements | TEXT (JSON) | 加分项数组 |
| skills_required | TEXT (JSON) | 技能关键词数组 |
| implicit_requirements | TEXT | 隐性要求描述 |
| raw_text | TEXT | 完整原始 JD 文本（RAG 源头） |
| parsed_data | TEXT (JSON) | 完整解析数据（冗余存储） |
| source | TEXT | 来源: crawler/jd_crawler/manual/batch_manual/batch_upload/url |
| industry_tag | TEXT | 行业标签（自动分类） |
| function_tag | TEXT | 职能标签（自动分类） |
| position_tag | TEXT | 岗位标签（自动分类） |
| auto_classified | INT | 1=规则/Embedding, 2=LLM兜底需复核 |
| is_public | INT | 0=私有, 1=公开（未来 JD 池） |

### 3.3 `match_history` — 匹配历史记录

每次简历-JD 匹配分析的结果持久化。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | TEXT (UUID) | 主键 |
| resume_id | TEXT (FK) | 关联 resumes |
| jd_id | TEXT (FK) | 关联 jds |
| score | REAL (0-100) | 匹配分数 |
| reasoning | TEXT | LLM 匹配理由 |
| matched_skills | TEXT (JSON) | 命中技能数组 |
| missing_skills | TEXT (JSON) | 缺失技能数组 |
| gaps | TEXT (JSON) | 差距详情数组 |
| recommendations | TEXT (JSON) | 建议数组 |
| should_apply | INT | 是否建议投递 |
| applied | INT | 用户是否已投递 |

### 3.4 `optimizations` — 优化建议记录

LLM 生成的简历优化建议，支持用户确认/评分。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | TEXT (UUID) | 主键 |
| jd_id | TEXT (FK) | 关联 jds |
| resume_id | TEXT (FK, nullable) | 关联 resumes |
| chunk_id | TEXT (FK, nullable) | 关联 knowledge_chunks |
| optimization_type | TEXT | modify/delete/suggest_add |
| section | TEXT | 修改位置：experience/skills/summary/projects |
| original_content | TEXT | 当前内容 |
| suggested_content | TEXT | 建议内容 |
| reason | TEXT | 修改理由 |
| user_adopted | INT | 0=pending, 1=adopted, 2=rejected |
| user_rating | INT (1-5) | 用户评分 |

### 3.5 `knowledge_chunks` — RAG 知识库文本块

JD 切分后的文本块，支持向量检索。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | TEXT (UUID) | 主键 |
| jd_id | TEXT (FK) | 父 JD |
| chunk_index | INT | 块序号 |
| chunk_text | TEXT | 文本内容 |
| chunk_type | TEXT | overview/responsibility/requirement/nice_to_have/full |
| keywords | TEXT (JSON) | 提取的关键词数组 |
| embedding | BLOB | 向量嵌入（Float32 raw bytes） |
| embedding_dim | INT | 向量维度 |

### 3.6 `schema_version` — 迁移版本追踪

单行记录，用于后续版本升级。

### 3.7 `quality_checks` — 质量评测记录

| 字段 | 类型 | 说明 |
|------|------|------|
| check_type | TEXT | broken_link/expired_jd/ragas_faithfulness/ragas_relevance/content_completeness |
| target_table | TEXT | 目标表名 |
| target_id | INT | 目标记录 ID |
| score | REAL | 质量评分 |
| details | TEXT (JSON) | 详情 |

## 4. RAG 知识库运作原理

### 4.1 Chunking 策略

JD 入库时自动切分：
1. **按语义段落切分**：识别 `【职位描述】`、`【任职要求】`、`【加分项】` 等中文 JD 常见分隔符
2. **英文 JD**：按自然段落切分，每段约 500-1500 字符
3. **类型标注**：每块标注 `chunk_type`：
   - `overview`：职位基本信息（标题/公司/地点）
   - `responsibility`：工作职责描述
   - `requirement`：核心任职要求
   - `nice_to_have`：加分项/可选要求
   - `full`：未切分的完整 JD

### 4.2 Embedding 流程

1. 新 JD 入库后，系统调用 embedding 端点对每个 chunk 生成向量
2. 向量以 BLOB 格式存储（`struct.pack('f', *vector)`）
3. 检索时：对用户查询做同样 embedding → 余弦相似度排序 → Top-K 返回

### 4.3 检索加权

检索结果可按 `chunk_type` 加权：`requirement` 块的权重高于 `overview`。

## 5. JD 自动分类原理

### 5.1 三层 Fallback 机制

```
Title + raw_text
    │
    ├── Layer 1: 规则匹配
    │   └── 关键词直接命中分类树叶子节点
    │       → 命中 → 返回 (industry, function, position)
    │       → 未命中 → Layer 2
    │
    ├── Layer 2: Embedding 语义相似度
    │   └── TF-IDF 向量化 → 余弦相似度 ≥ 0.6
    │       → 命中 → 返回结果
    │       → 未命中 → Layer 3
    │
    └── Layer 3: LLM 兜底
        └── 调用 LLM 获取分类，标记 auto_classified=2（需人工复核）
```

### 5.2 分类树

存储在 `data/job_taxonomy.json`，三级结构：
```
行业（14个） → 职能（每行业多个） → 岗位名枚举（总计约 340 个）
```

### 5.3 入库时自动调用

`SqliteBackend.insert_jd()` 会在入库流程中调用 `Classifier.classify()`，自动填充三个 tag 字段。

## 6. 质量评测体系

### 6.1 表内评测

`quality_checks` 表用于记录关键指标（如 JD 是否过期、链接是否有效等）。

### 6.2 外部评测脚本

详细的 RAG 质量评测（Ragas faithfulness/relevance 等）由外部脚本完成，结果存 JSON 日志文件。
评测脚本可查询 `quality_checks` 表获取历史结果进行趋势分析。

## 7. 数据迁移指南

### 7.1 迁移前准备

```bash
# 1. 确保旧数据存在
ls ~/.job_hunter/crawler.db
ls data/knowledge_bases/

# 2. 预演迁移（不写入）
python scripts/migrate_v1.py --dry-run
```

### 7.2 执行迁移

```bash
# 正式迁移（自动备份旧文件）
python scripts/migrate_v1.py
```

迁移完成后：
- `~/.job_hunter/crawler.db` → `~/.job_hunter/crawler.db.backup`
- `data/jobhunter_v2.db` → 新的统一数据库
- `data/knowledge_bases/` → 文件保持不变（数据已导入 DB）

### 7.3 验证迁移

```bash
# 检查各表记录数
python -c "
from database import get_db
db = get_db()
print(db.get_stats())
"
```

## 8. 未来扩展方向

| 方向 | 说明 | 涉及改动 |
|------|------|---------|
| 多租户 | `user_id` 已从 'default' 升级为 UUID/email | 无需改 schema |
| 向量库升级 | embedding BLOB 兼容 sqlite-vec / sqlite-vss | 仅改检索逻辑 |
| 公共 JD 池 | `is_public` 字段已预留 | 仅需 Web 端展示逻辑 |
| 增量迁移 | schema_version 支持版本号升级 | 新建 migration SQL 文件 |
