# tools/generator/resume_generator.py
"""
简历生成器 - 将结构化数据转换为格式工整的 PDF 简历
"""
from typing import Dict, Any, Optional
from pathlib import Path
import os
from loguru import logger

try:
    import markdown
except ImportError:
    markdown = None
    logger.warning("markdown 模块未安装，HTML 功能将受限")


class ResumeGenerator:
    """简历生成器"""

    def __init__(self, template_path: Optional[str] = None):
        """
        初始化简历生成器

        Args:
            template_path: HTML 模板路径
        """
        self.logger = logger.bind(component="resume_generator")
        self.template_path = template_path

    def to_markdown(self, resume_data: Dict[str, Any]) -> str:
        """
        转换为格式工整的 Markdown

        Args:
            resume_data: 简历数据

        Returns:
            Markdown 文本
        """
        lines = []

        # 头部
        header = resume_data.get("header", {})
        name = header.get("name", "")
        contact = header.get("contact", {})

        lines.append(f"# {name}")
        lines.append("")

        # 联系方式
        contact_parts = []
        if contact.get("phone"):
            contact_parts.append(f"📱 {contact['phone']}")
        if contact.get("email"):
            contact_parts.append(f"✉️ {contact['email']}")
        if contact.get("wechat"):
            contact_parts.append(f"💬 {contact['wechat']}")
        if contact.get("linkedin"):
            contact_parts.append(f"🔗 {contact['linkedin']}")

        if contact_parts:
            lines.append(" | ".join(contact_parts))
            lines.append("")

        # 个人陈述
        summary = header.get("summary", "")
        if summary:
            lines.append("## 个人陈述")
            lines.append(summary)
            lines.append("")

        # 工作经历
        experience = resume_data.get("experience", [])
        if experience:
            lines.append("## 工作经历")
            lines.append("")

            for exp in experience:
                title = exp.get("title", "")
                company = exp.get("company", "")
                duration = exp.get("duration", "")
                description = exp.get("description", "")
                achievements = exp.get("achievements", [])

                lines.append(f"### {title} | {company}")
                if duration:
                    lines.append(f"{duration}")
                lines.append("")

                if description:
                    lines.append(description)
                    lines.append("")

                if achievements:
                    lines.append("**主要成果：**")
                    for achievement in achievements:
                        lines.append(f"- {achievement}")
                    lines.append("")

        # 项目经历
        projects = resume_data.get("projects", [])
        if projects:
            lines.append("## 项目经历")
            lines.append("")

            for proj in projects:
                name = proj.get("name", "")
                role = proj.get("role", "")
                tech_stack = proj.get("tech_stack", [])
                description = proj.get("description", "")
                achievements = proj.get("achievements", [])

                lines.append(f"### {name}")
                if role:
                    lines.append(f"**角色：** {role}")
                if tech_stack:
                    lines.append(f"**技术栈：** {', '.join(tech_stack)}")
                lines.append("")

                if description:
                    lines.append(description)
                    lines.append("")

                if achievements:
                    lines.append("**主要成果：**")
                    for achievement in achievements:
                        lines.append(f"- {achievement}")
                    lines.append("")

        # 技能
        skills = resume_data.get("skills", {})
        if skills:
            lines.append("## 技能")
            lines.append("")

            technical = skills.get("technical", [])
            soft = skills.get("soft", [])

            if technical:
                lines.append(f"**技术技能：** {', '.join(technical)}")
            if soft:
                lines.append(f"**软技能：** {', '.join(soft)}")
            lines.append("")

        # 教育背景
        education = resume_data.get("education", [])
        if education:
            lines.append("## 教育背景")
            lines.append("")

            for edu in education:
                school = edu.get("school", "")
                degree = edu.get("degree", "")
                major = edu.get("major", "")
                start_year = edu.get("start_year", "")
                end_year = edu.get("end_year", "")

                lines.append(f"### {school}")
                parts = [p for p in [degree, major] if p]
                if parts:
                    lines.append(" | ".join(parts))
                if start_year or end_year:
                    lines.append(f"{start_year or ''} - {end_year or '至今'}")
                lines.append("")

        return "\n".join(lines)

    def to_html(self, resume_data: Dict[str, Any], custom_css: Optional[str] = None) -> str:
        """
        转换为 HTML

        Args:
            resume_data: 简历数据
            custom_css: 自定义 CSS

        Returns:
            HTML 文本
        """
        markdown_text = self.to_markdown(resume_data)

        # 转换 Markdown 为 HTML
        if markdown:
            html_content = markdown.markdown(markdown_text, extensions=['extra', 'codehilite'])
        else:
            # 降级：简单的 Markdown 到 HTML 转换
            html_content = self._simple_markdown_to_html(markdown_text)

        # 默认 CSS
        default_css = """
        body {
            font-family: 'Helvetica Neue', 'Microsoft YaHei', Arial, sans-serif;
            line-height: 1.6;
            color: #333;
            max-width: 210mm;
            margin: 0 auto;
            padding: 20mm;
            background: white;
        }

        h1 {
            font-size: 28px;
            margin-bottom: 5px;
            color: #2c3e50;
            border-bottom: none;
        }

        h2 {
            font-size: 18px;
            margin-top: 25px;
            margin-bottom: 10px;
            border-bottom: 2px solid #3498db;
            padding-bottom: 5px;
            color: #2c3e50;
        }

        h3 {
            font-size: 16px;
            margin-top: 15px;
            margin-bottom: 5px;
            color: #34495e;
        }

        .contact-info {
            font-size: 14px;
            color: #666;
            margin-bottom: 20px;
        }

        ul, ol {
            margin-top: 5px;
            margin-bottom: 10px;
            padding-left: 20px;
        }

        li {
            margin-bottom: 3px;
        }

        strong {
            color: #2c3e50;
            font-weight: 600;
        }

        code {
            background: #f4f4f4;
            padding: 2px 5px;
            border-radius: 3px;
            font-family: 'Courier New', monospace;
        }

        @media print {
            body {
                padding: 0;
            }

            .no-print {
                display: none;
            }
        }
        """

        css = custom_css if custom_css else default_css

        html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{resume_data.get('header', {}).get('name', '简历')}</title>
    <style>
{css}
    </style>
