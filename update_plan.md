# Job Hunter v3 重建方案（update_plan）

> **本文件是 v3 重建的"唯一权威方案文档"**。Claude code（或任何接手实现的 agent）只需要照着这一份文件干。
>
> 涵盖：产品决策、技术方案、文件落位、协作流程、风险与边界。
>
> 撰写日期：2026-07-13  
> 适用范围：M-rebuild-1（简历生成重做） + M-rebuild-2（JD 解析 + 跨岗位改写 + RAG 库）  
> 暂搁：M-rebuild-3（一键投递 4 平台）、M-rebuild-4（面试真题题库）——后续里程碑

---

## 0. 重建动机（一句话）

v2.1 的「匹配度分析 + 投递历史」数据闭环已经跑通（M1-M6），但**简历生成是死胡同**：

- **解析端**：上传 docx/pdf → 抽字段 → 进库，但**没有回写路径**，用户改完简历导不出
- **生成端**：没有"一页纸强制"约束，没有"跨岗位改写"能力，没有"无公司名模板"模式
- **JD 端**：只接文本粘贴，**没有图片 OCR、没有岗位库匹配**这两条主路
- **投递端**：手动标记，自动投递器 (`agents/applicant.py`) 还没接上 `update_match_applied` 回调

v3 把**简历生成 + JD 解析 + 跨岗位改写**这条主路径**从头重做**——围绕"用户填一次表，能产出多份匹配不同岗位的简历"。

---

## 1. 产品决策（已拍板）

### 1.1 Flow A：简历填写

**形态**：渐进式披露，默认最小集，`+` 号显式扩展。

**表单结构**：

```
[基本信息（始终展开）]
  姓名 / 性别 / 手机 / 邮箱 / 现居地 / 求职意向
  出生年（可选）/ 头像（可选）

[教育经历]  [+ 添加]  默认 1 段
  学校 / 学历 / 专业 / 起止时间 / GPA（可选）

[工作经历]  [+ 添加]  默认 1 段
  公司 / 岗位 / 起止时间
  工作描述（多行，事实流水账）
  成果数据（独立字段，单独列 — 例：促成 200 单成交 / GMV 120 万）

[项目经历]  [+ 添加]  默认 0 段（不是所有人都有）
  项目名 / 角色 / 起止时间 / 项目描述 / 我的贡献 / 成果数据

[技能 / 证书 / 语言 / 作品集]  （折叠区，默认收起）
```

**关键设计点**：
- **"成果数据"独立字段**：HR 最看的是数字，单独列出视觉强，且 LLM 改写时**有现成数字可调**，比从描述里挖靠谱
- **项目经历默认 0 段**：不是所有人都有，不强行占位
- **不强制填完才能用**：保存草稿即可中途退出

### 1.2 Flow B：JD 输入 + 跨岗位改写

**JD 三种输入形式**（**不是三个独立功能，后两步共享**）：

| 形式 | 输入 | 技术方案 | 性能 |
|---|---|---|---|
| A. 粘贴文本 | 文本框 | 简单结构化 | 1-2s |
| B. 上传图片 | 截图/照片 | PaddleOCR（中文准）+ LLM 抽结构 | ~10s（含进度） |
| C. 选岗位 → 调 RAG | 下拉选"行业×职能" | 从 RAG 库调出该岗位真实 JD | 2-3s |

**统一抽象**："JD 解析器"作为统一接口，三种输入最后都归一成同一份结构化 JD：

```json
{
  "company": "...",
  "title": "...",
  "responsibilities": ["...", "..."],
  "requirements": ["...", "..."],
  "industry": "...",
  "function": "...",
  "level": "..."
}
```

**核心：跨岗位改写（双模式）**

| 模式 | 触发条件 | 行为 | 风险 |
|---|---|---|---|
| **模式 A：改写** | 用户原简历**信息充足** | 视角切换 + 数字保留 | 低（基于事实） |
| **模式 B：生成模板** | 用户原简历**信息偏少 / 极少** | AI 凭空编"不带公司名/时间/学校"的工作/项目模板 | 中（需严格边界） |

**评估信息量 → 选模式**：
```
[用户提交原简历 + 目标 JD]
       ↓
[评估信息量]
  ├─ 每段都有数据/细节 → 模式 A 改写
  ├─ 部分段落空/无数据 → 模式 A 改写 + 模式 B 补全
  └─ 基本空白 → 模式 B 全模板生成
       ↓
[输出]  改写的 + 补全的（在视觉上有清晰区分）
       ↓
[用户校对 + 切换模式（可手动覆盖）]
       ↓
[导出 Word/PDF]
```

### 1.3 模式 B 的硬边界（锁死，写进 prompt）

**能做的**：
- 编"通用型"工作/项目经历，不绑定公司名/时间/学校
- 数字用**范围/区间**（"月均获客 500-1000"），不用精确数

**绝对不能做的**：
- ❌ 编造公司名（"曾在字节跳动..."）
- ❌ 编造时间（"2022.03-2024.05"）
- ❌ 编造学校/项目名
- ❌ 编造具体数据/奖项

**UI 隔离**：
- 模式 B 生成内容用**虚线框 + 警示色**
- 模式 B 输出末尾固定标注"⚠️ AI 虚构，不带公司名/时间，请结合自身情况填写"
- 模式 B 在"改写 vs 生成"切换器上**不是默认**，需要用户主动选

### 1.4 导出：一页纸铁律

**强制约束**：

