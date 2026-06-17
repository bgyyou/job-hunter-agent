
# agents/coordinator.py
"""
协调者 Agent - 单 Agent 调用 Tools 模式

具备能力：
1. 规划能力 - 根据前一步结果动态调整工作流
2. 工具调用 - 协调各工具模块（阶段4）
3. 反思能力 - 评估工作流质量
4. 错误恢复 - 处理失败
5. 记忆能力 - 记住工作流历史
6. 成本意识 - 缓存机制
"""
from typing import Dict, Any, List, Optional
from datetime import datetime
from pathlib import Path
import os
import json

from agents.base import BaseAgent, AgentPlan
from tools.llm import VolcanoClient, LLMMessage
from tools.resume_parser import ResumeParser, ResumeData
from tools.scraper.jd_analyzer_enhanced import JDAnalyzerEnhanced
from tools.scraper.auto_submitter import AutoSubmitter
from tools.generator.resume_generator import ResumeGenerator
from tools.generator.cover_letter_generator import CoverLetterGenerator
from core.cache import Cache
from loguru import logger


class CoordinatorAgent(BaseAgent):
    """
    协调者 Agent - 单 Agent 调用 Tools 模式

    功能：
    1. 解析简历（ResumeParser）
    2. 分析 JD（JDAnalyzerEnhanced）
    3. 匹配度分析
    4. 生成优化建议
    5. 生成简历（ResumeGenerator）
    6. 生成求职信（CoverLetterGenerator）
    7. 投递决策
    """

    def __init__(self, llm_client: VolcanoClient, cache: Optional[Cache] = None):
        """
        初始化协调者 Agent

        Args:
            llm_client: LLM 客户端
            cache: 缓存实例（可选）
        """
        super().__init__("coordinator")
        self.llm_client = llm_client
        self.cache = cache or Cache("data/coordinator_cache")

        # 初始化工具模块
        self.resume_parser = ResumeParser()
        self.jd_analyzer = JDAnalyzerEnhanced(llm_client=llm_client)
        self.resume_generator = ResumeGenerator()
        self.cover_letter_generator = CoverLetterGenerator(llm_client=llm_client)
        self.auto_submitter = AutoSubmitter()

        # 工作流状态记忆
        self.workflow_state: Dict[str, Any] = {}
        self.current_step = 0

        # 历史记录记忆
        self.execution_history: List[Dict[str, Any]] = []

        # 注册工具
        self._register_coordinator_tools()

    def _register_coordinator_tools(self):
        """注册协调者工具"""
        self.register_tool(
            "parse_resume",
            "解析简历",
            self._tool_parse_resume
        )
        self.register_tool(
            "analyze_jd",
            "分析职位描述",
            self._tool_analyze_jd
        )
        self.register_tool(
            "analyze_match",
            "分析匹配度",
            self._tool_analyze_match
        )
        self.register_tool(
            "generate_optimization",
            "生成优化建议",
            self._tool_generate_optimization
        )
        self.register_tool(
            "generate_resume",
            "生成简历",
            self._tool_generate_resume
        )
        self.register_tool(
            "generate_cover_letter",
            "生成求职信",
            self._tool_generate_cover_letter
        )
        self.register_tool(
            "submit_application",
            "投递职位",
            self._tool_submit_application
        )
        self.register_tool(
            "batch_submit",
            "批量投递",
            self._tool_batch_submit
        )
        self.register_tool(
            "evaluate_workflow",
            "评估工作流质量",
            self._tool_evaluate_workflow
        )

    async def plan(self, goal: str, input_data: Dict[str, Any]) -> AgentPlan:
        """
        动态规划工作流 - 规划能力

        根据输入动态调整工作流策略
        """
        plan = AgentPlan(goal)

        # 检查输入类型
        has_resume_file = "resume_file" in input_data
        has_jd_text = "jd_text" in input_data

        # 基础步骤
        if has_resume_file:
            plan.add_step(
                "parse_resume", "parse_resume",
                {"input_data": input_data},
                "解析简历"
            )

        if has_jd_text:
            plan.add_step(
                "analyze_jd", "analyze_jd",
                {"input_data": input_data},
                "分析职位描述",
                depends_on=[0] if has_resume_file else []
            )

        # 匹配度分析
        depends_match = []
        if has_resume_file and has_jd_text:
            depends_match = [0, 1]
        elif has_resume_file:
            depends_match = [0]
        plan.add_step(
            "analyze_match", "analyze_match",
            {},
            "分析简历与职位匹配度",
            depends_on=depends_match
        )

        # 生成优化建议
        plan.add_step(
            "generate_optimization", "generate_optimization",
            {},
            "生成简历优化建议",
            depends_on=[2]
        )

        # 生成简历
        plan.add_step(
            "generate_resume", "generate_resume",
            {},
            "生成优化后简历",
            depends_on=[3]
        )

        # 生成求职信
        plan.add_step(
            "generate_cover_letter", "generate_cover_letter",
            {},
            "生成求职信",
            depends_on=[2, 4]
        )

        # 评估工作流质量
        plan.add_step(
            "evaluate_workflow", "evaluate_workflow",
            {},
            "评估工作流质量",
            depends_on=[5]
        )

        return plan

    def _get_goal(self, input_data: Dict[str, Any]) -> str:
        """获取目标"""
        return "职位申请工作流"

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

    async def chat(self, user_message: str) -> Dict[str, Any]:
        """测试 LLM 连接"""
        from tools.llm import LLMMessage
        messages = [LLMMessage(role="user", content=user_message)]
        response = await self.llm_client.analyze(messages=messages, max_tokens=100)
        return {"status": "success", "reply": response.content}

    async def _calculate_match(self, resume_data: Any, jd_result: Dict[str, Any]) -> Dict[str, Any]:
        """计算匹配度 - 智能语义匹配 + 可迁移技能分析"""
        self.logger.info("===== 开始智能匹配度分析 =====")

        # 使用LLM进行深度分析
        llm_analysis = await self._generate_llm_match_analysis(resume_data, jd_result)

        return {
            "score": llm_analysis.get("score", 50),
            "reasoning": llm_analysis.get("reasoning", ""),
            "gaps": llm_analysis.get("gaps", []),
            "recommendations": llm_analysis.get("recommendations", []),
            "skill_mapping": llm_analysis.get("skill_mapping", []),
            "matching_skills": llm_analysis.get("matching_skills", []),
            "missing_skills": llm_analysis.get("missing_skills", [])
        }

    async def _generate_llm_match_analysis(self, resume_data: Any, jd_result: Dict[str, Any]) -> Dict[str, Any]:
        """使用 LLM 生成智能匹配度分析 - 重点关注可迁移技能"""
        from tools.llm import LLMMessage

        self.logger.info("===== 开始 LLM 智能匹配分析 =====")

        # 提取简历信息
        resume_dict = resume_data if isinstance(resume_data, dict) else resume_data.__dict__
        header = resume_dict.get('header', {})
        name = header.get('name', '候选人')

        # 提取完整工作经历（包括描述，用于可迁移技能分析）
        experience = resume_dict.get('experience', [])
        exp_full = []
        for exp in experience:
            company = exp.get('company', '')
            title = exp.get('title', '')
            desc = exp.get('description', '')
            exp_full.append(f"- {title} @ {company}\n  {desc}")

        tech_skills = resume_dict.get('skills', {}).get('technical', [])

        # 提取 JD 信息
        jd_title = jd_result.get('title', '职位')
        jd_company = jd_result.get('company', '公司')
        jd_requirements = jd_result.get('core_requirements', [])
        jd_keywords_list = jd_result.get('keywords', [])
        jd_description = jd_result.get('description', '')

        # 构建智能匹配提示词 - 重点关注可迁移技能
        prompt = f"""你是资深招聘顾问，擅长挖掘候选人的可迁移技能。请深度分析以下候选人与职位的匹配情况。

【重要原则】
1. 不要只看关键词是否完全匹配！重点分析：
   - 候选人的经验可以迁移到这个职位吗？
   - 如何用JD的话术重新包装候选人的经验？
2. 如果简历中有相关经验但用了不同的词，这也算匹配！
3. 简历优化三原则：
   - 做减法：删除与目标岗位不相关的经历/技能
   - 做加法：如果删除后简历内容不足一页，给出填充建议
   - 做包装：保留的内容用JD的话术重新表达

【候选人完整信息】
姓名：{name}
技能：{', '.join(tech_skills[:20])}

详细工作经历：
{chr(10).join(exp_full)}

【目标职位完整信息】
职位：{jd_title} @ {jd_company}
职责描述：{jd_description[:500]}

核心要求：
{chr(10).join(f'- {r}' for r in jd_requirements[:10])}

技能关键词：{', '.join(jd_keywords_list[:20])}

请按以下JSON格式返回分析结果：

{{
  "score": 75,
  "reasoning": "200字以内的整体分析，说明候选人的核心优势和可迁移技能",
  "skill_mapping": [
    {{
      "resume_skill": "小红书运营",
      "jd_requirement": "Social Media Content",
      "confidence": 0.9,
      "explanation": "小红书运营经验完全对应社交媒体内容运营要求"
    }},
    {{
      "resume_skill": "视频号运营",
      "jd_requirement": "Social Media Executive",
      "confidence": 0.85,
      "explanation": "视频号运营可以迁移到社交媒体管理岗位"
    }}
  ],
  "matching_skills": ["已匹配的技能1", "已匹配的技能2"],
  "missing_skills": ["确实缺失的技能（不是可以迁移的）"],
  "gaps": [
    {{"description": "差距描述", "importance": "high"}}
  ],
  "recommendations": [
    {{
      "type": "modify",
      "section": "工作经历",
      "original": "你简历中原有的描述",
      "suggested": "建议修改为...",
      "reason": "为什么这样改：用JD的话术重新包装，突出相关能力"
    }},
    {{
      "type": "delete",
      "section": "技能",
      "original": "Python, React, Node.js",
      "reason": "投递Marketing岗位，这些coding技能相关性较低，建议移除以突出重点"
    }},
    {{
      "type": "suggest_add",
      "section": "项目经验",
      "suggestion": "建议添加一个AI相关的个人项目，例如：使用LangChain搭建一个简单的AI问答机器人，展示你对AI工具的理解和应用能力",
      "reason": "当前简历内容较少，补充相关项目可以增加匹配度"
    }}
  ]
}}

recommendations中的type可以是：
- "modify": 修改现有内容
- "delete": 删除不相关内容
- "suggest_add": 建议补充内容

只返回JSON，不要其他文字。"""

        self.logger.info(f"发送 LLM 请求，长度: {len(prompt)}")

        try:
            messages = [LLMMessage(role="user", content=prompt)]
            response = await self.llm_client.analyze(messages=messages, max_tokens=2000, temperature=0.8)
            llm_text = response.content.strip()

            self.logger.info(f"LLM 响应成功，长度: {len(llm_text)}")
            self.logger.info(f"响应内容: {llm_text[:800]}...")

            # 尝试提取JSON
            json_start = llm_text.find('{')
            json_end = llm_text.rfind('}') + 1

            if json_start >= 0 and json_end > json_start:
                json_str = llm_text[json_start:json_end]
                result = json.loads(json_str)
                self.logger.info("JSON解析成功")
                return result

            raise ValueError(f"LLM返回格式错误: {llm_text[:300]}...")

        except Exception as e:
            self.logger.exception(f"LLM调用或解析失败: {e}")
            raise

    def _generate_match_recommendations(self, resume_data: Any, jd_result: Dict[str, Any]) -> List[str]:
        """生成匹配建议"""
        recommendations = []

        jd_keywords = set(jd_result.get('keywords', []))
        resume_skills = set()
        if hasattr(resume_data, 'skills'):
            resume_skills.update(resume_data.skills.get('technical', []))
        elif isinstance(resume_data, dict):
            resume_skills.update(resume_data.get('skills', {}).get('technical', []))

        missing_skills = list(jd_keywords - resume_skills)
        if missing_skills:
            recommendations.append(f"建议在简历中突出这些技能: {', '.join(missing_skills[:5])}")

        return recommendations

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
        match_result: Dict[str, Any]
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

    async def _evaluate_step_result(self, step: Dict, result: Any) -> float:
        """评估步骤结果质量"""
        if isinstance(result, dict):
            return 1.0 if result.get("status") == "success" else 0.0
        return 1.0

    async def _correct_result(self, step: Dict, result: Any, quality: float) -> Any:
        """修正结果"""
        return result

    async def _recover_from_failure(self, step: Dict, error: Exception, results: Dict) -> Optional[Dict]:
        """从失败中恢复 - 错误恢复"""
        step_name = step.get("name")
        self.logger.info(f"尝试恢复步骤 {step_name}")

        if step_name == "parse_resume":
            return {"status": "success", "resume_data": None}
        elif step_name == "analyze_jd":
            return {"status": "success", "jd_result": None}

        return None

    async def _reflect_on_execution(self, results: Dict):
        """对执行过程进行反思 - 反思能力"""
        reflection = {
            "timestamp": datetime.now().isoformat(),
            "agent": self.name,
            "steps_completed": len(results),
            "reasoning": self.reasoning
        }

        self.execution_history.append(reflection)
        self.state["last_reflection"] = reflection
        self.save_state()

    async def execute(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行完整工作流

        Args:
            input_data: 输入数据，应包含：
                - resume_file: 简历文件路径（可选）
                - resume_text: 简历文本（可选）
                - jd_text: JD 文本（可选）
                - jd_url: JD URL（可选）

        Returns:
            执行结果
        """
        self.log_action("start_workflow", input_data)

        try:
            self.state["original_input"] = input_data
            self.workflow_state = {
                "start_time": datetime.now().isoformat(),
                "steps": []
            }
            self.current_step = 0
            step_results = {}

            # 检查是否已有预设置的 resume_data
            resume_data = self.state.get("resume_data")
            jd_result = None

            # 步骤 1: 解析简历（仅当没有预设置 resume_data 时）
            if not resume_data and ("resume_file" in input_data or "resume_text" in input_data):
                self._update_progress("正在解析简历...", 1)
                parse_result = await self._step_parse_resume(input_data)
                step_results["parse_resume"] = parse_result
                if parse_result.get("status") == "success":
                    resume_data = parse_result.get("resume_data")
                    self.state["resume_data"] = resume_data

            # 步骤 2: 分析 JD
            if "jd_text" in input_data or "jd_url" in input_data:
                self._update_progress("正在分析职位描述...", 2)
                jd_parse_result = await self._step_analyze_jd(input_data)
                step_results["analyze_jd"] = jd_parse_result
                if jd_parse_result.get("status") == "success":
                    jd_result = jd_parse_result.get("jd_result")
                    self.state["jd_result"] = jd_result

            # 步骤 3: 匹配度分析
            if resume_data and jd_result:
                self._update_progress("正在分析匹配度...", 3)
                match_result = await self._step_analyze_match()
                step_results["analyze_match"] = match_result
                if match_result.get("status") == "success":
                    self.state["match_result"] = match_result.get("match_result")

            # 步骤 4: 生成优化建议
            if resume_data and jd_result:
                self._update_progress("正在生成优化建议...", 4)
                opt_result = await self._step_generate_optimization()
                step_results["generate_optimization"] = opt_result
                if opt_result.get("status") == "success":
                    self.state["optimization_result"] = opt_result.get("optimization_result")

            # 步骤 5: 生成简历
            if resume_data:
                self._update_progress("正在生成优化后简历...", 5)
                resume_gen_result = await self._step_generate_resume()
                step_results["generate_resume"] = resume_gen_result

            # 步骤 6: 生成求职信
            if resume_data and jd_result:
                self._update_progress("正在生成求职信...", 6)
                cl_gen_result = await self._step_generate_cover_letter()
                step_results["generate_cover_letter"] = cl_gen_result

            # 反思执行过程
            self.state["step_results"] = step_results
            await self._reflect_on_execution(step_results)

            self._update_progress("工作流完成", 6)

            final_result = self._build_success_result({
                "resume_data": resume_data,
                "jd_result": jd_result,
                "match_result": self.state.get("match_result"),
                "optimization_result": self.state.get("optimization_result"),
                "step_results": step_results,
                "summary": self._generate_summary(resume_data, jd_result, self.state.get("match_result"))
            })

            return final_result

        except Exception as e:
            self.logger.exception(f"工作流执行失败: {e}")
            return {
                "status": "error",
                "error": str(e),
                "agent": self.name
            }

    async def _step_parse_resume(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """步骤：解析简历"""
        self.current_step += 1
        return await self._tool_parse_resume(input_data)

    async def _step_analyze_jd(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """步骤：分析 JD"""
        self.current_step += 1
        return await self._tool_analyze_jd(input_data)

    async def _step_analyze_match(self) -> Dict[str, Any]:
        """步骤：分析匹配度"""
        self.current_step += 1
        return await self._tool_analyze_match()

    async def _step_generate_optimization(self) -> Dict[str, Any]:
        """步骤：生成优化建议"""
        self.current_step += 1
        return await self._tool_generate_optimization()

    async def _step_generate_resume(self) -> Dict[str, Any]:
        """步骤：生成简历"""
        self.current_step += 1
        return await self._tool_generate_resume()

    async def _step_generate_cover_letter(self) -> Dict[str, Any]:
        """步骤：生成求职信"""
        self.current_step += 1
        return await self._tool_generate_cover_letter()

    def _update_progress(self, message: str, step: int):
        """更新进度"""
        self.set_reasoning(f"【进度】{message}")

    def _generate_summary(
        self,
        resume_data: Any,
        jd_result: Dict[str, Any],
        match_result: Dict[str, Any]
    ) -> str:
        """生成工作流摘要"""
        parts = []

        if jd_result:
            parts.append(f"【职位】{jd_result.get('title', '未知')} @ {jd_result.get('company', '未知')}")

        if match_result:
            score = match_result.get('score', 0)
            parts.append(f"【匹配度】{score:.1f}%")

        parts.append(f"【完成时间】{datetime.now().strftime('%Y-%m-%d %H:%M')}")

        return "\n".join(parts)

    def _build_success_result(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """构建成功结果"""
        return {
            "status": "success",
            "workflow_summary": data["summary"],
            "resume_data": data["resume_data"],
            "jd_result": data["jd_result"],
            "match_result": data["match_result"],
            "optimization_result": data.get("optimization_result"),
            "step_results": data.get("step_results"),
            "reasoning": self.reasoning
        }

    def _build_error_result(
        self,
        error_message: str,
        error_result: Dict[str, Any]
    ) -> Dict[str, Any]:
        """构建错误结果"""
        return {
            "status": "error",
            "error": error_message,
            "details": error_result,
            "workflow_state": self.workflow_state
        }

    def get_workflow_status(self) -> Dict[str, Any]:
        """获取当前工作流状态"""
        return {
            "current_step": self.current_step,
            "steps": self.workflow_state.get("steps", []),
            "reasoning": self.reasoning
        }

    def validate_input(self, input_data: Dict[str, Any]) -> bool:
        """验证输入"""
        if not super().validate_input(input_data):
            return False

        has_resume = "resume_file" in input_data or "resume_text" in input_data
        has_jd = "jd_text" in input_data or "jd_url" in input_data

        if not has_resume and not has_jd:
            self.logger.error("至少需要提供简历或 JD")
            return False

        return True

    async def _tool_submit_application(
        self,
        job_url: str,
        resume_path: str,
        cover_letter: str = "",
        platform: str = None,
        company_name: str = "",
        job_title: str = ""
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
        cover_letter_template: str = ""
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
                # 只要有一个成功就算整体成功
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

    def get_application_stats(self) -> Dict[str, Any]:
        """获取投递统计"""
        return self.auto_submitter.get_stats()

    def get_application_history(self, limit: int = 20) -> List[Dict[str, Any]]:
        """获取投递历史"""
        return self.auto_submitter.get_application_history(limit)

    def get_supported_platforms(self) -> List[str]:
        """获取支持的平台列表"""
        return self.auto_submitter.get_supported_platforms()

    async def chat(self, user_message: str) -> Dict[str, Any]:
        """
        自然语言对话 - 理解用户意图并执行相应操作

        Args:
            user_message: 用户的自然语言输入

        Returns:
            包含回复和执行结果的字典
        """
        from tools.llm import LLMMessage

        # 先做简单的关键词匹配，更可靠！
        lower_msg = user_message.lower()

        # 检查是否要分析匹配度
        match_keywords = ["匹配", "匹配度", "match", "分析匹配", "看看匹配"]
        if any(k in lower_msg for k in match_keywords):
            has_resume = "resume_data" in self.state
            has_jd = "jd_result" in self.state

            if has_resume and has_jd:
                # 已经有数据了，只是要显示分析
                return await self._chat_check_state()
            elif has_resume and not has_jd:
                return {
                    "status": "success",
                    "type": "chat",
                    "reply": "请先提供职位描述 (JD)，让我分析匹配度！"
                }
            elif has_jd and not has_resume:
                return {
                    "status": "success",
                    "type": "chat",
                    "reply": "请先提供您的简历，让我分析匹配度！"
                }
            else:
                return {
                    "status": "success",
                    "type": "chat",
                    "reply": "请先提供简历和职位描述！"
                }

        # 检查是否要查看状态
        state_keywords = ["状态", "state", "当前状态", "当前"]
        if any(k in lower_msg for k in state_keywords):
            return await self._chat_check_state()

        # 检查是否要解析简历（有文件路径或关键词）
        if any(ext in lower_msg for ext in [".pdf", ".docx", ".md", ".txt"]):
            return await self._chat_parse_resume(user_message, {})
        if any(k in lower_msg for k in ["解析简历", "parse resume", "读简历"]):
            return await self._chat_parse_resume(user_message, {})

        # 检查是否要分析 JD（长文本或有明确关键词）
        if len(user_message) > 100 and any(k in lower_msg for k in ["职位", "jd", "job", "要求", "职责"]):
            return await self._chat_analyze_jd(user_message, {"jd_text": user_message})
        if any(k in lower_msg for k in ["分析jd", "分析职位", "analyze jd"]):
            return await self._chat_analyze_jd(user_message, {})

        # 检查是否要运行完整工作流
        workflow_keywords = ["完整工作流", "优化简历", "生成简历", "cover letter", "求职信", "完整流程", "帮我申请", "run workflow"]
        if any(k in lower_msg for k in workflow_keywords):
            return await self._chat_run_workflow({})

        # 否则，用 LLM 理解意图
        state_summary = self._get_state_summary()

        prompt = f"""你是 Job Hunter Agent，一个专业的求职助手。

当前状态:
{state_summary}

可用工具:
1. parse_resume - 解析简历文件，需要参数: resume_file (文件路径) 或 resume_text (文本)
2. analyze_jd - 分析职位描述，需要参数: jd_text (文本) 或 jd_url (URL)
3. analyze_match - 分析简历与职位的匹配度（需要已解析简历和JD）
4. generate_optimization - 生成优化建议（需要已解析简历和JD）
5. generate_resume - 生成优化后简历（需要已解析简历）
6. generate_cover_letter - 生成求职信（需要已解析简历和JD）
7. submit_application - 投递职位
8. 无工具 - 只是聊天或回答问题

用户输入: "{user_message}"

请分析用户意图，以 JSON 格式返回:
{{
    "intent": "用户意图的简短描述",
    "action": "要执行的动作: chat|parse_resume|analyze_jd|run_workflow|check_state|other",
    "params": {{
        "resume_file": "如果要解析简历，这里填文件路径",
        "jd_text": "如果要分析JD，这里填JD文本",
        "jd_url": "如果要分析JD，这里填URL",
        "company_name": "如果是求职，这里填公司名"
    }},
    "needs_confirmation": false,
    "confirmation_question": "如果需要用户确认，这里填确认问题"
}}

只返回 JSON，不要其他内容！！！
"""

        try:
            # 调用 LLM 理解意图
            messages = [LLMMessage(role="user", content=prompt)]
            response = await self.llm_client.analyze(messages, max_tokens=1000)

            # 解析 LLM 的响应
            text = response.content.strip()
            if text.startswith("```json"):
                text = text[7:]
            if text.startswith("```"):
                text = text[3:]
            if text.endswith("```"):
                text = text[:-3]

            parsed = json.loads(text.strip())
            action = parsed.get("action", "chat")
            params = parsed.get("params", {})
            intent = parsed.get("intent", "")

            # 根据意图执行相应动作
            if action == "parse_resume":
                return await self._chat_parse_resume(user_message, params)
            elif action == "analyze_jd":
                return await self._chat_analyze_jd(user_message, params)
            elif action == "run_workflow":
                return await self._chat_run_workflow(params)
            elif action == "check_state":
                return await self._chat_check_state()
            else:
                return await self._chat_response(user_message, intent)

        except Exception as e:
            self.logger.error(f"解析意图失败: {e}")
            # LLM 解析失败时，给一个友好的回复
            return {
                "status": "success",
                "type": "chat",
                "reply": "我理解您的意思了！您可以：\n- 说 '解析简历: /path/to/resume.pdf' 来解析简历\n- 直接粘贴职位描述给我分析\n- 或者说 '查看状态' 看看当前进度"
            }

    def _get_state_summary(self) -> str:
        """获取状态摘要"""
        has_resume = "resume_data" in self.state
        has_jd = "jd_result" in self.state
        has_match = "match_result" in self.state

        summary = []
        if has_resume:
            summary.append("✅ 已解析简历")
        else:
            summary.append("❌ 未解析简历")

        if has_jd:
            summary.append("✅ 已分析JD")
        else:
            summary.append("❌ 未分析JD")

        if has_match:
            summary.append("✅ 已分析匹配度")

        return "\n".join(summary)

    async def _chat_parse_resume(self, user_message: str, params: dict) -> Dict[str, Any]:
        """对话：解析简历"""
        # 尝试从用户消息中提取文件路径
        import re
        file_match = re.search(r'([^\s]+\.(pdf|docx|md|txt))', user_message, re.I)

        resume_file = params.get("resume_file", "")
        if not resume_file and file_match:
            resume_file = file_match.group(1)

        if not resume_file:
            return {
                "status": "success",
                "type": "chat",
                "reply": "请告诉我简历文件的完整路径，例如：\n/Users/name/Desktop/resume.pdf"
            }

        if not os.path.exists(resume_file):
            return {
                "status": "success",
                "type": "chat",
                "reply": f"找不到文件: {resume_file}\n请确认路径是否正确。"
            }

        # 执行解析
        result = await self.execute({"resume_file": resume_file})

        if result.get("status") == "success":
            return {
                "status": "success",
                "type": "action",
                "action": "parse_resume",
                "result": result,
                "reply": "✅ 简历解析成功！我看到了您的工作经历、技能和教育背景。接下来您可以：\n- 提供 JD 让我分析职位匹配度\n- 或者直接让我生成优化建议！"
            }
        else:
            return {
                "status": "success",
                "type": "chat",
                "reply": f"简历解析失败: {result.get('error', '未知错误')}"
            }

    async def _chat_analyze_jd(self, user_message: str, params: dict) -> Dict[str, Any]:
        """对话：分析JD"""
        jd_text = params.get("jd_text", "")
        jd_url = params.get("jd_url", "")

        # 如果没提取到，检查用户输入是否是 URL 或 长文本
        if not jd_url and not jd_text:
            if "http" in user_message:
                jd_url = user_message.strip()
            elif len(user_message) > 50:
                jd_text = user_message

        if not jd_url and not jd_text:
            return {
                "status": "success",
                "type": "chat",
                "reply": "请把职位描述（JD）粘贴给我，或者提供职位链接！"
            }

        input_data = {}
        if jd_url:
            input_data["jd_url"] = jd_url
        else:
            input_data["jd_text"] = jd_text

        result = await self.execute(input_data)

        if result.get("status") == "success":
            reply = "✅ JD 分析完成！我提取了职位要求、技能需求和公司信息。"
            if "resume_data" in self.state:
                reply += "\n现在我可以分析您的简历与这个职位的匹配度！要继续吗？"
            else:
                reply += "\n接下来请提供您的简历，让我分析匹配度！"

            return {
                "status": "success",
                "type": "action",
                "action": "analyze_jd",
                "result": result,
                "reply": reply
            }
        else:
            return {
                "status": "success",
                "type": "chat",
                "reply": f"JD 分析失败: {result.get('error', '未知错误')}"
            }

    async def _chat_run_workflow(self, params: dict) -> Dict[str, Any]:
        """对话：运行完整工作流"""
        has_resume = "resume_data" in self.state
        has_jd = "jd_result" in self.state

        if not has_resume or not has_jd:
            missing = []
            if not has_resume:
                missing.append("简历")
            if not has_jd:
                missing.append("JD")
            return {
                "status": "success",
                "type": "chat",
                "reply": f"还需要提供：{' 和 '.join(missing)}\n请先让我解析简历和分析JD！"
            }

        company_name = params.get("company_name", "目标公司")

        result = await self.execute({"company_name": company_name})

        if result.get("status") == "success":
            return {
                "status": "success",
                "type": "action",
                "action": "run_workflow",
                "result": result,
                "reply": "✅ 工作流完成！我已经为您生成了：\n- 优化后的简历\n- 定制化的 Cover Letter\n- 匹配度分析报告\n您可以在 data/output/ 目录查看输出文件！"
            }
        else:
            return {
                "status": "success",
                "type": "chat",
                "reply": f"工作流执行失败: {result.get('error', '未知错误')}"
            }

    async def _chat_check_state(self) -> Dict[str, Any]:
        """对话：检查状态（给出详细分析）"""
        state = self.state
        reply_parts = []

        # 有匹配度分析结果时，给出详细分析
        if "match_result" in state and "jd_result" in state and "resume_data" in state:
            match_result = state.get("match_result", {})
            score = match_result.get("match_score", 0)

            reply_parts.append(f"📊 当前匹配度: {score}%")

            # 获取简历和JD的关键信息
            resume_data = state.get("resume_data", {})
            jd_result = state.get("jd_result", {})

            header = resume_data.get("header", {})
            name = header.get("name", "候选人")
            resume_skills = resume_data.get("skills", {}).get("technical", [])
            jd_keywords = jd_result.get("keywords", [])
            core_requirements = jd_result.get("core_requirements", [])

            if score >= 70:
                reply_parts.append(f"🎉 {name}，您的简历与这个职位匹配度很高！")
                if resume_skills and jd_keywords:
                    matched = [s for s in resume_skills if any(k.lower() in s.lower() for k in jd_keywords)]
                    if matched:
                        reply_parts.append(f"✅ 匹配技能: {', '.join(matched[:5])}")
            elif score >= 50:
                reply_parts.append(f"🤝 {name}，您的简历与这个职位基本匹配，还有优化空间。")
            else:
                reply_parts.append(f"💡 {name}，您的简历与这个职位匹配度较低，我可以帮您优化！")

            # 列出JD的核心要求
            if core_requirements:
                reply_parts.append("\n📋 职位核心要求:")
                for i, req in enumerate(core_requirements[:5], 1):
                    reply_parts.append(f"  {i}. {req}")

            # 建议下一步
            if score < 70:
                reply_parts.append("\n🚀 建议:")
                reply_parts.append("  - 让我为您生成优化建议")
                reply_parts.append("  - 或者直接让我帮您重写简历！")

        # 只有简历的情况
        elif "resume_data" in state and "jd_result" not in state:
            resume_data = state.get("resume_data", {})
            header = resume_data.get("header", {})
            name = header.get("name", "候选人")
            reply_parts.append(f"✅ {name}，您的简历已解析成功！")
            reply_parts.append("接下来请提供职位描述 (JD)，让我分析匹配度！")

        # 只有JD的情况
        elif "jd_result" in state and "resume_data" not in state:
            jd_result = state.get("jd_result", {})
            title = jd_result.get("title", "职位")
            company = jd_result.get("company", "公司")
            reply_parts.append(f"✅ {company} 的 {title} 职位已分析！")
            reply_parts.append("接下来请提供您的简历，让我分析匹配度！")

        # 没有数据的情况
        else:
            reply_parts.append("目前还没有处理任何数据。")
            reply_parts.append("您可以先让我解析简历或分析职位描述！")

        reply = "\n".join(reply_parts)

        return {
            "status": "success",
            "type": "state",
            "state": dict(state),
            "reply": reply
        }

    async def _chat_response(self, user_message: str, intent: str) -> Dict[str, Any]:
        """对话：纯回复"""
        from tools.llm import LLMMessage

        state_summary = self._get_state_summary()

        prompt = f"""你是 Job Hunter Agent，一个友好专业的求职助手。

当前状态:
{state_summary}

用户说: "{user_message}"
理解的意图: "{intent}"

请给出友好、专业的回复。回复要简短（2-4句话），有帮助性。如果用户需要提供更多信息，请具体说明需要什么。"""

        messages = [LLMMessage(role="user", content=prompt)]
        response = await self.llm_client.analyze(messages, max_tokens=500)

        return {
            "status": "success",
            "type": "chat",
            "reply": response.content.strip()
        }

