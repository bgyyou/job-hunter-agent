# Job Hunter - 详细任务清单

每个子任务包含：**实现步骤**、**代码文件**、**验收标准**、**测试方法**

> ⚠️ **架构调整说明（2026-05-20）**：
> 从多智能体协作调整为高质量单步骤执行。保留原有代码兼容性，新增核心模块。

---

## 阶段 0-3：原有架构 ✅ 已完成（保留兼容）

详细实现步骤已在原版本中记录，此处不再重复。

**保留文件**：
- `agents/base.py` - Agent 基类
- `agents/registry.py` - Agent 注册表
- `core/` - 核心功能模块
- `models/` - 数据模型
- `tools/llm.py` - LLM 客户端
- `tools/parser/` - 文档解析器
- `tools/scraper/` - 爬虫框架

**可复用功能**：
- LLM 调用封装
- 缓存系统
- 链路追踪
- 状态管理

---

## 阶段 4：新架构核心开发 🆕 进行中

### 4.1 简历解析器增强

#### 4.1.1 实现深度结构化解析

**目标**：增强简历解析能力，输出高质量的结构化数据

**实现步骤**：
1. 创建 `tools/parser/resume_parser.py`
2. 实现 `ResumeParser` 类
3. 实现章节自动识别（个人信息、工作经历、项目、技能、教育）
4. 实现内容提取和格式化
5. 输出标准化的结构化数据

**代码文件**：`tools/parser/resume_parser.py`

```python
# tools/parser/resume_parser.py
from typing import Dict, Any, List, Optional
import re
from pathlib import Path

class ResumeParser:
    """简历解析器 - 增强版"""

    def __init__(self):
        self.section_patterns = {
            "experience": [r"工作经历", r"工作经验", r"Work Experience", r"Professional Experience"],
            "projects": [r"项目经验", r"Project Experience", r"Projects"],
            "skills": [r"技能", r"专业技能", r"Skills", r"Technical Skills"],
            "education": [r"教育背景", r"Education", r"学历"]
        }

    async def parse(self, pdf_path: str) -> Dict[str, Any]:
        """
        解析 PDF 简历，返回结构化数据

        Returns:
            {
                "header": {"name": "...", "contact": {...}, "summary": "..."},
                "experience": [{"company": "...", "title": "...", "description": "...", "achievements": [...]}],
                "projects": [{"name": "...", "role": "...", "tech_stack": [...], "description": "...", "achievements": [...]}],
                "skills": {"technical": [...], "soft": [...]},
                "education": [{"school": "...", "degree": "...", "major": "...", "start_year": ..., "end_year": ...}]
            }
        """
        # 1. 提取文本
        text = await self._extract_text(pdf_path)

        # 2. 识别章节
        sections = self._identify_sections(text)

        # 3. 解析各章节
        header = self._parse_header(text, sections)
        experience = self._parse_experience(text, sections)
        projects = self._parse_projects(text, sections)
        skills = self._parse_skills(text, sections)
        education = self._parse_education(text, sections)

        return {
            "header": header,
            "experience": experience,
            "projects": projects,
            "skills": skills,
            "education": education
        }

    async def _extract_text(self, pdf_path: str) -> str:
        """提取 PDF 文本"""
        # 使用 PyMuPDF 或 pdfplumber
        import pymupdf
        doc = pymupdf.open(pdf_path)
        text = ""
        for page in doc:
            text += page.get_text()
        return text

    def _identify_sections(self, text: str) -> Dict[str, int]:
        """识别章节位置"""
        sections = {}
        lines = text.split('\n')

        for i, line in enumerate(lines):
            for section_name, patterns in self.section_patterns.items():
                if section_name not in sections:
                    for pattern in patterns:
                        if re.search(pattern, line, re.IGNORECASE):
                            sections[section_name] = i
                            break

        return sections

    def _parse_header(self, text: str, sections: Dict[str, int]) -> Dict[str, Any]:
        """解析头部信息"""
        # 提取姓名、电话、邮箱、个人陈述
        name = self._extract_name(text)
        contact = self._extract_contact(text)
        summary = self._extract_summary(text, sections)

        return {
            "name": name,
            "contact": contact,
            "summary": summary
        }

    def _parse_experience(self, text: str, sections: Dict[str, int]) -> List[Dict]:
        """解析工作经历"""
        # 提取公司、职位、时间、描述、成果
        # ...
        return []

    def _parse_projects(self, text: str, sections: Dict[str, int]) -> List[Dict]:
        """解析项目经历"""
        # 提取项目名、角色、技术栈、描述、成果
        # ...
        return []

    def _parse_skills(self, text: str, sections: Dict[str, int]) -> Dict[str, List[str]]:
        """解析技能"""
        # 提取技术技能和软技能
        # ...
        return {"technical": [], "soft": []}

    def _parse_education(self, text: str, sections: Dict[str, int]) -> List[Dict]:
        """解析教育背景"""
        # 提取学校、学位、专业、时间
        # ...
        return []

    def _extract_name(self, text: str) -> str:
        """提取姓名"""
        # 实现姓名提取逻辑
        return "Unknown"

    def _extract_contact(self, text: str) -> Dict[str, str]:
        """提取联系方式"""
        email = re.search(r'[\w\.-]+@[\w\.-]+', text)
        phone = re.search(r'1[3-9]\d{9}', text)

        return {
            "phone": phone.group() if phone else "",
            "email": email.group() if email else ""
        }

    def _extract_summary(self, text: str, sections: Dict[str, int]) -> str:
        """提取个人陈述"""
        # 提取头部和第一个章节之间的内容
        # ...
        return ""
```