```
[填写完 → 实时预估]
  ├─ 一页内 → "✓ 一页可容纳"
  └─ 超出一页 → 触发瘦身向导：
      1. 标黄低优先级段落（GPA 偏低 / 短期实习 / 重复技能）
      2. AI 瘦身建议（合并/删除/精简）
      3. 用户点选后实时刷新
       ↓
[导出 Word/PDF]
  └─ 严格一页，超出直接报错（不允许"超页导出"）
```

**格式分工**：
- **Word (.docx)**：用 `python-docx` + jinja2 模板，HR 主流格式，**用户可再编辑**
- **PDF**：**前端方案**（`react-to-print` 或 html2pdf），**所见即所得**，不依赖 weasyprint

**字号/排版硬约束**（一页纸的关键）：
- 正文字号：10.5pt（中文 5 号字）
- 段标题：12pt 加粗
- 个人信息行：单行 9pt
- 行距：1.15-1.25
- 页边距：上下 12mm、左右 14mm
- 总高度上限：A4 可用区 182×265mm，**绝对不能溢出**

**模板数量**：
- Word 模板：**2-3 套风格**（保守 / 现代 / 创意）
- PDF 模板：跟 Word 视觉对齐但**允许加色彩/图标**（Word 保持简洁）
- 文件命名：`{姓名}_{岗位}_{公司}.{ext}`

**模式 B 输出在导出时的处理**：
- 默认导出（**带 [AI 补全] 标记**）
- 用户可手动关闭标记（**默认关**——保留标记更安全）
- 已确认"由 AI 改写"的部分，**加 ⚠️ 提示**让用户自己核对是否造假

### 1.5 暂不做（M-rebuild-3/4）

| 里程碑 | 内容 | 状态 |
|---|---|---|
| M-rebuild-3 | 一键投递（Boss / 猎聘 / 51 / 智联，4 平台，先半自动投递猎聘） | **暂搁** |
| M-rebuild-4 | AI 面试真题（500 道 / 5 个行业×职能组合） | **暂搁** |

### 1.6 变现

**M-rebuild-1 / 2 全免费跑数据**——等 3 / 4 落地再考虑付费墙。

---

## 2. 技术方案

### 2.1 架构总览

```
┌─────────────────────────────────────────────────────────┐
│  Frontend (Streamlit / 后续可换 React)                   │
│  ├─ Tab1: 简历填写（渐进式披露表单）                      │
│  ├─ Tab2: JD 输入（三选一）                              │
│  ├─ Tab3: 匹配 + 改写（模式 A/B 切换）                   │
│  ├─ Tab4: 实时预览（一页纸检测）                         │
│  ├─ Tab5: 导出（Word/PDF）                              │
│  └─ Tab6: 投递历史（已有，保留）                          │
└─────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────┐
│  Backend (FastAPI / Streamlit handlers)                 │
│  ├─ ResumeRepository（CRUD）                            │
│  ├─ JD Parser 统一接口                                   │
│  │   ├─ TextJDParser                                    │
│  │   ├─ ImageJDParser（OCR + LLM 抽结构）                │
│  │   └─ RAGJDRetriever（从 RAG 库调真实 JD）             │
│  ├─ Resume Rewriter                                     │
│  │   ├─ 模式 A：基于原简历改写                           │
│  │   └─ 模式 B：模板生成（无公司名/时间/学校）            │
│  ├─ One-Page Estimator（实时超页检测）                    │
│  └─ Document Generator                                  │
│      ├─ WordGenerator（python-docx + jinja2）            │
│      └─ PDFGenerator（前端方案）                         │
└─────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────┐
│  Data Layer                                              │
│  ├─ SQLite（默认）：data/jobhunter_v2.db                 │
│  ├─ pgvector（进阶）：向量库                              │
│  └─ 关键词索引（双路召回）                                │
└─────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────┐
│  LLM (Agnes / 火山引擎 / OpenAI / DeepSeek)              │
│  └─ .env 配置 LLM_API_KEY / LLM_BASE_URL / LLM_MODEL    │
└─────────────────────────────────────────────────────────┘
```

### 2.2 数据模型（关键表）

**新增**：

```sql
-- JD 结构化存储（覆盖粘贴文本 / OCR / RAG 三种来源）
CREATE TABLE jd_structured (
    jd_id INTEGER PRIMARY KEY,
    source TEXT NOT NULL,            -- 'text' / 'image' / 'rag'
    raw_text TEXT,                   -- 原始输入（OCR 文本 / 粘贴文本 / 调出的 RAG JD）
    company TEXT,
    title TEXT,
    industry TEXT,
    function TEXT,
    level TEXT,
    responsibilities JSON,           -- 列表
    requirements JSON,               -- 列表
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 改写记录（每次改写都留痕，支持版本对比）
CREATE TABLE rewrite_history (
    rewrite_id INTEGER PRIMARY KEY,
    resume_id INTEGER NOT NULL,
    jd_id INTEGER,
    mode TEXT NOT NULL,              -- 'A_改写' / 'B_生成' / 'A+B_混合'
    input_snapshot JSON,             -- 改写前的原简历快照
    output_snapshot JSON,            -- 改写后的内容
    rewrite_notes JSON,              -- AI 的改写说明（每段一段）
    user_edited BOOLEAN DEFAULT 0,  -- 用户是否手动调整过
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (resume_id) REFERENCES resumes(resume_id),
    FOREIGN KEY (jd_id) REFERENCES jd_structured(jd_id)
);

-- RAG 库（行业 × 职能分类树）
CREATE TABLE rag_industry_function (
    id INTEGER PRIMARY KEY,
    industry TEXT NOT NULL,
    function TEXT NOT NULL,
    level TEXT,                      -- 'junior' / 'mid' / 'senior'
    sample_jds JSON,                 -- 该组合下的真实 JD 样本
    sample_resumes JSON,             -- 该组合下的优质简历样本
    scoring_rubric JSON,             -- 评分维度（人工标）
    source TEXT,                     -- 来源：scraped / user_contributed / ai_generated
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(industry, function, level)
);

-- 面试真题（M-rebuild-4 暂不做，但 schema 先留）
CREATE TABLE interview_questions (
    question_id INTEGER PRIMARY KEY,
    industry TEXT NOT NULL,
    function TEXT NOT NULL,
    level TEXT,
    type TEXT,                       -- 'single_choice' / 'multiple_choice' / 'true_false'
    question TEXT,
    options JSON,
    answer TEXT,
    analysis TEXT,
    key_points JSON,
    source TEXT,                     -- 'ai_generated' / 'user_contributed' / 'scraped'
    reviewed_by TEXT,                -- 人工审核者（AI 生成的题必须经人审）
    reviewed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**沿用**（v2.1 已有，不动）：
- `resumes`
- `match_history`
- `optimizations`
- `applied_history`（v2.1 M2 的"投递历史"）

### 2.3 关键接口（设计原则）

```python
# JD 解析器统一接口
class BaseJDParser(Protocol):
    def parse(self, input: Any) -> StructuredJD: ...

