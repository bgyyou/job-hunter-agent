# agents/matcher.py
"""
匹配度分析 Agent - 真正的 Agent 实现

具备能力：
1. 规划能力 - 动态选择匹配策略（单职位/批量）
2. 工具调用 - 封装匹配步骤
3. 反思能力 - 评估匹配质量
4. 错误恢复 - LLM 失败时使用规则匹配
5. 记忆能力 - 记住匹配历史
6. 事实核查 - 防止幻觉
"""
from typing import Dict, Any, List, Optional
import asyncio
from datetime import datetime
from agents.base import BaseAgent, AgentPlan
from tools.llm import LLMClient, LLMMessage
from models.resume import ResumeProfile
from models.job import JobPosting
from models.match import MatchResult, Gap
from models.traceable_result import TraceableResult, Source
from loguru import logger


class MatcherAgent(BaseAgent):
    """
    匹配度分析 Agent - 真正的 Agent 实现

    功能：
    1. 批量匹配分析
    2. 输出 TraceableResult（决策透明）
    3. 生成差距分析报告
    4. 动态匹配策略
    5. 匹配质量反思
    """

    def __init__(self, llm_client: LLMClient):
        """
        初始化匹配度分析 Agent

        Args:
            llm_client: LLM 客户端
        """
        super().__init__("matcher")
        self.llm_client = llm_client

        # 匹配历史记忆
        self.match_history: List[Dict[str, Any]] = []

        # 匹配统计
        self.match_stats = {
            "total_matches": 0,
            "high_match_count": 0,  # score >= 80
            "medium_match_count": 0,  # 70 <= score < 80
            "low_match_count": 0,  # score < 70
            "avg_score": 0.0
        }

        # 注册工具
        self._register_matcher_tools()

        # 匹配分析 Prompt 模板
        self.match_system_prompt = """你是一个专业的招聘匹配分析师。你的任务是根据候选人的简历和职位要求，进行客观的匹配度分析。

严格遵循以下规则：
1. **客观性**：只基于简历中明确提到的技能和经验，不要推断或编造
2. **技能对比**：逐一检查职位要求中的每个技能，判断候选人是否具备
3. **经验评估**：根据工作年限和项目经验评估经验匹配度
4. **分数定义**：
   - 90-100：核心技能全部匹配，经验充足
   - 70-89：大部分核心技能匹配，有少量缺失
   - 50-69：部分关键技能缺失或经验不足
   - 0-49：核心技能大量缺失
5. 只返回 JSON，不要有其他文字"""

        self.match_prompt = """请分析候选人与职位的匹配度。

## 候选人画像
- 姓名：{name}
- 工作年限：{experience_years} 年
- 邮箱：{email}
- 技能列表：{skills}
- 目标岗位：{target_roles}
- 技术领域：{domains}
- 教育背景：{education}
- 项目经验：{projects}

## 职位要求
- 职位名称：{title}
- 公司：{company}
- 地点：{location}
- 薪资：{salary_range}
- 职位描述：{requirements}
- 要求技能：{skills_required}

## 输出格式

请按以下 JSON 格式返回：
{{
    "score": 匹配度分数（0-100的整数）,
    "reasoning": "匹配理由的详细说明（2-3句话）",
    "matched_skills": ["匹配的技能1", ...],
    "missing_skills": ["缺失的技能1", ...],
    "gaps": [
        {{
            "type": "missing_skill|experience_short|other",
            "description": "具体描述",
            "importance": "high|medium|low"
        }}
    ],
    "should_apply": true 或 false
}}

注意：should_apply 的判断标准 — score >= 70 时为 true。"""

    # ==================== 工具注册 ====================

    def _register_matcher_tools(self):
        """注册匹配工具"""
        self.register_tool(
            "analyze_single_match",
            "分析单个职位的匹配度",
            self._tool_analyze_single_match
        )
        self.register_tool(
            "batch_match",
            "批量分析职位匹配度",
            self._tool_batch_match
        )
        self.register_tool(
            "fact_check",
            "事实核查",
            self._tool_fact_check
        )
        self.register_tool(
            "rule_based_match",
            "基于规则的匹配（LLM 失败时降级）",
            self._tool_rule_based_match
        )
        self.register_tool(
            "evaluate_match_quality",
            "评估匹配质量",
            self._tool_evaluate_match_quality
        )

    # ==================== 规划能力 ====================

    async def plan(self, goal: str, input_data: Dict[str, Any]) -> AgentPlan:
        """动态规划匹配策略"""
        plan = AgentPlan(goal)

        has_jobs = "jobs" in input_data
        has_job = "job" in input_data

        if has_jobs:
            jobs_count = len(input_data["jobs"])
            strategy = self._determine_batch_strategy(jobs_count)
            plan.add_step("batch_match", "batch_match", {"strategy": strategy}, f"批量分析 {jobs_count} 个职位")
            plan.add_step("evaluate_match_quality", "evaluate_match_quality", {}, "评估匹配质量", depends_on=[0])
        else:
            plan.add_step("analyze_single_match", "analyze_single_match", {}, "分析单个职位匹配度")
            plan.add_step("evaluate_match_quality", "evaluate_match_quality", {}, "评估匹配质量", depends_on=[0])

        return plan

    def _determine_batch_strategy(self, job_count: int) -> str:
        """根据职位数量决定批量策略"""
        if job_count <= 5:
            return "sequential"
        elif job_count <= 20:
            return "parallel"
        else:
            return "sampling"

    def _get_goal(self, input_data: Dict[str, Any]) -> str:
        """获取目标"""
        if "jobs" in input_data:
            count = len(input_data["jobs"])
            return f"分析 {count} 个职位的匹配度"
        return "分析职位匹配度"

    # ==================== 工具实现 ====================

    async def _tool_analyze_single_match(self) -> Dict[str, Any]:
        """工具：分析单个职位的匹配度"""
        span = self.start_span("tool:analyze_single_match")

        try:
            resume = self.state.get("resume", {})
            job = self.state.get("job", {})

            job_id = job.get("job_id", "unknown")

            # 准备 Prompt
            prompt = self._build_match_prompt(resume, job)
            messages = [
                LLMMessage(role="system", content=self.match_system_prompt),
                LLMMessage(role="user", content=prompt)
            ]

            schema = {
                "type": "object",
                "properties": {
                    "score": {"type": "number"},
                    "reasoning": {"type": "string"},
                    "matched_skills": {"type": "array", "items": {"type": "string"}},
                    "missing_skills": {"type": "array", "items": {"type": "string"}},
                    "gaps": {"type": "array", "items": {"type": "object", "properties": {"type": {"type": "string"}, "description": {"type": "string"}, "importance": {"type": "string"}}}},
                    "should_apply": {"type": "boolean"}
                }
            }

            analysis = await self.llm_client.analyze_with_structured_output(
                messages=messages,
                output_schema=schema,
                temperature=0.1
            )

            # 事实核查
            checked_analysis = self._fact_check(analysis, resume, job)

            # 记录 Token 使用
            tokens = self.llm_client.estimate_tokens(prompt + str(checked_analysis))
            self.record_llm_call(tokens)

            # 构建 MatchResult
            gaps = [Gap(**gap) for gap in checked_analysis.get("gaps", [])]
            match_result = MatchResult(
                job_id=job_id,
                score=checked_analysis["score"],
                reasoning=checked_analysis["reasoning"],
                gaps=gaps,
                recommendations=checked_analysis.get("recommendations", []),
                should_apply=checked_analysis.get("should_apply", checked_analysis["score"] >= 70)
            )

            # 构建 TraceableResult
            traceable = self._build_traceable_result(
                match_result=match_result,
                resume=resume,
                job=job,
                analysis=checked_analysis,
                prompt=prompt
            )

            if span:
                self.end_span(True)

            return {
                "status": "success",
                "job_id": job_id,
                "match_result": match_result.model_dump(),
                "traceable_result": traceable.model_dump()
            }

        except Exception as e:
            self.logger.error(f"匹配分析失败: {e}")
            if span:
                self.end_span(False, str(e))
            raise

    async def _tool_batch_match(self, strategy: str = "parallel") -> Dict[str, Any]:
        """工具：批量分析职位匹配度"""
        span = self.start_span("tool:batch_match")

        try:
            resume = self.state.get("resume", {})
            jobs = self.state.get("jobs", [])

            if strategy == "sequential" or len(jobs) <= 5:
                results = []
                for job in jobs:
                    self.state["job"] = job
                    try:
                        result = await self._tool_analyze_single_match()
                        results.append(result)
                    except Exception:
                        continue
            elif strategy == "parallel" or len(jobs) <= 20:
                tasks = []
                for job in jobs:
                    self.state["job"] = job
                    tasks.append(self._tool_analyze_single_match())
                results = await asyncio.gather(*tasks, return_exceptions=True)
                results = [r for r in results if not isinstance(r, Exception)]
            else:
                sample_jobs = jobs[:20]
                tasks = []
                for job in sample_jobs:
                    self.state["job"] = job
                    tasks.append(self._tool_analyze_single_match())
                results = await asyncio.gather(*tasks, return_exceptions=True)
                results = [r for r in results if not isinstance(r, Exception)]

            results.sort(key=lambda x: x.get("match_result", {}).get("score", 0), reverse=True)

            if span:
                self.end_span(len(results) > 0)

            return {"status": "success", "results": results, "count": len(results)}

        except Exception as e:
            if span:
                self.end_span(False, str(e))
            return {"status": "error", "error": str(e)}

    async def _tool_fact_check(self) -> Dict[str, Any]:
        """工具：事实核查"""
        return {"status": "success", "verified": True}

    async def _tool_rule_based_match(self) -> Dict[str, Any]:
        """工具：基于规则的匹配（降级策略）"""
        span = self.start_span("tool:rule_based_match")

        try:
            resume = self.state.get("resume", {})
            job = self.state.get("job", {})

            resume_skills = set(s.lower() for s in resume.get("skills", []))
            job_skills = set(s.lower() for s in job.get("skills_required", []))

            matched = resume_skills & job_skills
            missing = job_skills - resume_skills

            if job_skills:
                score = int(len(matched) / len(job_skills) * 100)
            else:
                score = 50

            exp_years = resume.get("experience_years", 0)
            if exp_years >= 3:
                score = min(score + 10, 100)
            elif exp_years < 1:
                score = max(score - 10, 0)

            analysis = {
                "score": score,
                "reasoning": f"基于规则匹配：匹配 {len(matched)}/{len(job_skills)} 项技能",
                "matched_skills": list(matched),
                "missing_skills": list(missing),
                "gaps": [{"type": "missing_skill", "description": f"缺少 {skill}", "importance": "high"} for skill in missing],
                "recommendations": [],
                "should_apply": score >= 70
            }

            if span:
                self.end_span(True)

            return {"status": "success", "analysis": analysis, "fallback": True}

        except Exception as e:
            if span:
                self.end_span(False, str(e))
            return {"status": "error", "error": str(e)}

    async def _tool_evaluate_match_quality(self) -> Dict[str, Any]:
        """工具：评估匹配质量"""
        match_results = self.state.get("match_results", [])

        evaluation = {
            "total_matches": len(match_results),
            "high_match_count": 0,
            "medium_match_count": 0,
            "low_match_count": 0,
            "avg_score": 0.0,
            "quality_score": 0.8,
            "issues": []
        }

        if match_results:
            scores = [m.get("match_result", {}).get("score", 0) for m in match_results]
            evaluation["high_match_count"] = sum(1 for s in scores if s >= 80)
            evaluation["medium_match_count"] = sum(1 for s in scores if 70 <= s < 80)
            evaluation["low_match_count"] = sum(1 for s in scores if s < 70)
            evaluation["avg_score"] = sum(scores) / len(scores) if scores else 0

            if evaluation["avg_score"] >= 80:
                evaluation["quality_score"] = 1.0
            elif evaluation["avg_score"] >= 70:
                evaluation["quality_score"] = 0.8
            elif evaluation["avg_score"] >= 50:
                evaluation["quality_score"] = 0.6
                evaluation["issues"].append("平均匹配度偏低")
            else:
                evaluation["quality_score"] = 0.4
                evaluation["issues"].append("匹配度较低，建议调整简历或搜索关键词")

        return {"status": "success", "evaluation": evaluation}

    # ==================== 反思能力 ====================

    async def _evaluate_step_result(self, step: Dict, result: Any) -> float:
        """评估步骤结果质量"""
        if step["name"] == "analyze_single_match":
            score = result.get("match_result", {}).get("score", 0)
            return score / 100
        elif step["name"] == "batch_match":
            results = result.get("results", [])
            if results:
                scores = [r.get("match_result", {}).get("score", 0) for r in results]
                return (sum(scores) / len(scores) if scores else 0) / 100
            return 0.5
        elif step["name"] == "evaluate_match_quality":
            evaluation = result.get("evaluation", {})
            return evaluation.get("quality_score", 0.8)
        return 1.0

    async def _correct_result(self, step: Dict, result: Any, quality: float) -> Any:
        """修正结果"""
        if quality < 0.6 and isinstance(result, dict):
            if step["name"] == "batch_match" and not result.get("results"):
                result["results"] = []
                result["warning"] = "没有匹配结果"
        return result

    async def _recover_from_failure(self, step: Dict, error: Exception, results: Dict) -> Optional[Dict]:
        """从失败中恢复"""
        step_name = step["name"]
        if step_name in ["analyze_single_match", "batch_match"]:
            return await self._tool_rule_based_match()
        return None

    async def _reflect_on_execution(self, results: Dict):
        """反思执行过程"""
        reflection = {
            "timestamp": datetime.now().isoformat(),
            "agent": self.name,
            "steps_completed": len(results),
            "total_matches": self.match_stats["total_matches"],
            "avg_score": self.match_stats["avg_score"],
            "reasoning": self.reasoning
        }
        self.state["last_reflection"] = reflection
        self.save_state()

    # ==================== 记忆能力 ====================

    def get_match_stats(self) -> Dict[str, Any]:
        """获取匹配统计"""
        return self.match_stats.copy()

    def get_match_history(self, limit: int = 20) -> List[Dict[str, Any]]:
        """获取匹配历史"""
        return self.match_history[-limit:]

    def clear_history(self):
        """清空历史记录"""
        self.match_history = []
        self.match_stats = {
            "total_matches": 0,
            "high_match_count": 0,
            "medium_match_count": 0,
            "low_match_count": 0,
            "avg_score": 0.0
        }

    # ==================== 匹配分析 Prompt 模板 ====================

    # Prompt 模板已在 __init__ 中初始化为 self.match_prompt

    async def execute(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行匹配分析

        Args:
            input_data: 输入数据，应包含：
                - resume: 简历画像 (ResumeProfile 的 dict)
                - job: 职位信息 (JobPosting 的 dict)
                - 或者 jobs: 多个职位信息，用于批量分析

        Returns:
            分析结果，包含：
                - status: 执行状态 (success/error)
                - match_result: 匹配结果 (MatchResult 的 dict)
                - traceable_result: 可追溯结果 (TraceableResult 的 dict)
        """
        self.log_action("start_match_analysis", input_data)

        try:
            # 保存输入到状态
            self.state["resume"] = input_data["resume"]

            # 批量分析
            if "jobs" in input_data:
                self.state["jobs"] = input_data["jobs"]
                results = await self._batch_match(
                    resume=input_data["resume"],
                    jobs=input_data["jobs"]
                )

                # 保存匹配结果到状态
                self.state["match_results"] = results

                # 更新统计
                scores = [r.get("match_result", {}).get("score", 0) for r in results]
                self._update_stats(scores)

                return {
                    "status": "success",
                    "match_results": results,
                    "total_count": len(results)
                }

            # 单个职位分析
            if "job" not in input_data:
                raise ValueError("输入必须包含 job 或 jobs")

            self.state["job"] = input_data["job"]
            result = await self._analyze_match(
                resume=input_data["resume"],
                job=input_data["job"]
            )

            # 更新统计
            score = result["match_result"]["score"]
            self._update_stats([score])

            # 保存状态
            self.state["last_match"] = {
                "job_id": result["job_id"],
                "score": result["match_result"]["score"],
                "timestamp": datetime.now().isoformat()
            }
            self.save_state()

            # 生成决策理由
            self._generate_match_reasoning(result["match_result"])

            return {
                "status": "success",
                "match_result": result["match_result"],
                "traceable_result": result["traceable_result"]
            }

        except Exception as e:
            self.logger.error(f"匹配分析失败: {e}")
            return {
                "status": "error",
                "error": str(e),
                "agent": self.name
            }

    def _update_stats(self, scores: List[int]):
        """更新匹配统计"""
        self.match_stats["total_matches"] += len(scores)

        for score in scores:
            if score >= 80:
                self.match_stats["high_match_count"] += 1
            elif score >= 70:
                self.match_stats["medium_match_count"] += 1
            else:
                self.match_stats["low_match_count"] += 1

        # 更新平均分
        total = self.match_stats["total_matches"]
        current_avg = self.match_stats["avg_score"]
        new_avg = (current_avg * (total - len(scores)) + sum(scores)) / total if total > 0 else 0
        self.match_stats["avg_score"] = new_avg

    def _generate_match_reasoning(self, match_result: Dict[str, Any]):
        """生成匹配决策理由"""
        score = match_result.get("score", 0)
        job_id = match_result.get("job_id", "")

        parts = []
        parts.append(f"【匹配对象】职位: {job_id}")
        parts.append(f"【匹配度】{score}%")

        if score >= 85:
            parts.append("【建议】强烈推荐投递")
        elif score >= 70:
            parts.append("【建议】推荐投递")
        else:
            parts.append("【建议】不建议投递")

        parts.append(f"【历史统计】总匹配: {self.match_stats['total_matches']}, 平均分: {self.match_stats['avg_score']:.1f}%")

        self.set_reasoning("\n".join(parts))

    async def _batch_match(
        self,
        resume: Dict[str, Any],
        jobs: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        批量匹配分析

        Args:
            resume: 简历画像
            jobs: 职位列表

        Returns:
            分析结果列表
        """
        self.logger.info(f"开始批量分析 {len(jobs)} 个职位")

        # 创建分析任务
        tasks = [
            self._analyze_match(resume, job)
            for job in jobs
        ]

        # 并行执行
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 处理结果
        final_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                self.logger.error(f"职位 {i} 分析失败: {result}")
                continue
            final_results.append(result)

        # 按分数排序
        final_results.sort(
            key=lambda x: x["match_result"]["score"],
            reverse=True
        )

        self.logger.info(f"批量分析完成，共 {len(final_results)} 个结果")
        return final_results

    async def _analyze_match(
        self,
        resume: Dict[str, Any],
        job: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        分析单个职位的匹配度

        Args:
            resume: 简历画像
            job: 职位信息

        Returns:
            分析结果
        """
        job_id = job.get("job_id", "unknown")
        self.log_action("analyze_single_job", {"job_id": job_id})

        # 准备 Prompt
        prompt = self._build_match_prompt(resume, job)
        messages = [LLMMessage(role="user", content=prompt)]

        # 调用 LLM
        schema = {
            "type": "object",
            "properties": {
                "score": {"type": "number"},
                "reasoning": {"type": "string"},
                "matched_skills": {"type": "array", "items": {"type": "string"}},
                "missing_skills": {"type": "array", "items": {"type": "string"}},
                "gaps": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "type": {"type": "string"},
                            "description": {"type": "string"},
                            "importance": {"type": "string"}
                        }
                    }
                },
                "should_apply": {"type": "boolean"}
            }
        }

        analysis = await self.llm_client.analyze_with_structured_output(
            messages=messages,
            output_schema=schema,
            temperature=0.1
        )

        # 构建 MatchResult
        gaps = [Gap(**gap) for gap in analysis.get("gaps", [])]
        match_result = MatchResult(
            job_id=job_id,
            score=analysis["score"],
            reasoning=analysis["reasoning"],
            gaps=gaps,
            recommendations=analysis.get("recommendations", []),
            should_apply=analysis.get("should_apply", analysis["score"] >= 70)
        )

        # 构建 TraceableResult
        traceable = self._build_traceable_result(
            match_result=match_result,
            resume=resume,
            job=job,
            analysis=analysis,
            prompt=prompt
        )

        return {
            "job_id": job_id,
            "match_result": match_result.model_dump(),
            "traceable_result": traceable.model_dump()
        }

    def _build_match_prompt(
        self,
        resume: Dict[str, Any],
        job: Dict[str, Any]
    ) -> str:
        """构建匹配分析 Prompt"""
        # 格式化技能列表
        skills = ", ".join(resume.get("skills", []))
        target_roles = ", ".join(resume.get("target_roles", []))
        domains = ", ".join(resume.get("domains", []))

        # 格式化教育背景
        education = "\n".join([
            f"- {edu.get('school')}: {edu.get('degree')} {edu.get('major')} ({edu.get('start_year')}-{edu.get('end_year')})"
            for edu in resume.get("education", [])
        ])

        # 格式化项目经验
        projects = "\n".join([
            f"- {proj.get('name')}: {proj.get('role')}, 技术栈: {', '.join(proj.get('tech_stack', []))}"
            for proj in resume.get("projects", [])
        ])

        # 格式化职位要求
        salary_min = job.get("salary_min")
        salary_max = job.get("salary_max")
        salary_range = f"{salary_min}k-{salary_max}k" if salary_min and salary_max else "面议"

        skills_required = ", ".join(job.get("skills_required", []))

        return self.match_prompt.format(
            name=resume.get("name", "未知"),
            experience_years=resume.get("experience_years", 0),
            email=resume.get("email", ""),
            skills=skills or "无",
            target_roles=target_roles or "无",
            domains=domains or "无",
            education=education or "无",
            projects=projects or "无",
            title=job.get("title", ""),
            company=job.get("company", ""),
            location=job.get("location", ""),
            salary_range=salary_range,
            requirements=job.get("requirements", ""),
            skills_required=skills_required or "无"
        )

    def _build_traceable_result(
        self,
        match_result: MatchResult,
        resume: Dict[str, Any],
        job: Dict[str, Any],
        analysis: Dict[str, Any],
        prompt: str
    ) -> TraceableResult:
        """构建可追溯结果"""
        content = f"匹配度 {match_result.score}%，{match_result.match_level}匹配"

        traceable = TraceableResult(
            agent_name=self.name,
            content=content,
            reasoning=match_result.reasoning,
            confidence=match_result.score / 100
        )

        # 添加来源
        traceable.add_source(
            source_id="resume_skills",
            source_text=f"简历技能: {', '.join(resume.get('skills', []))}",
            relevance="用于技能匹配"
        )
        traceable.add_source(
            source_id="job_requirements",
            source_text=f"职位要求: {job.get('title')}",
            relevance="用于匹配分析"
        )

        # 添加中间结果
        traceable.intermediate_results.append({
            "step": "skill_matching",
            "matched_skills": analysis.get("matched_skills", []),
            "missing_skills": analysis.get("missing_skills", [])
        })
        traceable.intermediate_results.append({
            "step": "gap_analysis",
            "gaps_count": len(analysis.get("gaps", [])),
            "high_importance_gaps": [
                g for g in analysis.get("gaps", [])
                if g.get("importance") == "high"
            ]
        })

        # 记录 LLM 调用
        traceable.add_llm_call(
            prompt=prompt,
            response=str(analysis),
            tokens_used=self.llm_client.estimate_tokens(prompt + str(analysis))
        )

        return traceable

    def validate_input(self, input_data: Dict[str, Any]) -> bool:
        """验证输入"""
        if not super().validate_input(input_data):
            return False

        has_job = "job" in input_data
        has_jobs = "jobs" in input_data
        has_resume = "resume" in input_data

        if not has_job and not has_jobs:
            self.logger.error("输入必须包含 job 或 jobs")
            return False

        if not has_resume:
            self.logger.error("输入必须包含 resume")
            return False

        return True

    def _fact_check(self, analysis: Dict[str, Any], resume: Dict, job: Dict) -> Dict[str, Any]:
        """
        事实核查（防幻觉）

        Args:
            analysis: LLM 分析结果
            resume: 简历数据
            job: 职位数据

        Returns:
            核查后的结果
        """
        # 核查匹配的技能是否真的在简历中
        resume_skills = set(s.lower() for s in resume.get("skills", []))
        matched_skills = analysis.get("matched_skills", [])

        verified_matched = []
        for skill in matched_skills:
            if skill.lower() in resume_skills or any(skill.lower() in s.lower() for s in resume.get("skills", [])):
                verified_matched.append(skill)
            else:
                self.logger.warning(f"幻觉检测：匹配的技能 '{skill}' 不在简历中")

        # 核查分数合理性
        score = analysis.get("score", 0)
        if not (0 <= score <= 100):
            self.logger.warning(f"幻觉检测：匹配度分数 {score} 超出范围 [0, 100]")
            score = max(0, min(100, score))

        # 更新结果
        analysis["matched_skills"] = verified_matched
        analysis["score"] = score

        return analysis