**验收标准**：
- [ ] 能正确解析 PDF 简历
- [ ] 能识别个人信息、工作经历、项目、技能、教育
- [ ] 输出格式符合要求
- [ ] 支持常见简历格式

**测试方法**：
```python
# tests/unit/test_resume_parser.py
import pytest
from tools.parser.resume_parser import ResumeParser

@pytest.mark.asyncio
async def test_parse_resume():
    parser = ResumeParser()
    result = await parser.parse("tests/fixtures/sample_resume.pdf")

    assert "header" in result
    assert "experience" in result
    assert "projects" in result
    assert "skills" in result
    assert "education" in result
    assert result["header"]["name"] != "Unknown"
```

---

#### 4.1.2 实现章节自动识别

**目标**：自动识别简历中的各个章节

**实现步骤**：
1. 定义常见章节关键词（中英文）
2. 实现模式匹配
3. 处理多种简历格式

**验收标准**：
- [ ] 能识别常见章节名称
- [ ] 能处理中英文混合
- [ ] 能处理不同格式

---

#### 4.1.3 实现内容验证

**目标**：验证解析结果的完整性和准确性

**实现步骤**：
1. 检查必填字段
2. 验证字段格式（邮箱、电话）
3. 计算完整度评分

**验收标准**：
- [ ] 能检测缺失字段
- [ ] 能验证格式正确性
- [ ] 能给出完整度评分

---

### 4.2 JD 分析器（新增）

#### 4.2.1 实现从 URL 获取 JD

**目标**：从招聘网站 URL 获取职位描述

**实现步骤**：
1. 创建 `tools/scraper/jd_analyzer.py`
2. 实现 `JDAnalyzer` 类
3. 实现从 Boss 直聘等平台获取 JD
4. 清理和格式化文本

**代码文件**：`tools/scraper/jd_analyzer.py`

```python
# tools/scraper/jd_analyzer.py
from typing import Dict, Any, Optional
from loguru import logger

class JDAnalyzer:
    """JD 分析器"""

    def __init__(self, llm_client):
        self.llm_client = llm_client

    async def parse_from_url(self, url: str) -> Dict[str, Any]:
        """
        从 URL 获取并分析 JD

        Returns:
            {
                "title": "...",
                "company": "...",
                "location": "...",
                "salary_range": "...",
                "core_requirements": [...],
                "preferred_requirements": [...],
                "implicit_requirements": "...",
                "keywords": [...]
            }
        """
        # 1. 识别平台
        platform = self._identify_platform(url)

        # 2. 获取 JD 文本
        jd_text = await self._fetch_jd_text(url, platform)

        # 3. 分析 JD（包括隐性要求）
        return await self._analyze_with_llm(jd_text)

    async def parse_from_text(self, text: str) -> Dict[str, Any]:
        """从文本分析 JD"""
        return await self._analyze_with_llm(text)

    async def _analyze_with_llm(self, jd_text: str) -> Dict[str, Any]:
        """
        使用 LLM 深度分析 JD，提取隐性要求
        """
        prompt = f"""
分析以下职位描述，提取：
1. 核心要求（必须具备的技能/经验）
2. 加分项（优先考虑的能力）
3. 隐性要求（未明说但重要的特质）
4. 岗位关键词（用于简历匹配）

JD：
{jd_text}

请以 JSON 格式返回：
```json
{{
    "title": "职位名称",
    "company": "公司名称",
    "location": "地点",
    "salary_range": "薪资范围",
    "core_requirements": ["要求1", "要求2"],
    "preferred_requirements": ["加分项1", "加分项2"],
    "implicit_requirements": "隐性要求描述",
    "keywords": ["关键词1", "关键词2"]
}}
```
"""

        # 调用 LLM 返回结构化结果
        result = await self.llm_client.analyze_with_structured_output(
            messages=[{"role": "user", "content": prompt}],
            output_schema={
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "company": {"type": "string"},
                    "location": {"type": "string"},
                    "salary_range": {"type": "string"},
                    "core_requirements": {"type": "array", "items": {"type": "string"}},
                    "preferred_requirements": {"type": "array", "items": {"type": "string"}},
                    "implicit_requirements": {"type": "string"},
                    "keywords": {"type": "array", "items": {"type": "string"}}
                }
            }
        )

        return result

    def _identify_platform(self, url: str) -> str:
        """识别招聘平台"""
        if "zhipin.com" in url:
            return "boss"
        elif "liepin.com" in url:
            return "liepin"
        elif "jobsdb.com" in url:
            return "jobsdb"
        else:
            return "unknown"

    async def _fetch_jd_text(self, url: str, platform: str) -> str:
        """从平台获取 JD 文本"""
        # 调用对应平台的爬虫
        # ...
        return ""
```

**验收标准**：
- [ ] 能从 URL 获取 JD
- [ ] 能解析 JD 内容
- [ ] 能提取核心要求
- [ ] 能识别隐性要求