# 实现
class TextJDParser: ...        # 粘贴文本
class ImageJDParser: ...       # 图片 OCR + LLM 抽结构
class RAGJDRetriever: ...      # 从 RAG 库调

# 改写服务
class ResumeRewriter:
    def rewrite(
        self,
        original_resume: Resume,
        target_jd: StructuredJD,
        mode: Literal["A", "B", "A+B"] = "A",
    ) -> RewriteResult: ...

# 一页纸预估
class OnePageEstimator:
    def estimate(self, resume: Resume, template: str) -> PageEstimate:
        # 返回: total_lines, capacity, overflow_segments
        ...

# 文档生成
class DocumentGenerator:
    def generate_word(self, resume: Resume, template: str) -> bytes: ...
    def generate_pdf(self, resume: Resume, template: str) -> bytes: ...
```

### 2.4 LLM Prompt 草案（锁死约束）

**模式 A：改写 prompt 关键约束**

```markdown
# Role
你是一位资深求职简历顾问，擅长把已有工作经历"重新诠释"为目标岗位视角。

# Hard Rules（绝对不能违反）
1. 绝对不能编造原简历中没有的数据、数字、奖项
2. 保留所有数字、人名、公司名、时间不变
3. 把每段经历从"做了什么"改成"带来了什么"（结果导向）
4. 改写后每段附一句"改写思路"
5. 如果原简历某段实在无法对接目标 JD，明确说"建议删除或大改"
6. 涉及百分比/增长率时，只能用"显著/明显/约"等模糊词，不能用具体数字（除非原简历有）

# Output Format
```json
{
  "rewrites": [
    {
      "original": "原段落原文",
      "rewritten": "改写后内容",
      "rewrite_reason": "为什么这么改，对接了 JD 中哪个能力词",
      "warning": "如有风险点必填（如编造嫌疑）"
    }
  ]
}
```
```

**模式 B：生成模板 prompt 关键约束**

```markdown
# Role
你是一位资深求职简历顾问，为目标岗位生成"参考模板"。

# Hard Rules（绝对不能违反）
1. 绝对不能编造公司名、学校名、项目名
2. 绝对不能编造具体时间
3. 数字用范围/区间（"月均获客 500-1000"），不用精确数
4. 每段输出末尾必须标注"[AI 模板生成]"
5. 内容只针对"目标 JD 中的能力关键词"，不绑定任何具体行业经历

# Output Format
```json
{
  "templates": [
    {
      "section": "工作经历 / 项目经历",
      "content": "...",
      "anchored_keywords": ["JD 中的能力词 1", "能力词 2"],
      "is_ai_generated": true
    }
  ]
}
```
```

### 2.5 实时一页纸检测

**估算算法**（轻量，实时跑）：
```
中文字数 / 字段数 → 估算行数
A4 可用高度 / 单行高度 → 一页容量
行数 > 容量 → 触发瘦身
```

**超页瘦身向导**：
1. 按"优先级权重"给每段打分（GPA < 3.0 减分 / 短期实习 < 3 月减分 / 重复技能减分）
2. 标黄低优先级段落
3. AI 给"合并/删除/精简"建议
4. 用户点选后实时刷新预估

### 2.6 OCR 流水线（图片 JD 解析）

```
用户上传图片
       ↓
PaddleOCR（中文准确率优先，Tesseract 兜底）
       ↓
原始文本（可能有错）
       ↓
LLM 抽结构（"公司/岗位/职责/要求"四段）
       ↓
OCR 结果预览界面（用户校对 — 这一步不能省）
       ↓
用户确认 → 入库
```

**关键风险**：
- OCR 在图标字体、emoji 上会出错
- **不能默默用错的** —— 必须给用户校对机会
- 单张图 3-8s（OCR）+ 2-4s（LLM 抽结构）= 合计 ~10s，**要进度提示**

### 2.7 RAG 库（M-rebuild-2 框架先搭，数据待定）

**数据流**：
```
[数据源 51/公开 JD/用户贡献] 
       ↓
[Ingestion Pipeline]
   ├─ 清洗（去 PII / 去重）
   ├─ 分类（按行业×职能×级别打标）
   ├─ 评分维度标注（人工）
   └─ 写入 rag_industry_function
       ↓
[查询时双路召回]
   ├─ 向量召回（pgvector / chroma）
   └─ 关键词召回（行业职能标签匹配）
       ↓
