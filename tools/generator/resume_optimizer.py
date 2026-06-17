# tools/generator/resume_optimizer.py
"""
简历优化器 - 根据JD和优化建议来优化简历内容
"""
from typing import Dict, Any, List, Optional
from loguru import logger
import json


class ResumeOptimizer:
    """简历优化器"""

    def __init__(self, llm_client):
        """
        初始化简历优化器

        Args:
            llm_client: LLM客户端
        """
        self.llm_client = llm_client
        self.logger = logger.bind(component="resume_optimizer")

    async def optimize(
        self,
        resume_data: Dict[str, Any],
        jd_result: Dict[str, Any],
        recommendations: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        根据建议优化简历

        Args:
            resume_data: 原始简历数据
            jd_result: JD分析结果
            recommendations: 优化建议列表

        Returns:
            优化后的简历数据
        """
        self.logger.info("开始优化简历")

        # 首先，让LLM根据建议完整优化整个简历
        optimized_data = await self._optimize_with_llm(
            resume_data, jd_result, recommendations
        )

        return optimized_data

    async def _optimize_with_llm(
        self,
        resume_data: Dict[str, Any],
        jd_result: Dict[str, Any],
        recommendations: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        使用LLM优化简历

        Args:
            resume_data: 原始简历数据
            jd_result: JD分析结果
            recommendations: 优化建议列表

        Returns:
            优化后的简历数据
        """
        from tools.llm import LLMMessage

        # 把建议转成文本
        rec_texts = []
        for rec in recommendations:
            rec_type = rec.get('type', 'modify')
            if rec_type == 'modify':
                rec_texts.append(f"- [修改] {rec.get('section', '')}: {rec.get('reason', '')}")
            elif rec_type == 'delete':
                rec_texts.append(f"- [删除] {rec.get('section', '')}: {rec.get('reason', '')}")
            elif rec_type == 'suggest_add':
                rec_texts.append(f"- [补充] {rec.get('section', '')}: {rec.get('reason', '')}")

        recommendations_text = "\n".join(rec_texts) if rec_texts else "无特殊建议"

        # 使用 string.format() 避免 f-string 解析复杂表达式时的问题
        system_prompt = """你是资深简历优化专家。你的任务是根据目标职位的要求和具体的优化建议，重写简历的核心内容。

严格遵循以下原则：
1. **真实性**：只调整表达方式和措辞，不编造简历中不存在的经历、技能或数据
2. **针对性**：所有修改必须与目标职位直接相关
3. **具体性**：给出完整的改写文本，不要空泛建议
4. **格式**：返回完整的 JSON 简历对象，保持与原始简历相同的结构

如果你发现简历中有与目标职位无关的内容，可以弱化或删除，但不要添加新的经历。"""

        prompt = """请根据以下信息优化简历。

【目标职位】
- 职位：{title}
- 公司：{company}
- 核心要求：
{core_requirements}
- 关键词：{keywords}

【优化建议】
{recommendations}

【原始简历】
{resume_json}

请返回优化后的完整简历 JSON，保持与原始简历相同的结构。只返回 JSON，不要有其他文字。""".format(
            title=jd_result.get('title', ''),
            company=jd_result.get('company', ''),
            core_requirements='\n'.join(f'- {r}' for r in jd_result.get('core_requirements', [])),
            keywords=', '.join(jd_result.get('keywords', [])),
            recommendations=recommendations_text,
            resume_json=json.dumps(resume_data, ensure_ascii=False, indent=2)
        )

        try:
            messages = [
                LLMMessage(role="system", content=system_prompt),
                LLMMessage(role="user", content=prompt)
            ]
            response = await self.llm_client.analyze(
                messages=messages, max_tokens=4096, temperature=0.3
            )
            llm_text = response.content.strip()

            # 提取JSON
            json_start = llm_text.find('{')
            json_end = llm_text.rfind('}') + 1

            if json_start >= 0 and json_end > json_start:
                json_str = llm_text[json_start:json_end]
                optimized_data = json.loads(json_str)
                self.logger.info("简历优化成功")
                return optimized_data

            # 如果提取失败，返回原始数据
            self.logger.warning("无法解析LLM返回的JSON，返回原始简历")
            return resume_data

        except Exception as e:
            self.logger.error(f"简历优化失败: {e}")
            return resume_data