**测试方法**：
```python
# tests/unit/test_jd_analyzer.py
import pytest
from tools.scraper.jd_analyzer import JDAnalyzer

@pytest.mark.asyncio
async def test_parse_from_text():
    analyzer = JDAnalyzer(llm_client)
    result = await analyzer.parse_from_text("职位描述文本...")

    assert "core_requirements" in result
    assert "implicit_requirements" in result
    assert len(result["core_requirements"]) > 0
```

---

#### 4.2.2 实现从文本解析 JD

**验收标准**：
- [ ] 能解析粘贴的 JD 文本
- [ ] 输出格式一致

---

#### 4.2.3 实现深度分析（包括隐性要求）

**验收标准**：
- [ ] 能提取隐性要求
- [ ] 能识别岗位关键词
- [ ] 分析结果准确

---

#### 4.2.4 编写单元测试

**验收标准**：
- [ ] 测试覆盖率 > 80%
- [ ] 测试通过

---

### 4.3 简历优化器扩展

#### 4.3.1 实现 LLM 驱动的优化建议生成

**目标**：基于简历和 JD 生成具体、可执行的修改建议

**实现步骤**：
1. 扩展 `agents/resume_optimizer.py`
2. 实现 `generate_suggestions()` 方法
3. 设计高质量 LLM Prompt
4. 返回结构化建议

**代码文件**：`agents/resume_optimizer.py`（扩展）

```python
# agents/resume_optimizer.py
from typing import Dict, Any
from tools.llm import LLMClient

class ResumeOptimizer:
    """简历优化器 - 扩展版"""

    def __init__(self, llm_client: LLMClient):
        self.llm_client = llm_client

    async def generate_suggestions(
        self,
        resume_data: Dict[str, Any],
        job_profile: Dict[str, Any],
        company_name: str = ""
    ) -> Dict[str, Any]:
        """
        生成详细的修改建议

        Returns:
            {
                "overall_assessment": "整体评估",
                "suggestions": [
                    {
                        "section": "summary|experience|projects|skills",
                        "target_id": "具体ID",
                        "before": "当前内容",
                        "issue": "问题分析",
                        "after": "修改后内容",
                        "reasoning": "修改理由",
                        "priority": "high|medium|low"
                    }
                ],
                "additional_tips": [...]
            }
        """

        prompt = f"""
你是一位专业的简历优化专家，擅长根据目标职位优化简历。

## 目标公司
{company_name}

## 目标职位
职位名称：{job_profile['title']}
公司名称：{job_profile.get('company', company_name)}
地点：{job_profile.get('location', '未知')}
薪资：{job_profile.get('salary_range', '面议')}

## 职位要求
**核心要求：**
{self._format_list(job_profile['core_requirements'])}

**加分项：**
{self._format_list(job_profile['preferred_requirements'])}

**岗位关键词：**
{', '.join(job_profile.get('keywords', []))}

**隐性要求分析：**
{job_profile.get('implicit_requirements', '无明显隐性要求')}

## 当前简历

**个人陈述：**
{resume_data['header'].get('summary', '无')}

**工作经历：**
{self._format_experience(resume_data['experience'])}

**项目经历：**
{self._format_projects(resume_data['projects'])}

**技能列表：**
{self._format_skills(resume_data['skills'])}

## 优化任务

请针对以上目标职位，给出具体的修改建议。每个建议包括：

1. **修改部分**：哪个部分需要修改
2. **当前内容**：当前的写法
3. **问题分析**：为什么需要修改
4. **修改后内容**：具体的改写（保持真实性，只调整表达方式）
5. **预期效果**：修改后能带来什么提升

请按以下结构返回 JSON：

```json
{{
  "overall_assessment": "整体评估：这份简历与目标职位的匹配度如何，主要差距在哪里",
  "suggestions": [
    {{
      "section": "summary|experience|projects|skills|education|other",
      "target_id": "具体到某一段的 ID（如 experience[0] 或 projects[1]）",
      "before": "当前内容",
      "issue": "问题分析",
      "after": "修改后内容（保持真实性，只调整表达方式）",
      "reasoning": "为什么这样改能提高匹配度",
      "priority": "high|medium|low"
    }}
  ],
  "additional_tips": [
    "其他优化建议（如格式调整、补充内容等）"
  ]
}}
```

## 重要约束

1. **真实性**：不要编造经历或技能，只能调整表达方式
2. **相关性**：所有修改都必须与目标职位相关
3. **具体性**：给出具体的修改内容，不要只说"要突出XX"
4. **格式**：只返回 JSON，不要有其他文字
"""

        result = await self.llm_client.analyze_with_structured_output(
            messages=[{"role": "user", "content": prompt}],
            output_schema={
                "type": "object",
                "properties": {
                    "overall_assessment": {"type": "string"},
                    "suggestions": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "section": {"type": "string"},
                                "target_id": {"type": "string"},
                                "before": {"type": "string"},
                                "issue": {"type": "string"},
                                "after": {"type": "string"},
                                "reasoning": {"type": "string"},
                                "priority": {"type": "string"}
                            }
                        }
                    },
                    "additional_tips": {
                        "type": "array",
                        "items": {"type": "string"}
                    }
                }
            }
        )

        return result

    def _format_list(self, items: list) -> str:
        """格式化列表"""
        return "\n".join(f"- {item}" for item in items)

    def _format_experience(self, experience: list) -> str:
        """格式化工作经历"""
        # ...
        return ""

    def _format_projects(self, projects: list) -> str:
        """格式化项目经历"""
        # ...
        return ""

    def _format_skills(self, skills: dict) -> str:
        """格式化技能"""
        # ...
        return ""

    async def apply_confirmations(
        self,
        resume_data: Dict[str, Any],
        suggestions: Dict[str, Any],
        confirmations: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        根据用户确认应用修改

        confirmations 格式：
        {
            "suggestions": [
                {"index": 0, "confirmed": True, "custom_after": "用户自己改的内容"}
            ]
        }
        """
        final_resume = resume_data.copy()

        for confirmation in confirmations.get("suggestions", []):
            suggestion = suggestions["suggestions"][confirmation["index"]]

            if confirmation["confirmed"]:
                # 获取修改内容
                if confirmation.get("custom_after"):
                    modified_content = confirmation["custom_after"]
                else:
                    modified_content = suggestion["after"]

                # 应用到对应部分
                section = suggestion["section"]
                target_id = suggestion["target_id"]

                if section == "summary":
                    final_resume["header"]["summary"] = modified_content
                elif section == "experience":
                    exp_index = int(target_id.replace("experience[", "").replace("]", ""))
                    final_resume["experience"][exp_index]["description"] = modified_content
                elif section == "projects":
                    proj_index = int(target_id.replace("projects[", "").replace("]", ""))
                    final_resume["projects"][proj_index]["description"] = modified_content
                # ... 其他部分

        return final_resume
```