[Reranker 合并排序]
       ↓
[Top-K 真实 JD → 喂给 LLM]
```

**重要约束**：
- **数据渠道待定**——M-rebuild-2 框架先搭，**实际爬取在数据渠道明确后再启动**
- 51 公开简历：可爬但需确认 ToS
- 猎聘 / Boss：反爬严格，**当前不可行**
- 公开 JD + 用户贡献：兜底方案

### 2.8 文档生成（Word + PDF）

**Word（python-docx + jinja2 模板）**：
- 2-3 套风格模板（保守 / 现代 / 创意）
- jinja2 语法填简历字段
- 字号/行距/边距严格按 §1.4 硬约束
- 文件命名：`{姓名}_{岗位}_{公司}.docx`

**PDF（前端方案）**：
- HTML 渲染（CSS `@page { size: A4; margin: ... }`）
- `react-to-print` 或 html2pdf 导出
- **所见即所得** + 一页纸严格控制
- 文件命名：`{姓名}_{岗位}_{公司}.pdf`

**为什么不后端出 PDF**：
- 简历样式前端就定了，html 渲染完直接出 PDF，**不会有"md→html→pdf"二次失真**
- 不依赖 weasyprint 等系统库，部署更简单
- 用户在网页上看到的样式 = 导出后的 PDF

### 2.9 模板参照（现成资源）

仓库根目录已有 **`AI Agent产品经理_简历.md`**（87 行 / 一页纸 / 字段齐全）——可作为 v3 简历模板的**直接参考**：

```
- 基本信息（姓名/手机/邮箱/GitHub）
- 个人陈述（一段话总结）
- 核心能力（4-5 条 bullet）
- 工作经历（公司+岗位+时间+主要成果）
- 项目经历（项目名+角色+技术栈+主要成果）
- 技能（产品规划/项目交付/技术理解/协调能力/价值度量 — 5 维）
- 教育背景
- 语言能力
```

v3 模板字段结构**对齐这份样例**，同时支持多套视觉风格。

---

## 3. 文件落位（v3 新增/修改清单）

### 3.1 新增文件

> **文件落位约定**：沿用现有 `services/` 扁平风格（现有 8 个 .py 都是扁平）。**不开子目录**。多文件模块用"主文件 + 内部 helper"组织，prompt 集中放在 `*_prompts.py` 便于 review。

| 路径 | 用途 | 备注 |
|---|---|---|
| `services/jd_parser.py` | JD 解析器统一接口（Text/Image/RAG） | 主入口 |
| `services/jd_parser_prompts.py` | 抽结构 / OCR 后处理 prompt | prompt 集中管理 |
| `services/resume_rewriter.py` | 改写服务（模式 A/B 切换） | 主入口 |
| `services/resume_rewriter_prompts.py` | **模式 A/B prompt 锁死** | §2.4 硬约束在此处 |
| `services/one_page_estimator.py` | 实时一页纸检测 | — |
| `services/document_generator.py` | Word + PDF 统一接口 | — |
| `services/document_generator_templates/word/conservative.j2` | 保守风格 | 模板目录例外 |
| `services/document_generator_templates/word/modern.j2` | 现代风格 | 同上 |
| `services/document_generator_templates/word/creative.j2` | 创意风格 | 同上 |
| `database/migrations/011_v3_resume_rewrite.sql` | schema 迁移 | 编号跟最新迁移对齐（010_flow_a_drafts.sql） |
| `tests/test_jd_parser.py` | JD 解析测试 | — |
| `tests/test_resume_rewriter_mode_a.py` | 模式 A 测试 | 含"不编造数据"边界 |
| `tests/test_resume_rewriter_mode_b.py` | 模式 B 测试 | 含"不编公司名"边界 |
| `tests/test_one_page_estimator.py` | 一页纸预估测试 | — |
| `tests/test_document_generator.py` | Word/PDF 生成测试 | — |
| `update_plan.md` | **本文件** | v3 唯一权威方案 |

### 3.2 修改文件

| 路径 | 改动 |
|---|---|
| `web_app.py` | 改造 Tab1-5（简历填写 / JD 输入 / 匹配改写 / 预览 / 导出），保留 Tab6（投递历史） |
| `database/backends/__init__.py` | 新增 jd_structured / rewrite_history / rag_industry_function CRUD |
| `database/backends/sqlite_backend.py` | 同上（SQLite 实现） |
| `database/backends/postgres_backend.py` | 同上（PostgreSQL 实现） |
| `tools/resume_parser.py` | 字段结构对齐 v3 表单（新增"成果数据"独立字段） |
| `CHANGELOG_v2.1.md` | 追加 `[M-rebuild-1]` 和 `[M-rebuild-2]` 两节 |

### 3.3 不动文件

- `.env.example` / `requirements.in`（如有新增依赖再加）
- `agents/applicant.py`（M-rebuild-3 范围，暂搁）
- `crawler/`（51 爬虫等 RAG 数据采集，M-rebuild-2 框架先搭，**实际爬取待数据渠道明确**）
- 投递历史 Tab 逻辑（v2.1 M2 已稳定）

---

## 4. 协作流程

### 4.1 文档职责

| 文件 | 谁写 | 谁读 | 时机 |
|---|---|---|---|
| `update_plan.md`（本文件） | Mavis（产品 + 技术方案） | Claude code 实现 / 用户 review | v3 启动时定稿 |
| `CHANGELOG_v2.1.md` | Claude code 实现后追加 | 用户 / reviewer | 每个里程碑完成后 |
| `CLAUDE.md` | 既有（项目协作规则） | Claude code | 全程遵守 |
| `CONTRIBUTING.md` | 既有（贡献者流程） | 外部贡献者 | 全程 |

### 4.2 实现节奏

```
Phase 1：基础设施
  ├─ 数据库 schema 迁移（database/migrations/0007）
  ├─ JD 解析器统一接口 + 文本/图片/RAG 三个实现
  └─ 一页纸预估器

