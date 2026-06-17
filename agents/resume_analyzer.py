# agents/resume_analyzer.py
"""
简历分析 Agent - 真正的 Agent 实现

具备能力：
1. 规划能力 - 动态规划分析策略
2. 工具调用 - 选择解析器、LLM
3. 记忆能力 - 记住之前分析过的简历
4. 错误恢复 - 解析失败时尝试多种方式
5. 反思能力 - 评估画像完整性
6. 成本意识 - 缓存相似简历
"""
from typing import Dict, Any, Optional, Tuple
from pathlib import Path
import json

from agents.base import BaseAgent, Tool, AgentPlan
from tools.llm import LLMClient, LLMMessage
from tools.parser import DocumentParserFactory
from models.resume import ResumeProfile
from loguru import logger


class ResumeAnalyzer(BaseAgent):
    """
    简历分析 Agent - 真正的 Agent 实现

    功能：
    1. 调用 Parser 解析简历
    2. 调用 LLM 提取画像
    3. 输出 reasoning（决策透明）
    4. 动态选择最佳解析策略
    5. 错误恢复
    """

    def __init__(self, llm_client: LLMClient):
        """
        初始化简历分析 Agent

        Args:
            llm_client: LLM 客户端
        """
        super().__init__("resume_analyzer")
        self.llm_client = llm_client
        self.parser_factory = DocumentParserFactory

        # ==================== 简历解析 Prompt ====================
        self.system_prompt = """你是一个专业的简历解析专家。你的任务是准确提取简历中的结构化信息。

严格遵循以下规则：
1. 只提取简历中明确出现的信息，不要推测或编造
2. 硬技能 = 编程语言、框架、工具、技术（如 Python、React、Docker）
3. 软技能 = 沟通能力、领导力、团队协作等（单独放入 soft_skills 字段）
4. 如果某项信息不存在，返回 null 或空列表，不要填默认值
5. experience_years 必须基于简历中的工作经历时间段计算
6. 保持原文语言，不要翻译
7. 只返回 JSON，不要有任何其他文字"""

        self.extraction_prompt = """请从以下简历文本中提取结构化信息。

简历内容：
--------
{resume_text}
--------"""

        self.output_schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string", "nullable": True},
                "phone": {"type": "string", "nullable": True},
                "email": {"type": "string", "nullable": True},
                "skills": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "硬技能列表（编程语言、框架、工具、技术）"
                },
                "soft_skills": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "软技能列表（沟通、领导力和团队协作等）"
                },
                "experience_years": {"type": "integer", "minimum": 0, "nullable": True},
                "domains": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "技术领域（如 Web开发、数据处理、AI/ML）"
                },
                "target_roles": {"type": "array", "items": {"type": "string"}},
                "preferred_locations": {"type": "array", "items": {"type": "string"}},
                "education": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "school": {"type": "string"},
                            "degree": {"type": "string"},
                            "major": {"type": "string"},
                            "start_year": {"type": "integer"},
                            "end_year": {"type": "integer"}
                        }
                    }
                },
                "projects": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "description": {"type": "string"},
                            "role": {"type": "string"},
                            "tech_stack": {"type": "array", "items": {"type": "string"}},
                            "start_date": {"type": "string"},
                            "end_date": {"type": "string"}
                        }
                    }
                }
            }
        }

    # ==================== 规划能力 ====================

    async def plan(self, goal: str, input_data: Dict[str, Any]) -> AgentPlan:
        """
        规划分析策略 - 规划能力

        根据输入类型动态规划最佳策略
        """
        plan = AgentPlan(goal)

        has_file = "resume_file" in input_data
        has_text = "resume_text" in input_data

        if has_file:
            file_path = input_data["resume_file"]
            suffix = Path(file_path).suffix.lower()

            # 根据文件类型规划
            if suffix == '.pdf':
                plan.add_step(
                    "parse_pdf", "parse_file",
                    {"file_path": file_path, "format": "pdf"},
                    "解析 PDF 文件"
                )
            elif suffix in ['.docx', '.doc']:
                plan.add_step(
                    "parse_word", "parse_file",
                    {"file_path": file_path, "format": "word"},
                    "解析 Word 文件"
                )
            else:
                plan.add_step(
                    "parse_text", "parse_file",
                    {"file_path": file_path, "format": "text"},
                    "解析文本文件"
                )
        elif has_text:
            plan.add_step(
                "use_text", "use_text",
                {"text": input_data["resume_text"]},
                "使用提供的文本"
            )
        else:
            # 降级策略：从记忆中查找
            plan.add_step(
                "search_memory", "search_memory",
                {"query": str(input_data)},
                "从记忆中搜索"
            )

        # 后续步骤
        plan.add_step(
            "extract_profile", "extract_profile",
            {},
            "提取简历画像",
            depends_on=[0]  # 依赖第一步
        )

        plan.add_step(
            "validate_profile", "validate_profile",
            {},
            "验证画像完整性",
            depends_on=[1]
        )

        return plan

    def _get_goal(self, input_data: Dict[str, Any]) -> str:
        """获取目标"""
        if "resume_file" in input_data:
            return f"解析文件 {input_data['resume_file']} 并提取画像"
        elif "resume_text" in input_data:
            return "从文本中提取简历画像"
        return "提取简历画像"

    # ==================== 工具注册 ====================

    def _register_default_tools(self):
        """注册工具"""
        self.register_tool(
            "parse_file",
            "解析简历文件（PDF/Word/TXT）",
            self._tool_parse_file
        )
        self.register_tool(
            "use_text",
            "直接使用提供的文本",
            self._tool_use_text
        )
        self.register_tool(
            "extract_profile",
            "使用 LLM 提取简历画像",
            self._tool_extract_profile
        )
        self.register_tool(
            "validate_profile",
            "验证画像完整性",
            self._tool_validate_profile
        )

    async def _tool_parse_file(self, file_path: str, format: str) -> str:
        """工具：解析文件"""
        span = self.start_span(f"parse_{format}")

        try:
            text = DocumentParserFactory.parse(file_path)

            if not text or len(text) < 50:
                raise ValueError(f"解析出的内容过少: {len(text)} 字符")

            self.logger.info(f"{format} 解析成功，文本长度: {len(text)}")

            # 存储到状态
            self.state["parsed_text"] = text
            self.state["file_format"] = format

            if span:
                self.end_span(True)

            return text

        except Exception as e:
            self.logger.error(f"{format} 解析失败: {e}")
            if span:
                self.end_span(False, str(e))
            raise

    async def _tool_use_text(self, text: str) -> str:
        """工具：使用文本"""
        if not text or not text.strip():
            raise ValueError("简历文本为空")

        self.state["parsed_text"] = text.strip()
        return text.strip()

    async def _tool_extract_profile(self, resume_text: str) -> Dict[str, Any]:
        """工具：提取画像"""
        span = self.start_span("llm_extract")

        try:
            # 检查缓存
            cache_key = f"profile_{hash(resume_text[:1000])}"
            if cache_key in self.state.get("cache", {}):
                self.logger.info("使用缓存画像")
                return self.state["cache"][cache_key]

            # 准备 Prompt
            prompt = self.extraction_prompt.format(
                resume_text=resume_text[:10000]  # 限制长度
            )
            messages = [
                LLMMessage(role="system", content=self.system_prompt),
                LLMMessage(role="user", content=prompt)
            ]

            # 调用 LLM
            result = await self.llm_client.analyze_with_structured_output(
                messages=messages,
                output_schema=self.output_schema,
                temperature=0.0
            )

            # 记录 Token 使用
            tokens = self.llm_client.estimate_tokens(prompt + str(result))
            self.record_llm_call(tokens)

            # 缓存结果
            if "cache" not in self.state:
                self.state["cache"] = {}
            self.state["cache"][cache_key] = result

            self.state["extracted_profile"] = result

            if span:
                self.end_span(True)

            return result

        except Exception as e:
            self.logger.error(f"LLM 提取失败: {e}")
            if span:
                self.end_span(False, str(e))
            raise

    async def _tool_validate_profile(self, profile: Dict[str, Any]) -> Tuple[bool, str]:
        """工具：验证画像完整性 - 反思能力"""
        issues = []

        # 检查关键字段
        if not profile.get("name") or profile["name"] == "未知":
            issues.append("姓名缺失")

        if not profile.get("email"):
            issues.append("邮箱缺失")

        if not profile.get("skills") or len(profile.get("skills", [])) == 0:
            issues.append("技能列表为空")

        if profile.get("experience_years", 0) < 0:
            issues.append("工作年限异常")

        # 计算完整度
        total_fields = 10  # 主要字段数量
        missing_fields = len(issues)
        completeness = (total_fields - missing_fields) / total_fields

        self.logger.info(f"画像完整性: {completeness:.1%}")

        if completeness < 0.7:
            return False, f"画像不完整: {', '.join(issues)}"

        return True, "画像完整"

    # ==================== 反思能力 ====================

    async def _evaluate_step_result(self, step: Dict, result: Any) -> float:
        """评估步骤结果质量 - 反思能力"""
        if step["name"] == "extract_profile":
            # 检查画像质量
            profile = result if isinstance(result, dict) else {}
            completeness = 0

            if profile.get("name"):
                completeness += 0.2
            if profile.get("email"):
                completeness += 0.15
            if profile.get("skills") and len(profile.get("skills", [])) > 3:
                completeness += 0.25
            if profile.get("experience_years", 0) > 0:
                completeness += 0.2
            if profile.get("projects") and len(profile.get("projects", [])) > 0:
                completeness += 0.2

            return min(completeness, 1.0)

        elif step["name"] == "validate_profile":
            is_valid, _ = result
            return 1.0 if is_valid else 0.5

        return 1.0

    async def _correct_result(self, step: Dict, result: Any, quality: float) -> Any:
        """修正结果 - 反思能力"""
        if step["name"] == "extract_profile" and quality < 0.7:
            self.logger.warning("画像质量偏低，尝试补充")

            # 补充默认值
            if isinstance(result, dict):
                result.setdefault("name", "未知")
                result.setdefault("phone", "")
                result.setdefault("email", "")
                result.setdefault("skills", [])
                result.setdefault("experience_years", 0)
                result.setdefault("domains", [])
                result.setdefault("target_roles", [])
                result.setdefault("preferred_locations", [])
                result.setdefault("education", [])
                result.setdefault("projects", [])

            return result

        return result

    # ==================== 错误恢复 ====================

    async def _recover_from_failure(self, step: Dict, error: Exception,
                                     results: Dict) -> Optional[Any]:
        """从失败中恢复 - 错误恢复"""
        step_name = step["name"]

        if step_name in ["parse_pdf", "parse_word", "parse_text"]:
            # 解析失败，尝试其他解析方式
            self.logger.info("尝试备用解析方式")

            try:
                # 尝试读取为纯文本
                with open(step["params"]["file_path"], "r", encoding="utf-8", errors="ignore") as f:
                    text = f.read()

                if len(text) > 50:
                    self.logger.info("纯文本解析成功")
                    self.state["parsed_text"] = text
                    return text
            except:
                pass

            # 最后降级：返回提示
            return f"解析失败: {error}"

        elif step_name == "extract_profile":
            # LLM 提取失败，使用规则提取
            self.logger.info("降级为规则提取")

            text = self.state.get("parsed_text", "")

            # 简单规则提取
            import re

            # 提取邮箱
            email = re.search(r'[\w\.-]+@[\w\.-]+', text)
            # 提取电话
            phone = re.search(r'1[3-9]\d{9}', text)

            return {
                "name": "未知",
                "email": email.group() if email else "",
                "phone": phone.group() if phone else "",
                "skills": [],
                "experience_years": 0,
                "domains": [],
                "target_roles": [],
                "preferred_locations": [],
                "education": [],
                "projects": []
            }

        return None

    # ==================== 核心执行 ====================

    async def execute(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行简历分析

        Args:
            input_data: 输入数据，应包含：
                - resume_file: 简历文件路径
                - 或者 resume_text: 简历文本（直接提供）

        Returns:
            分析结果，包含：
                - status: 执行状态 (success/error)
                - profile: 简历画像
                - reasoning: 决策理由
                - confidence: 置信度 (0-100)
        """
        self.log_action("start_resume_analysis", input_data)

        # 获取简历内容
        try:
            if "resume_text" in input_data:
                resume_text = await self._tool_use_text(input_data["resume_text"])
            elif "resume_file" in input_data:
                resume_text = await self._tool_parse_file(input_data["resume_file"], "auto")
            else:
                raise ValueError("必须提供 resume_file 或 resume_text")
        except Exception as e:
            self.logger.error(f"获取简历内容失败: {e}")
            return {
                "status": "error",
                "error": str(e),
                "agent": self.name
            }

        # 提取画像
        try:
            profile_data = await self._tool_extract_profile(resume_text)
        except Exception as e:
            self.logger.error(f"提取画像失败: {e}")
            profile_data = self._get_default_profile()

        # 验证画像
        is_valid, validation_msg = await self._tool_validate_profile(profile_data)

        # 构建结果
        try:
            profile = ResumeProfile(**profile_data)
            profile_dict = profile.model_dump()
        except Exception as e:
            self.logger.error(f"构建 ResumeProfile 失败: {e}")
            profile_dict = profile_data

        # 生成决策理由
        self.set_reasoning(self._generate_reasoning(profile_dict, resume_text))

        # 计算置信度
        confidence = self._calculate_confidence(profile_dict, resume_text)

        # 保存状态
        self.state["last_analyzed"] = {
            "resume_text_length": len(resume_text),
            "profile": profile_dict,
            "confidence": confidence,
            "validation": validation_msg
        }
        self.save_state()

        self.log_action("analysis_complete", {"confidence": confidence})

        return {
            "status": "success",
            "profile": profile_dict,
            "reasoning": self.reasoning,
            "confidence": confidence,
            "validation": validation_msg
        }

    def _generate_reasoning(self, profile: Dict[str, Any], resume_text: str) -> str:
        """生成决策理由"""
        reasoning_parts = []

        # 基本信息
        reasoning_parts.append(f"【基本信息】姓名: {profile.get('name', '未知')}")
        reasoning_parts.append(f"【联系方式】电话: {profile.get('phone', '未知')}, 邮箱: {profile.get('email', '未知')}")

        # 技能分析
        skills = profile.get("skills", [])
        if skills:
            reasoning_parts.append(f"【技能分析】共识别 {len(skills)} 项技能: {', '.join(skills[:10])}{'...' if len(skills) > 10 else ''}")
        else:
            reasoning_parts.append("【技能分析】未识别到明确的技能列表")

        # 经验分析
        exp_years = profile.get("experience_years", 0)
        reasoning_parts.append(f"【经验分析】工作年限: {exp_years} 年")

        # 技术领域
        domains = profile.get("domains", [])
        if domains:
            reasoning_parts.append(f"【技术领域】{', '.join(domains)}")

        # 教育背景
        education = profile.get("education", [])
        if education:
            reasoning_parts.append(f"【教育背景】共 {len(education)} 条教育记录")
            for edu in education[:2]:
                school = edu.get("school", "")
                degree = edu.get("degree", "")
                major = edu.get("major", "")
                year = f"({edu.get('start_year', '')}-{edu.get('end_year', '')})"
                reasoning_parts.append(f"  - {school}: {degree} {major} {year}")

        # 项目经验
        projects = profile.get("projects", [])
        if projects:
            reasoning_parts.append(f"【项目经验】共 {len(projects)} 个项目")

        # 求职意向
        target_roles = profile.get("target_roles", [])
        if target_roles:
            reasoning_parts.append(f"【求职意向】目标岗位: {', '.join(target_roles)}")

        return "\n".join(reasoning_parts)

    def _calculate_confidence(self, profile: Dict[str, Any], resume_text: str) -> int:
        """计算提取结果的置信度"""
        score = 0

        # 检查关键字段
        if profile.get("name") and profile["name"] != "未知":
            score += 15
        if profile.get("phone"):
            score += 15
        if profile.get("email"):
            score += 10
        if profile.get("skills") and len(profile.get("skills", [])) > 0:
            score += 20
        if profile.get("experience_years", 0) > 0:
            score += 10
        if profile.get("education") and len(profile.get("education", [])) > 0:
            score += 15
        if profile.get("projects") and len(profile.get("projects", [])) > 0:
            score += 15

        return min(score, 100)

    def _get_default_profile(self) -> Dict[str, Any]:
        """获取默认画像（用于错误恢复）"""
        return {
            "name": "未知",
            "phone": "",
            "email": "",
            "skills": [],
            "experience_years": 0,
            "domains": [],
            "target_roles": [],
            "preferred_locations": [],
            "education": [],
            "projects": []
        }

    def validate_input(self, input_data: Dict[str, Any]) -> bool:
        """验证输入"""
        if not super().validate_input(input_data):
            return False

        has_file = "resume_file" in input_data
        has_text = "resume_text" in input_data

        if not has_file and not has_text:
            self.logger.error("输入必须包含 resume_file 或 resume_text")
            return False

        # 检查文件类型
        if has_file:
            file_path = input_data["resume_file"]
            suffix = Path(file_path).suffix.lower()
            if suffix not in ['.pdf', '.docx', '.doc', '.txt', '.md']:
                self.logger.error(f"不支持的文件类型: {suffix}")
                return False

        return True