**验收标准**：
- [ ] 能生成具体、可执行的修改建议
- [ ] 保持真实性，不编造内容
- [ ] 修改理由清晰
- [ ] 支持优先级标记

**测试方法**：
```python
# tests/unit/test_resume_optimizer.py
import pytest
from agents.resume_optimizer import ResumeOptimizer

@pytest.mark.asyncio
async def test_generate_suggestions():
    optimizer = ResumeOptimizer(llm_client)
    result = await optimizer.generate_suggestions(resume_data, job_profile)

    assert "overall_assessment" in result
    assert "suggestions" in result
    assert len(result["suggestions"]) > 0
    assert "additional_tips" in result
```

---

#### 4.3.2 实现用户确认流程

**验收标准**：
- [ ] 能根据用户确认应用修改
- [ ] 支持用户自定义修改
- [ ] 能撤销不确认的修改

---

#### 4.3.3 实现修改应用逻辑

**验收标准**：
- [ ] 能正确应用修改到对应部分
- [ ] 能处理各种 section 类型

---

#### 4.3.4 编写单元测试

**验收标准**：
- [ ] 测试覆盖率 > 80%
- [ ] 测试通过

---

### 4.4 简历生成器（新增）

#### 4.4.1 实现 Markdown 转换

**目标**：将结构化数据转换为格式工整的 Markdown

**实现步骤**：
1. 创建 `tools/generator/resume_generator.py`
2. 实现 `ResumeGenerator` 类
3. 实现 `_to_markdown()` 方法
4. 确保格式工整

**代码文件**：`tools/generator/resume_generator.py`

```python
# tools/generator/resume_generator.py
from typing import Dict, Any

class ResumeGenerator:
    """简历生成器"""

    def _to_markdown(self, resume_data: Dict[str, Any]) -> str:
        """
        转换为格式工整的 Markdown
        """
        lines = []

        # 头部
        name = resume_data["header"].get("name", "")
        contact = resume_data["header"].get("contact", {})

        lines.append(f"# {name}")
        lines.append()

        # 联系方式
        contact_parts = []
        if contact.get("phone"):
            contact_parts.append(f"📱 {contact['phone']}")
        if contact.get("email"):
            contact_parts.append(f"✉️ {contact['email']}")

        lines.append(" | ".join(contact_parts))
        lines.append()

        # 个人陈述
        summary = resume_data["header"].get("summary", "")
        if summary:
            lines.append("## 个人陈述")
            lines.append(summary)
            lines.append()

        # 工作经历
        lines.append("## 工作经历")
        for exp in resume_data.get("experience", []):
            lines.append(f"### {exp['title']} | {exp['company']}")
            lines.append(f"{exp.get('duration', '')}")
            lines.append()
            lines.append(exp.get('description', ''))

            if exp.get("achievements"):
                lines.append()
                lines.append("**主要成果：**")
                for achievement in exp["achievements"]:
                    lines.append(f"- {achievement}")
            lines.append()

        # 项目经历
        if resume_data.get("projects"):
            lines.append("## 项目经历")
            for proj in resume_data["projects"]:
                lines.append(f"### {proj['name']} | {proj['role']}")
                lines.append(f"技术栈：{', '.join(proj['tech_stack'])}")
                lines.append()
                lines.append(proj['description'])

                if proj.get("achievements"):
                    lines.append()
                    lines.append("**主要成果：**")
                    for achievement in proj["achievements"]:
                        lines.append(f"- {achievement}")
                lines.append()

        # 技能
        lines.append("## 技能")
        skills = resume_data.get("skills", {})

        if skills.get("technical"):
            lines.append(f"**技术技能：**{', '.join(skills['technical'])}")
        if skills.get("soft"):
            lines.append(f"**软技能：**{', '.join(skills['soft'])}")
        lines.append()

        # 教育背景
        if resume_data.get("education"):
            lines.append("## 教育背景")
            for edu in resume_data["education"]:
                lines.append(f"### {edu['school']}")
                lines.append(f"{edu['degree']} | {edu['major']}")
                lines.append(f"{edu['start_year']} - {edu['end_year']}")
                lines.append()

        return "\n".join(lines)
```