Phase 2：核心改写
  ├─ 模式 A 改写（基于原简历）
  ├─ 模式 B 模板生成（无公司名）
  └─ 双模式评估信息量自动切换

Phase 3：文档生成
  ├─ Word 生成（python-docx + jinja2，2-3 套模板）
  └─ PDF 生成（前端方案）

Phase 4：UI 改造
  ├─ Tab1 表单（渐进式披露 + + 号扩展）
  ├─ Tab2 JD 输入（三选一）
  ├─ Tab3 匹配 + 改写（模式 A/B 切换）
  ├─ Tab4 实时预览（一页纸检测）
  └─ Tab5 导出（Word/PDF）
```

### 4.3 Commit 规范（沿用 `CLAUDE.md`）

```
feat(M-rebuild-1): ...
fix(M-rebuild-1): ...
refactor(M-rebuild-1): ...
test(M-rebuild-1): ...
docs(M-rebuild-1): ...
```

### 4.4 推的时机（硬规则，不是嘴问）

> **本节是 v3 期间 push 远端的唯一依据**。每个 session 完成后，**不**问用户"推不推"，
> 按本节规则直接决定。能推就推；不能推说明还没达"事实交付"，要先补齐再推。

#### 4.4.1 必须推（满足任一即推）

| 触发条件 | 动作 |
|---|---|
| `pytest tests/ -q` 通过且新增 ≥ baseline 的真值校验测试 | 推（带 fix/test/feat/docs 分 commit） |
| 修复了真 bug（用户报 / 测试暴露） | 推（fix commit 立刻推） |
| 配置文件 / schema 迁移 / CI 改动 | 推（CI 必跑远端验证） |
| 一个 milestone 全部完成（验收 checklist 100% 勾完） | 推（带 milestone 标题 docs commit） |

#### 4.4.2 不推（明确不推，等条件齐再推）

| 情况 | 原因 |
|---|---|
| 临时调试 print / `*.db` / `data/cookies/*.json` 改动 | 不可入库（`.gitignore` 拦不住的本地副产物） |
| 改了一行还没跑测试 | 没真值校验 |
| 跨 milestone 的混合改动没拆 commit | 3 个月后回来看无法解释"为什么" |
| 验收 checklist 没 100% 勾完 | 不到事实交付 |
| `.env` 改动 | 密钥保护（pre-commit hook 拦 `sk-*` 形式硬编码） |

#### 4.4.3 推之前自检（不通过不推，先修）

1. `pytest tests/ -q` 全过（当前 baseline 242 → round-1 后 307；新增测试 ≥ 15）
2. `git status` 确认无 `.env` / `*.db` / `data/cookies/*.json` / 临时 `*.bak` 被 staged
3. pre-commit hook 已装（一次性：`bash tools/githooks/install.sh`）
4. 改了 `requirements.in` → `pip-compile` 生成 `requirements.lock` 同步推
5. `git log -1 --format='%an %ae'` 确认是本机作者（不是误用别人身份）

#### 4.4.4 推之后

CI 跑 `tests` + `secret-scan`：

- **通过**：跟用户报告"已推 + CI 绿"
- **失败**：`gh run list --limit 3` 找挂的 run → `gh run view <id> --log-failed` 拿日志
  - 修完按 4.4.3 自检再推一次
  - **不 force push**（除非用户明确要求）

#### 4.4.5 round-1 退出后立刻推（不嘴问）

round-1（Phase 1 + Phase 2）完成 = 满足 4.4.1 全部 4 条：

- ✅ 65 条新增测试 + pytest 307 passed
- ✅ 12 个 commit 按 feat/fix/test/docs 拆开
- ✅ schema 迁移 011/012 + 双方言 CRUD
- ✅ CHANGELOG 账本

**Mavis（我自己）下一步默认行为**：扫一遍 4.4.3 五条自检 → `git push origin main` → 跑 CI 验证 → 报告"已推 + CI 状态"。

**例外**：如果 4.4.2 任一情况成立（比如 CHANGELOG milestone 标题没补 / `.bak` 文件漏 staged），先修齐再推，**仍不嘴问**。

### 4.5 推之后

CI 跑 tests + secret-scan。失败按 4.4.4 处理（`gh run` 命令 + 不 force push）。

---

## 5. 风险与边界

### 5.1 已识别风险

| 风险 | 缓解 |
|---|---|
| LLM 改写时编造数据 | prompt 锁死 + 改写说明 + 用户校对环节强制 |
| LLM 模式 B 编造公司名 | prompt 锁死 + UI 虚线框 + 显式标注 |
| 简历超出一页 | 实时预估 + 瘦身向导 + 导出前最终检查 |
| OCR 错误被默默使用 | 校对界面 + 用户确认才能入库 |
| RAG 库数据质量差 | 数据渠道待定，宁缺勿滥 |
| LLM provider 切换影响 | `.env` 四个变量切换，代码 provider-neutral |
| 简历含敏感信息（PII） | 导出前给"敏感信息检查"提示 |

### 5.2 暂不做（避免 scope creep）

- M-rebuild-3 一键投递 4 平台（Boss / 猎聘 / 51 / 智联）
- M-rebuild-4 AI 面试真题题库
- 移动端 / 桌面端
- 简历评分（多维度自动评分）
- 多语言简历（仅中文）
- 简历市场 / 简历模板商城

### 5.3 暂未决策（要回头问用户）

| 决策点 | 当前默认值 | 需要确认 |
|---|---|---|
| RAG 数据渠道 | 51 + 公开 JD（待确认） | 用户定 |
| Word 模板套数 | 3 套（保守/现代/创意） | 用户是否够 |
| 改写模式默认 | A 为主，信息不足自动补 B | 用户是否要可手动覆盖 |
| 付费墙 | M-rebuild-1/2 全免费 | 跑数据后再定 |

---

## 6. 验收标准（M-rebuild-1 退出标准）

- [ ] Tab1 表单填写流畅，`+` 号扩展正常
- [ ] Tab2 三种 JD 输入都能跑通（含 OCR 校对环节）
- [ ] Tab3 模式 A / 模式 B / 自动切换都能触发
- [ ] 模式 B 输出有"虚线框 + 警示色 + 标注"
- [ ] 改写说明每段都生成，用户可见
- [ ] Tab4 实时预估一页纸容量
- [ ] 超页触发瘦身向导，标黄 + AI 建议
- [ ] Tab5 导出 Word / PDF，**强制一页**（超页报错）
- [ ] 模式 B 补全部分默认带 `[AI 补全]` 标记
- [ ] 文件命名自动 `{姓名}_{岗位}_{公司}.{ext}`
- [ ] pytest 全过，**当前 baseline 242**（M12+Launcher 之后）+ 新增 ≥ 15
- [ ] 至少 5 个真实用户跑通全流程，平均首次完成 < 10 分钟

---

## 7. 关联文件索引

- **项目协作规则**：`CLAUDE.md`（含 commit 规范、推的时机等）
- **贡献者流程**：`CONTRIBUTING.md`
- **历史账本**：`CHANGELOG_v2.1.md`（每个 milestone 完成后追加一节）
- **现成模板参照**：`AI Agent产品经理_简历.md`
- **本文件**：`update_plan.md` — **Mavis + Claude code + 用户 唯一协作对接文件**

---

## 8. 任务账本（实时进度）

> **本节是 v3 实施期间所有活跃任务的"实时状态面板"**。每个任务的状态、负责人、完成时间、
> 关联 commit 都在这里。**完成一个就勾一个 / 补一行，不等用户问**。

### 8.1 已完成轮次

| 轮次 | 范围 | 状态 | 关键产出 | 关联 commit |
|---|---|---|---|---|
| **round-1** | Phase 1（schema + JD 解析 + 一页纸预估）+ Phase 2（模式 A/B 改写 + auto 路由） | ✅ 完成（未 push 远端，账号问题） | 12 commit，baseline 242→307，新增 65 条测试 | `9d062f2` → `2872107`（+ `1f6161a` / `7e7c612` v2.1 flow-a 修复） |
|  | §6 验收 5/12 勾选（后端层）；7/12 延后 round-2（UI 改造 + 手动场景） |  | 详细见 `CHANGELOG_v2.1.md` [M-rebuild-1+2] 节 |  |
| **round-2** | Phase 3（document_generator 统一接口 + 2 套 Word 模板）+ Phase 4（flow_a 5 Step UI） | ✅ 完成（未 push 远端，账号问题） | 6 commit（本地），baseline 326→371，新增 45 条测试（19 doc_gen + 42 step UI - 复用 16 + 3 端到端） | 待 commit（round-2 期间 git 改动 6 个 commit） |
|  | §6 验收 11/12 勾选（剩 1 项 5 个真实用户验证 → round-3） |  | 详细见 `CHANGELOG_v2.1.md` [M-rebuild-3+4] 节 |  |

### 8.2 当前活跃轮次

#### Round-2: v3 Phase 3（文档生成）+ Phase 4（flow_a 5 Step UI 改造）

**启动时间**：2026-07-13  
**负责人**：Claude code（实施）+ Mavis（协调）+ 用户（review）  
**预计交付**：~10 commit（Phase 3: 2-3 commit + Phase 4: 5-7 commit + 测试 + 文档）  
**push 状态**：本轮不 push（GitHub 账号 sunlife 邮箱被回收），commit 本地积累

##### 任务清单

- [x] **T1**: Phase 3 — `services/document_generator.py`（Word + PDF 统一接口） ✅ 文档生成统一接口 commit
- [x] **T2**: Phase 3 — Word jinja2 模板（保守 + 现代，2 套起步） ✅ 同上
- [x] **T3**: Phase 3 — document_generator 单测（≥ 10 条，覆盖文件命名 / 一页纸强校验 / LLM 不可用降级） ✅ 19 条
- [x] **T4**: Phase 4 — Step 1: JD 三选一入口（text/image/rag，按 §1.2 决策） ✅ 5 Step 状态机 commit（9 条单测）
- [x] **T5**: Phase 4 — Step 2: 渐进式披露表单（基本+教育+工作+项目+技能，+ 号扩展） ✅ 同上（15 条单测）
- [x] **T6**: Phase 4 — Step 3: 模式 A/B/auto 切换器（调 round-1 ResumeRewriter） ✅ 同上（11 条单测）
- [x] **T7**: Phase 4 — Step 4: 一页纸实时预览 + 瘦身向导（调 round-1 OnePageEstimator） ✅ 同上（4 条单测）
- [x] **T8**: Phase 4 — Step 5: Word/PDF 导出（调 document_generator，强制一页，文件命名 `{姓名}_{岗位}_{公司}.{ext}`） ✅ 同上（3 条单测）
- [x] **T9**: Phase 4 — 5 个 Step UI 单测（≥ 15 条） ✅ 42 条（4 个 test 文件）
- [x] **T10**: 3 个手动场景跑通（完整/极简/部分） ✅ 端到端集成 test 3 条（`test_flow_a_step_3to5_scenarios.py`）
- [x] **T11**: CHANGELOG 追加 [M-rebuild-3] + [M-rebuild-4] 两节 ✅ `CHANGELOG_v2.1.md` 追加
- [x] **T12**: update_plan.md 修订 ✅ 本节（任务清单 + 进度汇总）

##### 歧义清单（启动前先看 update_plan + 现状能不能解）

| # | 歧义 | 建议 | 待解状态 |
|---|---|---|---|
| Q1 | Step 1 跟 §1.2 "JD 三选一" 跟现状"行业×职能×岗位下拉"对不齐 | 保留下拉作为 RAG 入口 + 旁加 text/image 两个备选按钮 | **已解**：采纳建议。下拉保留 = RAG 入口；旁加两个按钮触发 TextJDParser/ImageJDParser，三路径统一经 JDParserRouter.parse() |
| Q2 | Word 模板套数（2 套 / 3 套） | 本轮 2 套（保守+现代），第 3 套创意留 round-3 | **已解**：采纳建议 2 套（保守/现代）。services/document_generator_templates/word/{conservative,modern}.j2 |
| Q3 | PDF 方案选型（streamlit-html-to-pdf / 浏览器 print-to-PDF / weasyprint） | `st.components.v1.html` 嵌入 HTML + 浏览器 print-to-PDF，零依赖 | **已解（偏差）**：现状 tools/generator/resume_pdf.py 用 playwright headless chromium 已稳定（≥ 半年，未装 weasyprint）。本轮保留 playwright 方案（document_generator.generate_pdf 内部走它），前端 print-to-PDF 留 round-3 优化（避开 Playwright 启动开销） |
| Q4 | render_flow_a 改造方案（方案 A 渐进迁移 / 方案 B 整体重写） | 方案 A，5 Step 拆 5 commit | **已解**：采纳方案 A。每 Step 一个独立 render 函数（render_flow_a_step_1..5），逐步迁移现有 467 行 render_flow_a，不重写 |
| Q5 | 跟 flow_b 关系（只改 flow_a / 也改 flow_b） | 本轮只动 flow_a，flow_b 保留 | **已解**：采纳建议。本轮只动 render_flow_a（5 Step 状态机），render_flow_b 保留原状 |

##### 进度更新规则

- 完成一个 T 打勾，**同时**在 commit 列表里记关联 hash
- 解决一个 Q 改 "待 Claude code 确认" → "已解" + 写结论
- 新增歧义 → 加进 Q 列表
- 用户新决策点 → 加进 §5.3 表格 + 写"用户决定于 YYYY-MM-DD"

### 8.3 待启动轮次

| 轮次 | 范围 | 启动时机 |
|---|---|---|
| round-3 | Phase 5（真值闭环 + 真实用户验证 + 验收 12/12 收口） | round-2 完成后（2026-07-13 启动） |
| round-4 | M-rebuild-3 一键投递 4 平台（半自动投递猎聘） | 用户定（§5.2 暂不做） |
| round-5 | M-rebuild-4 AI 面试真题 500 道 | 用户定（§5.2 暂不做） |

#### Round-3 任务清单（v3 收口轮）

**目标**：§6 验收 12/12 全过 + v3 重建"事实完工"。

**优先级 P0**（必须做）：

- [ ] **P0-1**: T-extra-3 闭环 — CI 环境 playwright 不可用时 PDF 降级到"提示用户用浏览器打印"（当前直接 st.error，按"上线收费前提 = 真值闭环"是硬伤）
- [ ] **P0-2**: T-extra-4 闭环 — 真实 LLM 跑一次 3 场景（完整/极简/部分），把 `tests/integration/test_flow_a_step_3to5_scenarios.py` 的 mock LLM 路径补一条真 LLM integration test
- [ ] **P0-3**: §6 验收最后 1 条 — 3-5 个真实用户试用 + 反馈收集（招募方式 / 反馈表设计 / 数据收集表 / 反馈汇总成 round-3 收口报告）

**优先级 P1**（应该做）：

- [ ] **P1-1**: T-extra-1 闭环 — Step 2 表单加"重置草稿"按钮（清空 v3 + legacy state）
- [ ] **P1-2**: T-extra-2 闭环 — Step 3 auto 切 B 后"重跑改写"按钮（区分首次跑 / 手动切）
- [ ] **P1-3**: CHANGELOG_v2.1.md → rename 成 CHANGELOG.md（v3 内容已占主体，文件名不一致影响 review）

**收口验证**：

- [ ] pytest tests/ -q ≥ 371 + 新增 ≥ 10（真 LLM test 至少 3 条 + 真实用户场景 test）
- [ ] §6 验收 12/12 全勾
- [ ] round-3 收口报告写到 `update_plan.md §8.1` 加新行
- [ ] CHANGELOG 追加 [M-rebuild-5] 节（v3 收口）

**push 状态**：本轮 commit 仍本地积累（账号问题未解），不强行推。

**预计 commit 数**：5-7 个（P0-1/2/3 各 1 commit + P1 合并 1-2 commit + 文档 1 commit）

---

## 9. 协作模式

> **本节定义 v3 期间 Mavis + Claude code + 用户的协作流程**。从 round-2 起，
> 三个角色都按这一份文件 `update_plan.md` 对接，**不再单独维护 prompt 文件**。

### 9.1 角色职责

| 角色 | 谁 | 职责 |
|---|---|---|
| **Mavis** | 我（root session） | 协调三方、监控进度、解决歧义、更新 `update_plan.md` §8 任务账本、review Claude code 交付物 |
| **Claude code** | 实施者 session | 按 `update_plan.md` 实施、写代码、跑测试、commit、回报进度 |
| **用户** | 你 | 拍板决策、review 验收、定优先级 |

### 9.2 协作流（每轮启动 → 交付）

```
[1] 用户说"启动 round-X"（或同等意思）
        ↓
[2] Mavis 看 update_plan.md §8 任务账本
    - 找到 round-X 那一节
    - 列出 T 清单 + Q 歧义清单
    - 列出来给 Claude code（不需要再发独立 prompt 文件）
        ↓
[3] Claude code 按 update_plan §8 T 清单实施
    - 每完成一个 T → git commit（按 CLAUDE.md commit 规范）
    - 每解决一个 Q → 在 §8.2 表格里改"待确认"→"已解" + 写结论
    - 跑 pytest tests/ -q 确认 baseline 不破
        ↓
[4] Claude code 回报 Mavis
    - commit 列表
    - pytest 结果
    - §6 验收打勾状态
    - 手动场景日志
    - 剩余 Q / 新的 T（如果实施中发现新工作）
        ↓
[5] Mavis 转给用户 review
    - 用户 review commit / 测试 / 验收
    - 提修改意见 / 拍板剩余 Q
        ↓
[6] 验收通过 → 进入下一轮
    验收不通过 → Claude code 修 → 回到 [3]
```

### 9.3 唯一对接文件原则

> **从 round-2 起，`update_plan.md` 是 Mavis + Claude code + 用户的唯一协作对接文件**。
> 不再单独维护 `prompts/round-X-*.md` 之类的任务文件。

| 信息 | 写在 update_plan.md 哪一节 |
|---|---|
| 产品决策 / 技术方案 / 文件落位 / 风险边界 | §1 - §5 |
| 验收标准 | §6 |
| 关联文件引用 | §7 |
| **任务账本 / 实时进度** | **§8** ← 本轮新加 |
| **协作模式** | **§9** ← 本轮新加 |
| **实时更新规则** | **§10** ← 本轮新加 |

**任务、歧义、commit 关联、进度状态都在 §8**。Claude code 启动时只需要读一份文件。

### 9.4 例外：复杂轮次可临时加"任务说明块"

> 如果某轮任务非常复杂（比如 10+ 任务、5+ 歧义、跨多 service 改造），可以临时在本文件
> §8.2 加"任务说明块"（不是新文件，是新章节），描述实施顺序、commit 模板、硬要求。
> 完成后保留该块作为历史。

---

## 10. 实时更新规则

> **本节是 §8 任务账本"实时更新"的具体动作定义**。每完成一个动作，
> 谁、什么时候、改 update_plan.md 哪一行，都有规则。

### 10.1 谁负责更新

| 角色 | 改 update_plan.md 的时机 |
|---|---|
| **Mavis** | 用户拍板决策时 + Claude code 交付物 review 通过时 + round 启动/完成时 |
| **Claude code** | 完成一个 T 时（打勾 + 补 commit hash） + 解决一个 Q 时（改状态 + 写结论） |
| **用户** | 几乎不直接改本文件，通过 Mavis 转达 |

### 10.2 必做的实时更新

| 动作 | 谁 | 改 update_plan.md 哪一行 |
|---|---|---|
| 完成一个 T | Claude code | §8.2 任务清单 `- [ ]` → `- [x]` + 关联 commit hash |
| 解决一个 Q | Claude code | §8.2 歧义清单"待 Claude code 确认" → "已解：结论" |
| 新增 T / Q | Claude code 或 Mavis | §8.2 表格里加新行 |
| 用户新决策点 | Mavis | §5.3 表格里加行 + 标"用户决定 YYYY-MM-DD" |
| 跑通一个手动场景 | Claude code | §8.2 T10 附日志路径 |
| 验收一条打勾 | Mavis（review 通过后） | §6 验收 `- [ ]` → `- [x]` |
| 一个 round 完成 | Mavis | §8.1 "已完成轮次" 表格加一行 + §8.2 当前轮次清空 / 移到 §8.3 |
| 改了产品决策 | Mavis | §1 那一节更新 + §5.3 移除已决策项 |

### 10.3 实时更新后做什么

- **Claude code 完成 T 后**：
  1. `git add <具体文件>`（不 `git add -A`）
  2. `git commit -m "<type>(<scope>): <why>"`
  3. **不要 push**（按 §4.4.5 round-1 经验 + 当前账号问题）
  4. 更新 update_plan.md §8.2 T 状态
  5. 跑 `pytest tests/ -q` 确认 baseline 不破

- **Mavis 转给用户 review**：
  1. 把 Claude code 回报的 6 项（commit / pytest / 验收 / 场景 / 剩余 Q / update_plan 修订）整理成短消息
  2. 用户 review 后提意见或拍板
  3. 改 update_plan.md 对应章节

### 10.4 不要做的事

- ❌ 单独创建 `prompts/round-*.md` 任务文件
- ❌ 在 update_plan.md 之外的文档（如 IM 截图、口头约定）记录决策
- ❌ 完成 T 不打勾、解决 Q 不改状态（让账本跟实际状态脱节）
- ❌ round-1 之前那种"嘴问用户要不要 push"——按 §4.4.5 规则直接推 / 不推

---

**最后更新**：2026-07-13（新增 §8 任务账本 / §9 协作模式 / §10 实时更新规则；Mavis + Claude code + 用户唯一协作对接文件）  
**下次更新时机**：每个 T 完成时 / 每个 Q 解决时 / 用户新决策点时 / 每个 round 完成时
