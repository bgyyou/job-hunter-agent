#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
知识库管理模块
- 多库创建与切换
- JD数据存储
- 自动入库
- JD自动分类
"""
import json
import uuid
from pathlib import Path
from typing import Dict, Any, List, Optional
from loguru import logger


class KnowledgeBase:
    """知识库管理类 — 可选接收 JobHunterDB 实例，优先写入 SQLite"""

    def __init__(
        self,
        base_dir: str = "data/knowledge_bases",
        sqlite_db: Optional[Any] = None,
    ):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.current_db: Optional[str] = None
        self.llm_client = None  # 稍后设置
        self.sqlite_db = sqlite_db  # 可选的统一数据库

        # 预设的岗位类型
        self.preset_roles = [
            "AI产品经理",
            "AI应用开发",
            "AI Agent开发",
            "AI Marketing"
        ]

        # 确保预设库存在
        for role in self.preset_roles:
            self._ensure_db_exists(role)

        logger.info(f"知识库初始化完成，基础目录: {self.base_dir}")

    def set_llm_client(self, llm_client):
        """设置LLM客户端用于自动分类"""
        self.llm_client = llm_client

    def _ensure_db_exists(self, db_name: str) -> Path:
        """确保数据库目录存在"""
        db_path = self.base_dir / db_name
        db_path.mkdir(parents=True, exist_ok=True)
        return db_path

    def list_databases(self) -> List[str]:
        """列出所有数据库"""
        db_list = []
        for item in self.base_dir.iterdir():
            if item.is_dir():
                db_list.append(item.name)
        return sorted(db_list)

    def create_database(self, db_name: str) -> bool:
        """创建新数据库"""
        db_path = self._ensure_db_exists(db_name)
        logger.info(f"创建数据库: {db_name}")
        return True

    def switch_database(self, db_name: str) -> bool:
        """切换当前数据库"""
        if db_name not in self.list_databases():
            self._ensure_db_exists(db_name)
        self.current_db = db_name
        logger.info(f"切换到数据库: {db_name}")
        return True

    def _get_db_path(self, db_name: Optional[str] = None) -> Path:
        """获取数据库路径"""
        if db_name is None:
            if self.current_db is None:
                raise ValueError("没有选择当前数据库，请先切换")
            db_name = self.current_db
        return self.base_dir / db_name

    def add_jd(self, jd_data: Dict[str, Any], db_name: Optional[str] = None) -> str:
        """
        添加JD到数据库。
        如果有 sqlite_db，优先写入 SQLite，同时保留 JSON 文件兼容旧系统。
        """
        # 优先写入 SQLite
        if self.sqlite_db:
            self.sqlite_db.insert_jd(jd_data)

        # 兼容旧系统：保存 JSON 文件
        db_path = self._get_db_path(db_name)

        # 生成唯一ID
        jd_id = f"jd_{uuid.uuid4().hex[:12]}"

        # 完整数据
        full_data = {
            "id": jd_id,
            "raw_text": jd_data.get("raw_text", ""),
            "parsed_data": jd_data.get("parsed_data", {}),
            "source": jd_data.get("source", "manual"),
            "created_at": jd_data.get("created_at", None),
        }

        # 保存为JSON文件
        file_path = db_path / f"{jd_id}.json"
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(full_data, f, ensure_ascii=False, indent=2)

        logger.info(f"添加JD: {jd_id} -> {db_path.name}")
        return jd_id

    def get_jd(self, jd_id: str, db_name: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """获取单个JD"""
        db_path = self._get_db_path(db_name)
        file_path = db_path / f"{jd_id}.json"
        if not file_path.exists():
            return None
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)

    def list_jds(self, db_name: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        """列出数据库中的JD"""
        db_path = self._get_db_path(db_name)
        jd_list = []

        for file_path in sorted(db_path.glob("jd_*.json"), reverse=True):
            with open(file_path, 'r', encoding='utf-8') as f:
                jd_data = json.load(f)
                jd_list.append(jd_data)
                if len(jd_list) >= limit:
                    break

        return jd_list

    def delete_jd(self, jd_id: str, db_name: Optional[str] = None) -> bool:
        """删除JD"""
        db_path = self._get_db_path(db_name)
        file_path = db_path / f"{jd_id}.json"
        if file_path.exists():
            file_path.unlink()
            logger.info(f"删除JD: {jd_id}")
            return True
        return False

    def clear_database(self, db_name: Optional[str] = None) -> int:
        """清空数据库，返回删除数量"""
        db_path = self._get_db_path(db_name)
        count = 0
        for file_path in db_path.glob("jd_*.json"):
            file_path.unlink()
            count += 1
        logger.info(f"清空数据库，删除 {count} 个JD")
        return count

    async def classify_jd(self, jd_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        使用LLM自动分类JD

        Returns:
            {
                "category": "AI产品经理",  # 分类结果
                "confidence": 0.95,        # 置信度
                "reasoning": "..."         # 分类理由
            }
        """
        if not self.llm_client:
            return {
                "category": "AI产品经理",  # 默认
                "confidence": 0.5,
                "reasoning": "未设置LLM客户端，使用默认分类"
            }

        from tools.llm import LLMMessage

        title = jd_data.get("title", "")
        requirements = jd_data.get("core_requirements", [])
        keywords = jd_data.get("keywords", [])

        prompt = f"""你是专业的招聘分类专家。请将以下职位分类到4个类别之一：

【候选类别】
1. AI产品经理 - 产品管理、需求分析、AI产品规划
2. AI应用开发 - 软件开发、编程、AI应用开发
3. AI Agent开发 - Agent开发、LLM应用、Prompt Engineering
4. AI Marketing - 市场营销、内容运营、社交媒体、品牌推广

【职位信息】
职位名称：{title}
核心要求：{'; '.join(requirements[:10])}
关键词：{', '.join(keywords[:15])}

请按以下JSON格式返回：
{{
    "category": "AI产品经理",
    "confidence": 0.9,
    "reasoning": "简要说明分类理由（50字以内）"
}}
只返回JSON，不要其他文字。"""

        try:
            messages = [LLMMessage(role="user", content=prompt)]
            response = await self.llm_client.analyze(messages=messages, max_tokens=300)

            # 解析JSON
            content = response.content.strip()
            json_start = content.find('{')
            json_end = content.rfind('}') + 1

            if json_start >= 0 and json_end > json_start:
                result = json.loads(content[json_start:json_end])
                category = result.get("category", "AI产品经理")

                # 确保是预设类别之一
                if category not in self.preset_roles:
                    category = "AI产品经理"

                return {
                    "category": category,
                    "confidence": result.get("confidence", 0.8),
                    "reasoning": result.get("reasoning", "")
                }

        except Exception as e:
            logger.error(f"JD分类失败: {e}")

        # 默认返回
        return {
            "category": "AI产品经理",
            "confidence": 0.5,
            "reasoning": "分类失败，使用默认"
        }

    def get_stats(self, db_name: Optional[str] = None) -> Dict[str, Any]:
        """获取数据库统计信息"""
        jds = self.list_jds(db_name, limit=1000)
        skills_count = {}
        companies = set()

        for jd in jds:
            parsed = jd.get("parsed_data", {})

            # 统计公司
            company = parsed.get("company", "")
            if company:
                companies.add(company)

            # 统计技能
            for skill in parsed.get("skills", []):
                skills_count[skill] = skills_count.get(skill, 0) + 1

        # 排序技能
        top_skills = sorted(skills_count.items(), key=lambda x: x[1], reverse=True)[:10]

        return {
            "total_jds": len(jds),
            "companies": list(companies),
            "top_skills": top_skills
        }