**验收标准**：
- [ ] 能正确转换为 Markdown
- [ ] 格式工整，符合简历标准
- [ ] 支持所有数据类型

---

#### 4.4.2 实现 HTML 模板

**目标**：使用专业模板转换为 HTML

**实现步骤**：
1. 创建 `templates/resume_template.html`
2. 实现 `_to_html()` 方法
3. 应用模板样式

**代码文件**：`templates/resume_template.html`

```html
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <style>
        body {
            font-family: 'Helvetica Neue', Arial, sans-serif;
            line-height: 1.6;
            color: #333;
            max-width: 800px;
            margin: 0 auto;
            padding: 40px;
        }
        h1 {
            font-size: 28px;
            margin-bottom: 5px;
        }
        h2 {
            font-size: 18px;
            margin-top: 30px;
            margin-bottom: 10px;
            border-bottom: 2px solid #333;
            padding-bottom: 5px;
        }
        h3 {
            font-size: 16px;
            margin-top: 15px;
            margin-bottom: 5px;
        }
        .contact-info {
            font-size: 14px;
            color: #666;
            margin-bottom: 20px;
        }
        ul {
            margin-top: 5px;
            margin-bottom: 10px;
        }
        li {
            margin-bottom: 3px;
        }
    </style>
</head>
<body>
    {content}
</body>
</html>
```

**验收标准**：
- [ ] 能正确转换为 HTML
- [ ] 样式工整专业
- [ ] PDF 渲染效果良好

---

#### 4.4.3 实现 PDF 生成（WeasyPrint）

**目标**：使用 WeasyPrint 将 HTML 转换为 PDF

**实现步骤**：
1. 安装 WeasyPrint
2. 实现 `_to_pdf()` 方法
3. 处理转换错误

**代码示例**：
```python
from weasyprint import HTML

async def _to_pdf(self, html: str, output_path: str):
    """转换为 PDF"""
    HTML(string=html).write_pdf(output_path)
```

**验收标准**：
- [ ] 能成功生成 PDF
- [ ] 格式正确
- [ ] 支持中文

---

#### 4.4.4 实现自动下载到桌面

**目标**：生成后自动下载到桌面文件夹

**实现步骤**：
1. 获取桌面路径
2. 创建输出目录
3. 自动下载文件

**代码示例**：
```python
from pathlib import Path

def get_desktop_path() -> Path:
    """获取桌面路径"""
    import os
    return Path(os.path.expanduser("~/Desktop"))

async def generate_and_download(
    self,
    resume_data: Dict[str, Any],
    company_name: str,
    output_format: str = "pdf"
) -> str:
    """生成并下载到桌面"""
    # 获取桌面路径
    desktop = self.get_desktop_path()
    output_dir = desktop / "JobHunter_Resumes"
    output_dir.mkdir(exist_ok=True)

    # 生成文件
    filename = f"{company_name}_简历.{output_format}"
    output_path = output_dir / filename

    # 生成 PDF
    if output_format == "pdf":
        await self.generate_pdf(resume_data, output_path)

    return str(output_path)
```

**验收标准**：
- [ ] 能自动下载到桌面
- [ ] 文件以公司命名
- [ ] 能处理桌面路径不存在的情况

---

#### 4.4.5 编写单元测试

**验收标准**：
- [ ] 测试覆盖率 > 80%
- [ ] 测试通过

---

### 4.5 Cover Letter 生成器（新增）

#### 4.5.1 实现 Cover Letter Prompt

**目标**：设计高质量的 Cover Letter 生成 Prompt

**实现步骤**：
1. 创建 `tools/generator/cover_letter_generator.py`
2. 实现 `CoverLetterGenerator` 类
3. 设计 Prompt 模板

**代码文件**：`tools/generator/cover_letter_generator.py`

