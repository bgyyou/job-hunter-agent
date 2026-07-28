"""Coordinator tool implementations.

所有 _tool_parse_resume / _tool_analyze_jd / _tool_analyze_match / _tool_generate_optimization /
_tool_generate_resume / _tool_generate_cover_letter / _tool_evaluate_workflow /
_tool_submit_application / _tool_batch_submit，从原 coordinator.py 整体迁移，业务逻辑零改动。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger

from tools.llm import LLMMessage


class CoordinatorToolsMixin:
    """Tool implementation mixin. Expects self.tools dict (resume_parser/jd_analyzer/...)."""

    # ============================================================
    # 简历/JD/匹配/生成工具
    # ============================================================

    async def _tool_parse_resume(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """工具：解析简历"""
        span = self.start_span("tool:parse_resume")

        try:
            resume_file = input_data.get("resume_file")
            resume_text = input_data.get("resume_text")

            if resume_file:
                # 从文件解析
                logger.info(f"从文件解析简历: {resume_file}")
                resume_data = await self.resume_parser.parse(resume_file)
            elif resume_text:
                # 从文本解析
                logger.info("从文本解析简历")
                resume_data = await self.resume_parser.parse_from_text(resume_text)
            else:
                return {"status": "error", "error": "未提供简历文件或文本"}

            if span:
                self.end_span(True)

            return {
                "status": "success",
                "resume_data": resume_data
            }

        except Exception as e:
            self.logger.error(f"简历解析失败: {e}")
            if span:
                self.end_span(False, str(e))
            return {"status": "error", "error": str(e)}

    async def _tool_analyze_jd(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """工具：分析职位描述"""
        span = self.start_span("tool:analyze_jd")

        try:
            jd_text = input_data.get("jd_text", "")
            jd_url = input_data.get("jd_url")

            if jd_text:
                logger.info("从文本分析 JD")
                jd_result = await self.jd_analyzer.parse_from_text(jd_text)
            elif jd_url:
                logger.info(f"从 URL 分析 JD: {jd_url}")
                jd_result = await self.jd_analyzer.parse_from_url(jd_url)
            else:
                return {"status": "error", "error": "未提供 JD 文本或 URL"}

            if span:
                self.end_span(True)

            return {
                "status": "success",
                "jd_result": jd_result
            }

        except Exception as e:
            self.logger.error(f"JD 分析失败: {e}")
            if span:
                self.end_span(False, str(e))
            return {"status": "error", "error": str(e)}

    async def _tool_analyze_match(self) -> Dict[str, Any]:
        """工具：分析匹配度"""
        span = self.start_span("tool:analyze_match")

        try:
            resume_data = self.state.get("resume_data")
            jd_result = self.state.get("jd_result")

            if not resume_data or not jd_result:
                return {"status": "error", "error": "缺少简历数据或 JD 数据"}

            match_result = await self._calculate_match(resume_data, jd_result)

            if span:
                self.end_span(True)

            return {
                "status": "success",
                "match_result": match_result
            }

        except Exception as e:
            self.logger.exception(f"匹配度分析失败: {e}")
            if span:
                self.end_span(False, str(e))
            return {"status": "error", "error": f"匹配度分析失败: {str(e)}"}

    async def _tool_generate_optimization(self) -> Dict[str, Any]:
        """工具：生成优化建议"""
        span = self.start_span("tool:generate_optimization")

        try:
            resume_data = self.state.get("resume_data")
            jd_result = self.state.get("jd_result")
            match_result = self.state.get("match_result")

            optimization_result = await self._generate_optimization_suggestions(
                resume_data, jd_result, match_result
            )

            if span:
                self.end_span(True)

            return {
                "status": "success",
                "optimization_result": optimization_result
            }

        except Exception as e:
            self.logger.error(f"优化建议生成失败: {e}")
            if span:
                self.end_span(False, str(e))
            return {"status": "error", "error": str(e)}

    async def _generate_optimization_suggestions(
        self,
        resume_data: Any,
        jd_result: Dict[str, Any],
        match_result: Dict[str, Any],
    ) -> Dict[str, Any]:
        """使用 LLM 生成优化建议"""
        jd_requirements_str = "\n".join(f"- {r}" for r in jd_result.get('core_requirements', []))

        prompt = f"""你是专业简历优化专家，请基于以下信息，给出简历优化建议：

职位要求：
{jd_requirements_str}

请给出3-5条具体、可执行的简历优化建议，每条建议包含：
1. 具体要修改的部分
2. 修改前的问题分析
3. 修改后的建议内容
4. 修改理由

