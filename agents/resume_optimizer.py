# agents/resume_optimizer.py
"""
简历优化 Agent - 真正的 Agent 实现

具备能力：
1. 规划能力 - 根据差距动态选择优化策略
2. 工具调用 - 调用 LLM 生成建议/定制简历
3. 反思能力 - 评估建议质量、修正
4. 错误恢复 - LLM 失败时使用规则生成
5. 上下文感知 - 记住历史优化

新增功能（4.3 扩展）：
- 基于简历和 JD 生成具体修改建议
- 用户确认后应用修改
- 支持各部分针对性优化
"""
from typing import Dict, Any, List, Optional
from agents.base import BaseAgent, AgentPlan
from tools.llm import LLMClient, LLMMessage
from loguru import logger
import re
import copy


class ResumeOptimizer(BaseAgent):
    """
    简历优化 Agent - 真正的 Agent 实现

    功能：
    1. 根据差距生成优化建议
    2. 生成定制化简历版本
    3. 智能选择优化策略
    """

    def __init__(self, llm_client: LLMClient):
        """
        初始化简历优化 Agent

        Args:
            llm_client: LLM 客户端
        """
        super().__init__("resume_optimizer")
        self.llm_client = llm_client

        # ==================== 优化建议 Prompt ====================
        self.suggestion_system_prompt = """你是一个专业的简历优化顾问。你的目标是根据目标职位的要求，给候选人提供具体的、可操作的简历修改建议。

严格遵循以下原则：
1. **真实性**：只调整表达方式，不编造经历、技能或数据
2. **相关性**：每条建议必须与目标职位相关，不要提通用建议（如"注意格式"除非明显有问题）
3. **具体性**：给出改写后的具体内容，而不是"要突出XX能力"这样的空话
4. **保真改写**：after 版本应该是 before 版本的"职业化升级"，不是完全不同的内容
5. **优先级**：high = 直接影响匹配度，medium = 提升竞争力，low = 锦上添花"""

        self.suggestion_prompt = """请为候选人提供简历优化建议。

## 目标职位
- 职位：{title}
- 公司：{company}

## 候选人画像
- 姓名：{name}
- 工作年限：{experience_years} 年
- 现有技能：{skills}

## 项目经验
{projects}

## 职位要求
- 要求技能：{skills_required}

## 匹配差距
{gaps}

请提供优化建议："""

        self.suggestion_schema = {
            "type": "object",
            "properties": {
                "priority_actions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "优先行动项（高优先级，直接影响匹配度）"
                },
                "skill_improvements": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "技能层面的改进建议"
                },
                "project_highlights": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "项目描述优化建议"
                },
                "formatting_tips": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "格式和呈现建议"
                },
                "overall_strategy": {"type": "string", "description": "整体优化策略（2-3句话）"}
            }
        }

        # ==================== 简历定制 Prompt ====================
        self.customize_system_prompt = """你是一个专业的简历定制专家。你的任务是根据目标职位的要求，为候选人生成简历中核心部分的定制化内容。

严格遵循：
1. 只改写已有内容，不添加简历中不存在的经历或技能
2. 调整措辞和侧重点，使其与目标职位更匹配
3. 使用量化成果（如果原始简历中有数据）
4. 保持专业、简洁的书面语"""

        self.customize_prompt = """请为候选人定制简历核心内容。

## 候选人画像
- 姓名：{name}
- 工作年限：{experience_years} 年
- 技能：{skills}

## 项目经验
{projects}

## 目标职位
- 职位：{title}
- 公司：{company}
- 要求：{requirements}

请生成定制化内容："""

        self.customize_schema = {
            "type": "object",
            "properties": {
                "professional_summary": {
                    "type": "string",
                    "description": "专业概述（80-150字，突出与目标职位最相关的经验）"
                },
                "key_skills": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "按相关度排序的关键技能列表（6-10项）"
                },
                "experience_highlights": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "工作经历中的亮点（每段 1-2 句话，突出与目标职位最相关的成果）"
                },
                "project_section": {
                    "type": "string",
                    "description": "项目经历优化版（用一段话概括最相关的项目）"
                }
            }
        }

    # ==================== 规划能力 ====================

    async def plan(self, goal: str, input_data: Dict[str, Any]) -> AgentPlan:
        """
        规划优化策略 - 规划能力

        根据差距程度动态选择策略
        """
        plan = AgentPlan(goal)

        mode = input_data.get("mode", "both")
        resume = input_data.get("resume", {})
        job = input_data.get("job", {})
        gaps = input_data.get("gaps", [])

        # 分析差距程度
        gap_severity = self._analyze_gap_severity(gaps, resume, job)

        self.logger.info(f"差距分析: {gap_severity}")

        if gap_severity == "severe":
            # 严重差距：先建议再定制
            plan.add_step(
                "analyze_gaps", "analyze_gaps",
                {"resume": resume, "job": job, "gaps": gaps},
                "深度分析差距"
            )
            plan.add_step(
                "generate_suggestions", "generate_suggestions",
                {},
                "生成优化建议",
                depends_on=[0]
            )
            plan.add_step(
                "customize_resume", "customize_resume",
                {},
                "生成定制化简历",
                depends_on=[1]
            )
        elif gap_severity == "moderate":
            # 中等差距：并行生成
            if mode in ["suggestions", "both"]:
                plan.add_step(
                    "generate_suggestions", "generate_suggestions",
                    {},
                    "生成优化建议"
                )
            if mode in ["customize", "both"]:
                plan.add_step(
                    "customize_resume", "customize_resume",
                    {},
                    "生成定制化简历"
                )
        else:
            # 轻微差距：直接定制
            plan.add_step(
                "customize_resume", "customize_resume",
                {},
                "生成定制化简历"
            )

        # 评估和反思
        plan.add_step(
            "evaluate_quality", "evaluate_quality",
            {},
            "评估优化质量",
            depends_on=[i for i in range(len(plan.steps)) if plan.steps[i]["name"] != "evaluate_quality"]
        )

        return plan

    def _analyze_gap_severity(self, gaps: List[Dict], resume: Dict, job: Dict) -> str:
        """分析差距程度"""
        high_importance_gaps = [g for g in gaps if g.get("importance") == "high"]

        if len(high_importance_gaps) >= 3:
            return "severe"
        elif len(high_importance_gaps) >= 1:
            return "moderate"
        else:
            return "mild"

    def _get_goal(self, input_data: Dict[str, Any]) -> str:
        """获取目标"""
        resume = input_data.get("resume", {}).get("name", "候选人")
        job = input_data.get("job", {}).get("title", "目标职位")
        return f"优化 {resume} 的简历以匹配 {job}"

    # ==================== 工具注册 ====================

    def _register_default_tools(self):
        """注册工具"""
        self.register_tool(
            "analyze_gaps",
            "深度分析匹配差距",
            self._tool_analyze_gaps
        )
        self.register_tool(
            "generate_suggestions",
            "生成优化建议",
            self._tool_generate_suggestions
        )
        self.register_tool(
            "customize_resume",
            "生成定制化简历",
            self._tool_customize_resume
        )
        self.register_tool(
            "evaluate_quality",
            "评估优化质量",
            self._tool_evaluate_quality
        )

    async def _tool_analyze_gaps(
        self,
        resume: Dict[str, Any],
        job: Dict[str, Any],
        gaps: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """工具：分析差距"""
        analysis = {
            "gap_count": len(gaps),
            "high_importance_count": sum(1 for g in gaps if g.get("importance") == "high"),
            "medium_importance_count": sum(1 for g in gaps if g.get("importance") == "medium"),
            "skill_gap_count": sum(1 for g in gaps if g.get("type") == "missing_skill"),
            "recommendation_strategy": ""
        }

        # 生成策略建议
        if analysis["high_importance_count"] >= 3:
            analysis["recommendation_strategy"] = "需要重点补充技能和经验"
        elif analysis["high_importance_count"] >= 1:
            analysis["recommendation_strategy"] = "需要调整项目描述以突出相关经验"
        else:
            analysis["recommendation_strategy"] = "微调简历格式和措辞即可"

        self.logger.info(f"差距分析: {analysis}")
        return analysis

    async def _tool_generate_suggestions(self) -> Dict[str, Any]:
        """工具：生成优化建议"""
        span = self.start_span("llm_suggestions")

        try:
            # 从状态获取上下文
            resume = self.state.get("current_resume", {})
            job = self.state.get("current_job", {})
            gaps = self.state.get("current_gaps", [])

            # 格式化数据
            skills = ", ".join(resume.get("skills", []))
            projects = "\n".join([
                f"- {p.get('name')}: {p.get('description', '')}"
                for p in resume.get("projects", [])
            ]) or "无"
            gaps_text = "\n".join([
                f"- {g.get('type')}: {g.get('description')} ({g.get('importance')})"
                for g in gaps
            ]) or "无"

            # 构建 Prompt
            prompt = self.suggestion_prompt.format(
                name=resume.get("name", ""),
                experience_years=resume.get("experience_years", 0),
                email=resume.get("email", ""),
                skills=skills,
                projects=projects,
                title=job.get("title", ""),
                company=job.get("company", ""),
                skills_required=", ".join(job.get("tags", [])),
                gaps=gaps_text
            )

            messages = [
                LLMMessage(role="system", content=self.suggestion_system_prompt),
                LLMMessage(role="user", content=prompt)
            ]

            result = await self.llm_client.analyze_with_structured_output(
                messages=messages,
                output_schema=self.suggestion_schema,
                temperature=0.2
            )

            # 记录 Token 使用
            tokens = self.llm_client.estimate_tokens(prompt + str(result))
            self.record_llm_call(tokens)

            if span:
                self.end_span(True)

            return result

        except Exception as e:
            self.logger.error(f"生成建议失败: {e}")
            if span:
                self.end_span(False, str(e))
            raise

    async def _tool_customize_resume(self) -> Dict[str, Any]:
        """工具：生成定制化简历"""
        span = self.start_span("llm_customize")

        try:
            resume = self.state.get("current_resume", {})
            job = self.state.get("current_job", {})

            # 格式化数据
            skills = ", ".join(resume.get("skills", []))
            projects = "\n".join([
                f"{p.get('name')}: {p.get('description', '')}"
                for p in resume.get("projects", [])
            ]) or "无"

            job_reqs = job.get("parsed_sections", {}).get("requirements", [])
            requirements_str = "; ".join(job_reqs) if isinstance(job_reqs, list) else str(job_reqs or "")

            # 构建 Prompt
            prompt = self.customize_prompt.format(
                name=resume.get("name", ""),
                experience_years=resume.get("experience_years", 0),
                skills=skills,
                projects=projects,
                title=job.get("title", ""),
                company=job.get("company", ""),
                requirements=requirements_str
            )

            messages = [
                LLMMessage(role="system", content=self.customize_system_prompt),
                LLMMessage(role="user", content=prompt)
            ]

            result = await self.llm_client.analyze_with_structured_output(
                messages=messages,
                output_schema=self.customize_schema,
                temperature=0.2
            )

            # 记录 Token 使用
            tokens = self.llm_client.estimate_tokens(prompt + str(result))
            self.record_llm_call(tokens)

            if span:
                self.end_span(True)

            return result

        except Exception as e:
            self.logger.error(f"定制简历失败: {e}")
            if span:
                self.end_span(False, str(e))
            raise

    async def _tool_evaluate_quality(self) -> Dict[str, Any]:
        """工具：评估优化质量 - 反思能力"""
        results = self.state.get("step_results", {})

        evaluation = {
            "suggestions_quality": 0.8,
            "resume_quality": 0.8,
            "overall_score": 0.8,
            "issues": []
        }

        # 评估建议质量
        if "generate_suggestions" in results:
            suggestions = results["generate_suggestions"]
            priority_count = len(suggestions.get("priority_actions", []))
            skill_count = len(suggestions.get("skill_improvements", []))

            if priority_count >= 3:
                evaluation["suggestions_quality"] = 1.0
            elif priority_count >= 1:
                evaluation["suggestions_quality"] = 0.8
            else:
                evaluation["suggestions_quality"] = 0.5
                evaluation["issues"].append("优化建议缺少优先行动")

        # 评估定制简历质量
        if "customize_resume" in results:
            customized = results["customize_resume"]
            summary_len = len(customized.get("professional_summary", ""))
            key_skills_count = len(customized.get("key_skills", []))

            if summary_len > 50 and key_skills_count >= 3:
                evaluation["resume_quality"] = 1.0
            elif summary_len > 20 and key_skills_count >= 1:
                evaluation["resume_quality"] = 0.8
            else:
                evaluation["resume_quality"] = 0.5
                evaluation["issues"].append("定制化简历内容过少")

        # 计算总体分数
        evaluation["overall_score"] = (
            evaluation["suggestions_quality"] + evaluation["resume_quality"]
        ) / 2

        self.logger.info(f"质量评估: {evaluation}")
        return evaluation

    # ==================== 反思能力 ====================

    async def _evaluate_step_result(self, step: Dict, result: Any) -> float:
        """评估步骤结果质量"""
        if step["name"] in ["generate_suggestions", "customize_resume"]:
            # 简单评估：有内容就是高质量
            if isinstance(result, dict):
                content_count = sum(1 for v in result.values() if v)
                return min(content_count / 4, 1.0)
            return 0.5

        elif step["name"] == "evaluate_quality":
            evaluation = result
            return evaluation.get("overall_score", 0.8)

        return 1.0

    async def _correct_result(self, step: Dict, result: Any, quality: float) -> Any:
        """修正结果"""
        if quality < 0.7 and isinstance(result, dict):
            self.logger.warning("结果质量偏低，补充默认内容")

            if step["name"] == "generate_suggestions":
                result.setdefault("priority_actions", ["补充缺失技能", "优化项目描述"])
                result.setdefault("skill_improvements", ["学习相关技术栈"])
                result.setdefault("project_highlights", ["突出相关项目经验"])
                result.setdefault("formatting_tips", ["使用清晰的结构"])
                result.setdefault("overall_strategy", "根据职位要求调整简历")

            elif step["name"] == "customize_resume":
                resume = self.state.get("current_resume", {})
                result.setdefault("professional_summary", f"{resume.get('name', '候选人')}，{resume.get('experience_years', 0)} 年经验")
                result.setdefault("key_skills", resume.get("skills", [])[:5])
                result.setdefault("experience_highlights", ["有相关项目经验"])
                result.setdefault("project_section", "展示主要项目")

            return result

        return result

    async def _recover_from_failure(self, step: Dict, error: Exception,
                                     results: Dict) -> Optional[Dict]:
        """从失败中恢复"""
        step_name = step["name"]

        if step_name in ["generate_suggestions", "customize_resume"]:
            self.logger.info("降级为规则生成")

            resume = self.state.get("current_resume", {})
            job = self.state.get("current_job", {})

            # 规则生成
            missing_skills = set(s.lower() for s in job.get("tags", [])) - \
                           set(s.lower() for s in resume.get("skills", []))

            if step_name == "generate_suggestions":
                return {
                    "priority_actions": [f"学习 {s}" for s in list(missing_skills)[:3]],
                    "skill_improvements": ["加强实践", "学习最佳实践"],
                    "project_highlights": ["突出相关技术"],
                    "formatting_tips": ["使用清晰的结构"],
                    "overall_strategy": "根据职位要求补充技能"
                }
            else:
                return {
                    "professional_summary": f"{resume.get('name', '候选人')}，{resume.get('experience_years', 0)} 年经验",
                    "key_skills": list(missing_skills)[:5] or resume.get("skills", []),
                    "experience_highlights": ["持续学习新技术"],
                    "project_section": "展示核心项目"
                }

        return None

    # ==================== 核心执行 ====================

    async def execute(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行简历优化

        Args:
            input_data: 输入数据，应包含：
                - resume: 简历画像
                - job: 职位信息
                - gaps: 匹配差距（可选）
                - mode: 优化模式（suggestions/customize/both，默认 both）

        Returns:
            优化结果
        """
        self.log_action("start_resume_optimization", input_data)

        try:
            mode = input_data.get("mode", "both")
            resume = input_data["resume"]
            job = input_data["job"]
            gaps = input_data.get("gaps", [])

            # 保存到状态，供工具使用
            self.state["current_resume"] = resume
            self.state["current_job"] = job
            self.state["current_gaps"] = gaps

            result = {}

            # 生成优化建议
            if mode in ["suggestions", "both"]:
                try:
                    suggestions = await self._tool_generate_suggestions()
                    result["suggestions"] = suggestions
                except Exception as e:
                    self.logger.warning(f"生成建议失败: {e}")
                    result["suggestions"] = await self._recover_from_failure(
                        {"name": "generate_suggestions"}, e, {}
                    )

            # 生成定制化简历
            if mode in ["customize", "both"]:
                try:
                    customized = await self._tool_customize_resume()
                    result["customized_resume"] = customized
                except Exception as e:
                    self.logger.warning(f"定制简历失败: {e}")
                    result["customized_resume"] = await self._recover_from_failure(
                        {"name": "customize_resume"}, e, {}
                    )

            # 生成决策理由
            reasoning = self._generate_reasoning(
                resume=resume,
                job=job,
                mode=mode,
                gaps=gaps
            )
            self.set_reasoning(reasoning)

            # 保存状态
            self.state["last_optimization"] = {
                "job_title": job.get("title"),
                "mode": mode,
                "result_keys": list(result.keys())
            }
            self.save_state()

            self.log_action("optimization_complete", {"mode": mode})

            return {
                "status": "success",
                "reasoning": self.reasoning,
                **result
            }

        except Exception as e:
            self.logger.error(f"简历优化失败: {e}")
            return {
                "status": "error",
                "error": str(e),
                "agent": self.name
            }

    def _generate_reasoning(
        self,
        resume: Dict[str, Any],
        job: Dict[str, Any],
        mode: str,
        gaps: Optional[List[Dict[str, Any]]] = None
    ) -> str:
        """生成决策理由"""
        parts = []

        parts.append(f"【优化对象】简历: {resume.get('name', '未知')}")
        parts.append(f"【目标职位】{job.get('title', '')} - {job.get('company', '')}")

        if mode == "suggestions":
            parts.append("【优化模式】仅生成优化建议")
        elif mode == "customize":
            parts.append("【优化模式】仅生成定制化简历")
        else:
            parts.append("【优化模式】优化建议 + 定制化简历")

        # 分析技能匹配度
        resume_skills = set(s.lower() for s in resume.get("skills", []))
        job_skills = set(s.lower() for s in job.get("tags", []))

        matched = resume_skills & job_skills
        missing = job_skills - resume_skills

        if matched:
            parts.append(f"【已匹配技能】{len(matched)} 项: {', '.join(list(matched)[:3])}")

        if missing:
            parts.append(f"【待补充技能】{len(missing)} 项: {', '.join(list(missing)[:3])}")

        # 差距分析
        if gaps:
            high_count = sum(1 for g in gaps if g.get("importance") == "high")
            parts.append(f"【关键差距】{high_count} 项")

        return "\n".join(parts)

    def validate_input(self, input_data: Dict[str, Any]) -> bool:
        """验证输入"""
        if not super().validate_input(input_data):
            return False

        if "resume" not in input_data:
            self.logger.error("缺少简历信息")
            return False

        if "job" not in input_data:
            self.logger.error("缺少职位信息")
            return False

        return True

    # ==================== 新架构扩展（4.3） ====================

    async def generate_suggestions(
        self,
        resume_data: Dict[str, Any],
        job_profile: Dict[str, Any],
        company_name: str = ""
    ) -> Dict[str, Any]:
        """
        生成详细的修改建议（新架构核心方法）
        """
        self.logger.info("开始生成优化建议")

        prompt = self._build_suggestion_prompt(resume_data, job_profile, company_name)

        system_prompt = """你是一个专业的简历优化顾问。你的目标是根据目标职位的要求，给候选人提供具体的、可操作的简历修改建议。

原则：
1. 真实性：只调整表达方式，不编造经历
2. 相关性：每条建议必须与目标职位直接相关
3. 具体性：给出完整的改写文本
4. 数量：3-8 条高质量建议
5. 格式：只返回 JSON"""

        messages = [
            LLMMessage(role="system", content=system_prompt),
            LLMMessage(role="user", content=prompt)
        ]

        schema = {
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

        try:
            result = await self.llm_client.analyze_with_structured_output(
                messages=messages,
                output_schema=schema,
                temperature=0.2
            )

            # 验证结果格式
            if "suggestions" not in result:
                result["suggestions"] = []

            # 为建议添加索引
            for idx, suggestion in enumerate(result["suggestions"]):
                suggestion["index"] = idx

            return result

        except Exception as e:
            self.logger.error(f"生成建议失败: {e}")
            return {
                "overall_assessment": "生成建议时出错",
                "suggestions": [],
                "additional_tips": ["请稍后重试"],
                "error": str(e)
            }

    def _build_suggestion_prompt(
        self,
        resume_data: Dict[str, Any],
        job_profile: Dict[str, Any],
        company_name: str
    ) -> str:
        """构建优化建议 Prompt"""

        # 格式化目标职位
        job_title = job_profile.get("title", "")
        job_company = job_profile.get("company", company_name)
        job_location = job_profile.get("location", "未知")
        job_salary = job_profile.get("salary_range", "面议")

        # 格式化职位要求
        core_reqs = "\n".join(
            f"- {req}" for req in job_profile.get("core_requirements", [])[:10]
        )
        preferred_reqs = "\n".join(
            f"- {req}" for req in job_profile.get("preferred_requirements", [])[:5]
        )
        keywords = ", ".join(job_profile.get("keywords", [])[:10])
        implicit_reqs = job_profile.get("implicit_requirements", "无明显隐性要求")

        # 格式化简历
        header = resume_data.get("header", {})
        name = header.get("name", "")
        summary = header.get("summary", "")

        experience_text = self._format_resume_experience(resume_data.get("experience", []))
        projects_text = self._format_resume_projects(resume_data.get("projects", []))
        skills_text = self._format_resume_skills(resume_data.get("skills", {}))

        return f"""你是一位专业的简历优化专家，擅长根据目标职位优化简历表达方式。

## 目标职位
- 职位名称：{job_title}
- 公司：{company_name if company_name else job_company}
- 地点：{job_location}
- 薪资：{job_salary}

## 职位要求
**核心要求：**
{core_reqs if core_reqs else '见职位描述'}

**加分项：**
{preferred_reqs if preferred_reqs else '无'}

**关键词：**
{keywords if keywords else '无'}

**隐性要求：**
{implicit_reqs}

## 候选人简历

**姓名：** {name}
**个人陈述：** {summary if summary else '（未提供）'}

**工作经历：**
{experience_text if experience_text else '（未提供）'}

**项目经历：**
{projects_text if projects_text else '（未提供）'}

**技能：**
{skills_text if skills_text else '（未提供）'}

## 任务

请逐条给出具体的修改建议，每条包含：
- section: 修改位置（summary|experience|projects|skills|education）
- target_id: 具体位置（如 experience[0]）
- before: 当前内容
- issue: 为什么需要改
- after: 修改后的内容（保持真实性，只优化表达方式）
- reasoning: 为什么这样改能提高匹配度
- priority: high/medium/low

## 约束
1. 真实性：不编造经历或技能，只调整表达
2. 相关性：每条建议必须与目标职位直接相关
3. 具体性：给出完整的改写文本，不说"要突出XX"
4. 数量：3-8 条高质量建议
5. 格式：只返回 JSON"""

    def _format_resume_experience(self, experience: list) -> str:
        """格式化简历工作经历"""
        if not experience:
            return ""

        lines = []
        for idx, exp in enumerate(experience):
            title = exp.get("title", "")
            company = exp.get("company", "")
            duration = exp.get("duration", "")
            description = exp.get("description", "")

            lines.append(f"[experience[{idx}]] {title} @ {company} ({duration})")
            lines.append(f"描述：{description[:100]}...")
            lines.append("")

        return "\n".join(lines)

    def _format_resume_projects(self, projects: list) -> str:
        """格式化简历项目经历"""
        if not projects:
            return ""

        lines = []
        for idx, proj in enumerate(projects):
            name = proj.get("name", "")
            role = proj.get("role", "")
            description = proj.get("description", "")

            lines.append(f"[projects[{idx}]] {name} ({role})")
            lines.append(f"描述：{description[:100]}...")
            lines.append("")

        return "\n".join(lines)

    def _format_resume_skills(self, skills: dict) -> str:
        """格式化简历技能"""
        if not skills:
            return ""

        parts = []
        if skills.get("technical"):
            parts.append(f"技术：{', '.join(skills['technical'])}")
        if skills.get("soft"):
            parts.append(f"软技能：{', '.join(skills['soft'])}")

        return "\n".join(parts)

    def apply_confirmations(
        self,
        resume_data: Dict[str, Any],
        suggestions: Dict[str, Any],
        confirmations: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        根据用户确认应用修改

        Args:
            resume_data: 原始简历数据
            suggestions: 优化建议
            confirmations: 用户确认

        Returns:
            修改后的简历数据
        """
        self.logger.info("开始应用用户确认的修改")

        final_resume = copy.deepcopy(resume_data)

        for confirmation in confirmations.get("suggestions", []):
            idx = confirmation.get("index")
            confirmed = confirmation.get("confirmed", False)
            custom_after = confirmation.get("custom_after")

            if not confirmed:
                continue

            # 获取对应的建议
            if idx < len(suggestions.get("suggestions", [])):
                suggestion = suggestions["suggestions"][idx]
            else:
                continue

            # 获取修改内容
            modified_content = custom_after if custom_after else suggestion.get("after")

            if not modified_content:
                continue

            # 应用到对应部分
            section = suggestion.get("section")
            target_id = suggestion.get("target_id", "")

            try:
                if section == "summary":
                    final_resume["header"]["summary"] = modified_content

                elif section == "experience":
                    # 解析 target_id 如 "experience[0]"
                    match = re.search(r'experience\[(\d+)\]', target_id)
                    if match:
                        exp_idx = int(match.group(1))
                        if exp_idx < len(final_resume.get("experience", [])):
                            final_resume["experience"][exp_idx]["description"] = modified_content

                elif section == "projects":
                    match = re.search(r'projects\[(\d+)\]', target_id)
                    if match:
                        proj_idx = int(match.group(1))
                        if proj_idx < len(final_resume.get("projects", [])):
                            final_resume["projects"][proj_idx]["description"] = modified_content

                elif section == "skills":
                    # 技能可能需要特殊处理，这里是简化版本
                    if isinstance(modified_content, list):
                        final_resume["skills"]["technical"] = modified_content
                    elif isinstance(modified_content, str):
                        # 尝试解析逗号分隔的技能
                        final_resume["skills"]["technical"] = [
                            s.strip() for s in modified_content.split(",") if s.strip()
                        ]

                self.logger.info(f"已应用修改: {section} - {target_id}")

            except (KeyError, IndexError, ValueError) as e:
                self.logger.warning(f"应用修改失败: {section} - {target_id}, 错误: {e}")

        return final_resume

    def get_suggestions_by_priority(
        self,
        suggestions: Dict[str, Any],
        priority: str = "high"
    ) -> List[Dict[str, Any]]:
        """
        按优先级筛选建议

        Args:
            suggestions: 优化建议
            priority: 优先级

        Returns:
            筛选后的建议列表
        """
        all_suggestions = suggestions.get("suggestions", [])
        return [s for s in all_suggestions if s.get("priority") == priority]

    def get_suggestions_by_section(
        self,
        suggestions: Dict[str, Any],
        section: str
    ) -> List[Dict[str, Any]]:
        """
        按章节筛选建议

        Args:
            suggestions: 优化建议
            section: 章节名称

        Returns:
            筛选后的建议列表
        """
        all_suggestions = suggestions.get("suggestions", [])
        return [s for s in all_suggestions if s.get("section") == section]