```python
# tools/generator/cover_letter_generator.py
from typing import Dict, Any
from tools.llm import LLMClient

class CoverLetterGenerator:
    """Cover Letter 生成器"""

    def __init__(self, llm_client: LLMClient):
        self.llm_client = llm_client

    async def generate(
        self,
        resume_data: Dict[str, Any],
        job_profile: Dict[str, Any],
        company_name: str
    ) -> str:
        """
        生成 Cover Letter

        Returns:
            Cover Letter 文本（200-300 字）
        """

        prompt = f"""
根据以下简历和职位描述，生成一封专业的求职信。

## 候选人信息
姓名：{resume_data['header']['name']}
联系方式：{resume_data['header']['contact']['email']}

## 候选人经验
工作经历：
{self._format_experience(resume_data['experience'])}

项目经历：
{self._format_projects(resume_data['projects'])}

技能：{', '.join(resume_data['skills'].get('technical', []))}

## 目标职位
职位名称：{job_profile['title']}
公司：{job_profile.get('company', company_name)}
地点：{job_profile.get('location', '未知')}
薪资：{job_profile.get('salary_range', '面议')}

## 职位要求
核心要求：
{self._format_list(job_profile.get('core_requirements', []))}

## 求职信要求

1. **开头**：说明申请职位和来源
2. **中间**：强调与职位相关的经验和能力（2-3 点）
3. **结尾**：表达兴趣并请求面试
4. **语气**：专业、真诚、不夸大
5. **长度**：200-300 字（中文）
6. **针对性**：内容要与目标职位高度相关

请生成求职信：
"""

        result = await self.llm_client.chat(
            messages=[{"role": "user", "content": prompt}]
        )

        return result

    def _format_experience(self, experience: list) -> str:
        """格式化工作经历"""
        if not experience:
            return "暂无"

        lines = []
        for exp in experience[:3]:  # 只取前 3 个
            lines.append(f"- {exp['title']} @ {exp['company']}：{exp['description'][:50]}...")

        return "\n".join(lines)

    def _format_projects(self, projects: list) -> str:
        """格式化项目经历"""
        if not projects:
            return "暂无"

        lines = []
        for proj in projects[:3]:  # 只取前 3 个
            lines.append(f"- {proj['name']}：{proj['description'][:50]}...")

        return "\n".join(lines)

    def _format_list(self, items: list) -> str:
        """格式化列表"""
        return "\n".join(f"- {item}" for item in items[:5])
```

**验收标准**：
- [ ] 能生成专业的 Cover Letter
- [ ] 长度适中（200-300 字）
- [ ] 针对性强，不模板化
- [ ] 语气专业、真诚

---

#### 4.5.2 实现内容生成逻辑

**验收标准**：
- [ ] 能调用 LLM 生成内容
- [ ] 能处理各种输入格式

---

#### 4.5.3 实现格式化输出

**验收标准**：
- [ ] 输出格式规范
- [ ] 包含必要的格式化

---

#### 4.5.4 编写单元测试

**验收标准**：
- [ ] 测试覆盖率 > 80%
- [ ] 测试通过

---

### 4.6 自动投递器（新增）

#### 4.6.1 实现投递流程

**目标**：自动填写表单、上传文件、提交

**实现步骤**：
1. 创建 `tools/scraper/auto_submitter.py`
2. 实现 `AutoSubmitter` 类
3. 实现投递流程

**代码文件**：`tools/scraper/auto_submitter.py`

```python
# tools/scraper/auto_submitter.py
from typing import Dict, Any
from loguru import logger

class AutoSubmitter:
    """自动投递器"""

    def __init__(self):
        self.submitters = {
            "boss": self._submit_to_boss,
            # 其他平台
        }

    async def submit(
        self,
        job_url: str,
        resume_path: str,
        cover_letter: str,
        platform: str = "boss"
    ) -> Dict[str, Any]:
        """
        自动投递

        Returns:
            {
                "success": True/False,
                "message": "结果描述",
                "error": "错误信息（如果失败）"
            }
        """
        submitter = self.submitters.get(platform)

        if not submitter:
            return {
                "success": False,
                "message": f"不支持的平台：{platform}",
                "error": "Unsupported platform"
            }

        try:
            return await submitter(job_url, resume_path, cover_letter)
        except Exception as e:
            logger.error(f"投递失败：{e}")
            return {
                "success": False,
                "message": "投递失败",
                "error": str(e)
            }

    async def _submit_to_boss(
        self,
        job_url: str,
        resume_path: str,
        cover_letter: str
    ) -> Dict[str, Any]:
        """
        投递到 Boss 直聘

        实现方式：
        1. 打开职位页面
        2. 点击"立即沟通"或"投递简历"
        3. 填写 Cover Letter（如果有）
        4. 上传简历
        5. 提交
        6. 返回结果
        """
        # 使用 Playwright 实现浏览器自动化
        # ...
        return {
            "success": True,
            "message": "投递成功"
        }
```

**验收标准**：
- [ ] 能自动填写表单
- [ ] 能上传文件
- [ ] 能提交并返回结果

---

#### 4.6.2 实现多平台支持

**验收标准**：
- [ ] 支持 Boss 直聘
- [ ] 支持猎聘
- [ ] 易于扩展其他平台

---

#### 4.6.3 实现状态跟踪

**验收标准**：
- [ ] 能跟踪投递状态
- [ ] 能记录失败原因

---

#### 4.6.4 编写集成测试

**验收标准**：
- [ ] 测试覆盖主要流程
- [ ] 测试通过

---

## 阶段 5：GUI 开发 🔄 进行中（UI 重构）

> 🎯 **设计目标**：清爽、专业、高效、优雅的现代风格
> 🎨 **参考产品**：Notion、Linear、Cron

---

### 5.1 视觉设计升级

#### 5.1.1 专业配色方案

**目标**：采用现代蓝白配色，替代土气设计

**配色方案**：
```css
主色：#1a73e8（Google Blue）
辅助色：#34a853（绿色成功）、#ea4335（红色错误）
背景色：#f8f9fa、#ffffff
文字色：#202124（深灰）、#5f6368（浅灰）
边框色：#dadce0
```