请以 JSON 格式返回，格式如下：
{{
    "suggestions": [
        {{
            "section": "要修改的部分",
            "issue": "问题分析",
            "after": "修改建议",
            "reason": "修改理由"
        }}
    ]
}}
"""

        messages = [LLMMessage(role="user", content=prompt)]
        response = await self.llm_client.analyze(messages=messages, max_tokens=1000)

        return {"raw_suggestions": response.content}

    async def _tool_generate_resume(self) -> Dict[str, Any]:
        """工具：生成简历"""
        span = self.start_span("tool:generate_resume")

        try:
            resume_data = self.state.get("resume_data")

            if not resume_data:
                return {"status": "error", "error": "缺少简历数据"}

            resume_dict = resume_data.__dict__ if hasattr(resume_data, '__dict__') else resume_data

            markdown_content = self.resume_generator.to_markdown(resume_dict)

            output_dir = Path("data/output")
            output_dir.mkdir(exist_ok=True)

            output_path = output_dir / "optimized_resume.md"
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(markdown_content)

            if span:
                self.end_span(True)

            return {
                "status": "success",
                "markdown": markdown_content,
                "output_path": str(output_path)
            }

        except Exception as e:
            self.logger.error(f"简历生成失败: {e}")
            if span:
                self.end_span(False, str(e))
            return {"status": "error", "error": str(e)}

    async def _tool_generate_cover_letter(self) -> Dict[str, Any]:
        """工具：生成求职信"""
        span = self.start_span("tool:generate_cover_letter")

        try:
            resume_data = self.state.get("resume_data")
            jd_result = self.state.get("jd_result")

            if not resume_data or not jd_result:
                return {"status": "error", "error": "缺少简历数据或 JD 数据"}

            resume_dict = resume_data.__dict__ if hasattr(resume_data, '__dict__') else resume_data

            cover_letter = await self.cover_letter_generator.generate(
                resume_dict, jd_result, jd_result.get('company', '公司')
            )

            output_dir = Path("data/output")
            output_dir.mkdir(exist_ok=True)

            output_path = output_dir / "cover_letter.txt"
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(cover_letter)

            if span:
                self.end_span(True)

            return {
                "status": "success",
                "cover_letter": cover_letter,
                "output_path": str(output_path)
            }

        except Exception as e:
            self.logger.error(f"求职信生成失败: {e}")
            if span:
                self.end_span(False, str(e))
            return {"status": "error", "error": str(e)}

    async def _tool_evaluate_workflow(self) -> Dict[str, Any]:
        """工具：评估工作流质量 - 反思能力"""
        results = self.state.get("step_results", {})

        evaluation = {
            "workflow_quality": 0.8,
            "issues": []
        }

        completed_steps = sum(1 for r in results.values() if r.get("status") == "success")
        total_steps = len(results)

        if total_steps > 0:
            evaluation["workflow_quality"] = completed_steps / total_steps

        self.logger.info(f"工作流质量评估: {evaluation}")

        return {"status": "success", "evaluation": evaluation}

    # ============================================================
    # 投递工具
    # ============================================================

    async def _tool_submit_application(
        self,
        job_url: str,
        resume_path: str,
        cover_letter: str = "",
        platform: str = None,
        company_name: str = "",
        job_title: str = "",
    ) -> Dict[str, Any]:
        """工具：投递职位"""
        span = self.start_span("tool:submit_application")

        try:
            result = await self.auto_submitter.submit(
                job_url=job_url,
                resume_path=resume_path,
                cover_letter=cover_letter,
                platform=platform,
                company_name=company_name,
                job_title=job_title
            )

            if span:
                self.end_span(result.get("success", False))

            return result

        except Exception as e:
            self.logger.error(f"投递失败: {e}")
            if span:
                self.end_span(False, str(e))
            return {
                "success": False,
                "error": str(e)
            }

    async def _tool_batch_submit(
        self,
        jobs: list,
        resume_path: str,
        cover_letter_template: str = "",
    ) -> Dict[str, Any]:
        """工具：批量投递"""
        span = self.start_span("tool:batch_submit")

        try:
            results = await self.auto_submitter.batch_submit(
                jobs=jobs,
                resume_path=resume_path,
                cover_letter_template=cover_letter_template
            )

            if span:
                success_count = sum(1 for r in results if r.get("success"))
                self.end_span(success_count > 0)

            return {
                "success": True,
                "results": results,
                "total": len(results),
                "success_count": success_count
            }

        except Exception as e:
            self.logger.error(f"批量投递失败: {e}")
            if span:
                self.end_span(False, str(e))
            return {
                "success": False,
                "error": str(e)
            }
