"""Coordinator match analysis helpers.

LLM 驱动的语义匹配 / 可迁移技能分析（_calculate_match / _generate_llm_match_analysis /
_generate_match_recommendations），原 coordinator.py 行 348-518。
需要 tools.llm.LLMMessage + self.llm_client.analyze，保持调用方式不变。
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

from loguru import logger

from tools.llm import LLMMessage


class CoordinatorMatchAnalysisMixin:
    """Match analysis helpers. Expects self.llm_client + self.logger."""

    async def _calculate_match(
        self,
        resume_data: Any,
        jd_result: Dict[str, Any],
    ) -> Dict[str, Any]:
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
            "missing_skills": llm_analysis.get("missing_skills", []),
        }

    async def _generate_llm_match_analysis(
        self,
        resume_data: Any,
        jd_result: Dict[str, Any],
    ) -> Dict[str, Any]:
        """使用 LLM 生成智能匹配度分析 - 重点关注可迁移技能"""
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

    def _generate_match_recommendations(
        self,
        resume_data: Any,
        jd_result: Dict[str, Any],
    ) -> List[str]:
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