**实现步骤**：
1. 创建 `gui/style.py` - 统一颜色和样式定义
2. 实现全局样式表（QSS）
3. 应用到所有组件

**验收标准**：
- [ ] 配色统一、专业
- [ ] 符合现代设计审美
- [ ] 支持亮色模式

---

#### 5.1.2 图标系统

**目标**：使用 SVG 图标，美观一致

**图标集**：
- 简历：📄 或 SVG 图标
- JD/职位：💼
- 建议：💡
- 预览：👁️
- 投递：🚀
- 下载：⬇️
- 成功/失败：✅ ❌

**实现步骤**：
1. 准备 SVG 图标资源（assets/icons/）
2. 实现图标加载器
3. 统一图标尺寸（24x24、32x32）

**验收标准**：
- [ ] 图标清晰、风格统一
- [ ] 支持高 DPI 显示

---

#### 5.1.3 卡片式布局

**目标**：使用卡片、阴影、圆角，现代感

**设计元素**：
- 圆角：8px、12px
- 阴影：`0 2px 8px rgba(0,0,0,0.08)`
- 内边距：16px、24px
- 间距：12px、16px、24px

**实现步骤**：
1. 创建基础 Card 组件
2. 实现不同变体（基础、悬停、选中）
3. 统一样式使用

**验收标准**：
- [ ] 卡片层次清晰
- [ ] 有阴影和圆角，美观大方
- [ ] 悬停效果流畅

---

#### 5.1.4 清晰字体层级

**目标**：定义明确的标题和正文字号

**字体层级**：
```
标题1 (H1)：24px / 粗体
标题2 (H2)：20px / 粗体
标题3 (H3)：16px / 半粗
正文：14px / 常规
小字：12px / 常规
```

**实现步骤**：
1. 在 style.py 中定义字体常量
2. 应用到相应组件
3. 确保可读性良好

**验收标准**：
- [ ] 层级分明
- [ ] 可读性良好
- [ ] 中文显示正常

---

### 5.2 页面重构

#### 5.2.1 上传页 - 拖拽上传、双栏布局

**设计目标**：
- 左侧：拖拽上传区域（支持拖入）
- 右侧：职位信息表单
- 底部：操作按钮

**功能**：
- 📄 拖拽上传简历（PDF/Word/Markdown）
- 🌐 职位 URL 输入
- 📝 或直接粘贴 JD 文本
- 🏢 公司名称输入
- ▶️ 开始分析按钮

**实现步骤**：
1. 创建 `gui/pages/upload_page.py`
2. 实现拖放区域（DragDropArea）
3. 实现双栏布局（Splitter）
4. 实现表单验证

**验收标准**：
- [ ] 拖拽区域醒目，支持拖入
- [ ] 表单布局美观、清晰
- [ ] 有上传状态提示
- [ ] 验证友好（红色边框+提示文字）

---

#### 5.2.2 建议页 - 可视化匹配度、建议卡片

**设计目标**：
- 顶部：整体评估卡片 + 仪表盘式匹配度
- 中间：建议列表（每个建议一个卡片）
- 底部：操作按钮

**功能**：
- 📊 匹配度可视化（仪表盘/进度条）
- 💡 建议卡片（左右对比：当前 vs 建议）
- ✅ 每个建议都有确认/自定义选项
- 🏷️ 显示优先级标签（高中低，不同颜色）

**实现步骤**：
1. 创建 `gui/pages/suggestions_page.py`
2. 实现匹配度仪表盘组件
3. 实现建议卡片组件
4. 实现左右对比视图

**验收标准**：
- [ ] 匹配度可视化直观
- [ ] 建议卡片层次清晰
- [ ] 对比视图一目了然
- [ ] 操作流畅

---

#### 5.2.3 预览页 - 实时渲染、多格式导出

**设计目标**：
- 左侧：Markdown 实时预览
- 右侧：Cover Letter 预览
- 顶部：导出按钮组

**功能**：
- 👁️ 实时 Markdown 渲染
- 📄 多格式导出（Markdown、HTML、PDF）
- 💼 Cover Letter 预览
- 📥 一键下载到桌面

**实现步骤**：
1. 创建 `gui/pages/preview_page.py`
2. 实现 Markdown 渲染组件（QWebEngineView）
3. 实现导出按钮组
4. 集成简历生成器

**验收标准**：
- [ ] 预览渲染准确
- [ ] 导出功能正常
- [ ] 界面简洁大方

---

#### 5.2.4 投递页 - 投递看板、数据统计

**设计目标**：
- 顶部：操作按钮
- 中间：投递历史看板（表格/卡片）
- 底部：统计概览

**功能**：
- 📋 投递历史列表（状态、公司、职位、时间）
- 📊 统计概览（总数、成功、成功率）
- 🔄 重新投递功能
- 📝 Cover Letter 预览

**实现步骤**：
1. 创建 `gui/pages/submit_page.py`
2. 实现历史列表组件
3. 实现统计卡片
4. 集成自动投递器

**验收标准**：
- [ ] 历史列表清晰
- [ ] 统计一目了然
- [ ] 操作便捷

---

### 5.3 交互体验

#### 5.3.1 加载动画、Toast 通知