</head>
<body>
    {html_content}
</body>
</html>"""

        return html

    async def generate_pdf(
        self,
        resume_data: Dict[str, Any],
        output_path: str,
        output_format: str = "pdf"
    ) -> str:
        """
        生成 PDF 简历

        Args:
            resume_data: 简历数据
            output_path: 输出路径
            output_format: 输出格式（pdf/html/markdown）

        Returns:
            生成的文件路径
        """
        self.logger.info(f"开始生成简历: {output_path}")

        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)

        if output_format == "markdown":
            markdown_text = self.to_markdown(resume_data)
            output_file = output_file.with_suffix(".md")
            output_file.write_text(markdown_text, encoding="utf-8")

        elif output_format == "html":
            html_text = self.to_html(resume_data)
            output_file = output_file.with_suffix(".html")
            output_file.write_text(html_text, encoding="utf-8")

        elif output_format == "pdf":
            # 尝试使用 WeasyPrint
            try:
                from weasyprint import HTML

                html_text = self.to_html(resume_data)
                output_file = output_file.with_suffix(".pdf")

                HTML(string=html_text).write_pdf(str(output_file))
                self.logger.info(f"PDF 生成成功: {output_file}")

            except ImportError:
                self.logger.warning("WeasyPrint 未安装，尝试使用其他方法")

                # 尝试使用 pdfkit
                try:
                    import pdfkit

                    html_text = self.to_html(resume_data)
                    output_file = output_file.with_suffix(".pdf")

                    pdfkit.from_string(html_text, str(output_file))
                    self.logger.info(f"PDF 生成成功: {output_file}")

                except ImportError:
                    # 降级：生成 HTML 并提示用户
                    self.logger.error("无法生成 PDF，请安装 WeasyPrint 或 pdfkit")
                    html_text = self.to_html(resume_data)
                    output_file = output_file.with_suffix(".html")
                    output_file.write_text(html_text, encoding="utf-8")
                    self.logger.info(f"已生成 HTML: {output_file}")

        else:
            raise ValueError(f"不支持的输出格式: {output_format}")

        return str(output_file)

    def _simple_markdown_to_html(self, markdown_text: str) -> str:
        """简单的 Markdown 到 HTML 转换（降级方案）"""
        html = markdown_text
        html = html.replace('# ', '<h1>').replace('\n#', '</h1>')
        html = html.replace('## ', '<h2>').replace('\n##', '</h2>')
        html = html.replace('### ', '<h3>').replace('\n###', '</h3>')
        html = html.replace('**', '<strong>').replace('**', '</strong>')
        html = html.replace('- ', '<li>').replace('\n', '</li>')
        return html

    def get_desktop_path(self) -> Path:
        """获取桌面路径"""
        if os.name == 'nt':  # Windows
            desktop = Path(os.path.expanduser("~/Desktop"))
        else:  # macOS / Linux
            desktop = Path(os.path.expanduser("~/Desktop"))

        return desktop

    async def generate_and_download(
        self,
        resume_data: Dict[str, Any],
        company_name: str,
        output_format: str = "pdf"
    ) -> str:
        """
        生成并下载到桌面

        Args:
            resume_data: 简历数据
            company_name: 公司名称（用于命名）
            output_format: 输出格式

        Returns:
            生成的文件路径
        """
        # 获取桌面路径
        desktop = self.get_desktop_path()
        output_dir = desktop / "JobHunter_Resumes"
        output_dir.mkdir(exist_ok=True)

        # 生成文件名
        name = resume_data.get("header", {}).get("name", "简历")
        safe_company = "".join(c for c in company_name if c.isalnum() or c in ('-', '_'))
        filename = f"{safe_company}_{name}"
        output_path = output_dir / filename

        # 生成文件
        return await self.generate_pdf(resume_data, str(output_path), output_format)

    def export_to_json(self, resume_data: Dict[str, Any], output_path: str):
        """
        导出为 JSON

        Args:
            resume_data: 简历数据
            output_path: 输出路径
        """
        import json

        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)

        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(resume_data, f, ensure_ascii=False, indent=2)

        self.logger.info(f"JSON 导出成功: {output_file}")