**目标**：替代生硬的进度条和弹窗

**交互设计**：
- 加载：转圈动画 + 文字提示（居中显示）
- Toast：右上角滑入，2秒后自动消失（成功：绿色，错误：红色）

**实现步骤**：
1. 创建 `gui/components/loading_overlay.py`
2. 创建 `gui/components/toast.py`
3. 在主窗口中集成

**验收标准**：
- [ ] 加载动画流畅
- [ ] Toast 通知及时
- [ ] 用户体验好

---

#### 5.3.2 简历解析结果可视化

**目标**：展示解析出的数据，让用户确认

**功能**：
- 树形结构展示解析数据
- 可折叠/展开
- 快速预览个人信息、技能、经验

**实现步骤**：
1. 创建 `gui/components/resume_preview_dialog.py`
2. 实现树形视图
3. 在分析完成后弹出（可选、可关闭）

**验收标准**：
- [ ] 解析结果展示清晰
- [ ] 交互友好
- [ ] 不打断主流程

---

#### 5.3.3 本地缓存、历史记录

**目标**：持久化状态，保存投递历史

**功能**：
- 自动保存当前工作状态
- 投递历史记录到本地 JSON
- 下次启动恢复历史

**实现步骤**：
1. 创建 `gui/state_manager.py`
2. 实现本地缓存
3. 实现历史记录管理

**验收标准**：
- [ ] 状态正确保存/恢复
- [ ] 历史记录完整
- [ ] 性能良好（加载/保存快）

---

## 5.4 主窗口架构

**整体布局**：
```
┌─────────────────────────────────────────────────────────┐
│  Job Hunter  [图标]                  [设置] [帮助] │
├──────────┬──────────────────────────────────────────────┤
│          │  [步骤指示器]                          │
│  侧边栏  │                                      │
│  1 📄   │  ┌───────────────────────────────────┐  │
│  2 💡   │  │                               │  │
│  3 👁️   │  │   主内容区                   │  │
│  4 🚀   │  │                               │  │
│          │  └───────────────────────────────────┘  │
│          │                                      │
│ [数据]   │  [← 上一步]    [下一步 →]         │
└──────────┴──────────────────────────────────────────────┘
```

**实现步骤**：
1. 创建 `gui/main_window.py`
2. 创建侧边栏组件
3. 创建步骤指示器
4. 实现页面切换
5. 集成所有页面

---

---

## 阶段 6：批量模式开发 🆕 待开始

### 6.1 批量优化

#### 6.1.1 实现批量 JD 输入

**验收标准**：
- [ ] 支持多个 JD 输入
- [ ] 支持批量导入

---

#### 6.1.2 实现快速预览模式

**验收标准**：
- [ ] 能快速预览建议
- [ ] 只展示高优先级修改

---

#### 6.1.3 实现批量确认流程

**验收标准**：
- [ ] 支持批量确认
- [ ] 支持部分确认

---

### 6.2 批量投递

#### 6.2.1 实现批量简历生成

**验收标准**：
- [ ] 能批量生成简历
- [ ] 文件命名正确

---

#### 6.2.2 实现批量 Cover Letter 生成

**验收标准**：
- [ ] 能批量生成 Cover Letter
- [ ] 每份针对性强

---

#### 6.2.3 实现批量投递

**验收标准**：
- [ ] 能批量投递
- [ ] 失败能重试

---

## 阶段 7：测试与优化 🆕 待开始

### 7.1 功能测试

#### 7.1.1 单职位优化流程测试

#### 7.1.2 批量优化流程测试

#### 7.1.3 投递流程测试

---

### 7.2 性能测试

#### 7.2.1 单职位优化时间测试

#### 7.2.2 批量优化性能测试

#### 7.2.3 日均投递量测试

---

### 7.3 优化

#### 7.3.1 LLM Prompt 优化

#### 7.3.2 缓存策略优化

#### 7.3.3 用户体验优化

---

## 阶段 8：部署与文档 🆕 待开始

### 8.1 部署

#### 8.1.1 创建打包脚本

#### 8.1.2 创建安装程序（可选）

#### 8.1.3 部署测试

---

### 8.2 文档

#### 8.2.1 编写用户手册

#### 8.2.2 编写 API 文档

#### 8.2.3 编写故障排查指南

---

## 性能目标

| 指标 | 目标 |
|------|------|
| 单职位优化（含用户确认） | ≤ 10 分钟 |
| 批量优化（10 个职位） | ≤ 1 小时 |
| 日均投递量 | ≥ 50 份 |
| 简历解析时间 | ≤ 30 秒 |
| JD 分析时间 | ≤ 30 秒 |
| 优化建议生成时间 | ≤ 90 秒 |
| PDF 生成时间 | ≤ 20 秒 |

---

## 技术栈

| 组件 | 技术 | 说明 |
|------|------|------|
| PDF 解析 | PyMuPDF / pdfplumber | 提取文本 |
| PDF 生成 | WeasyPrint / Playwright | Markdown → HTML → PDF |
| LLM 调用 | OpenAI / Claude API | 优化建议、Cover Letter |
| GUI | Streamlit / PyQt | 用户界面 |
| 自动投递 | Playwright / Selenium | 浏览器自动化 |

---

*本文件会随开发进度更新*