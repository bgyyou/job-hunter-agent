"""v3 M-rebuild-1: JD 解析器统一接口

三种输入（text/image/rag）归一成同一份 StructuredJD：

- TextJDParser:    粘贴文本 + 关键词 + LLM 抽结构（LLM 失败降级到关键词）
- ImageJDParser:   PaddleOCR + LLM 抽结构（强制 needs_user_review=True）
- RAGJDRetriever:  从 rag_industry_function 库调真实 JD 样本（数据待补充）
- JDParserRouter:  按 source 路由

设计原则：
- 所有 parser 返回 StructuredJD（jd_id=None，待用户确认后入库）
- ImageJDParser 强制 needs_user_review=True（OCR 不可信，必须用户校对）
- LLM 失败时降级到关键词 + 行号定位（兜底）
"""

from __future__ import annotations

import io
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Protocol

from loguru import logger


# 工具: PaddleOCR 延迟导入（可选依赖）
def _try_paddleocr():
    try:
        from paddleocr import PaddleOCR  # type: ignore
        return PaddleOCR
    except ImportError:
        return None


# 工具: LLMClient 延迟导入（避免循环依赖）
def _try_llm_types():
    try:
        from tools.llm import LLMClient, LLMMessage  # type: ignore
        return LLMClient, LLMMessage
    except ImportError:
        return None, None


@dataclass
class StructuredJD:
    """JD 结构化表示（v3 统一接口）。

    字段对齐 update_plan.md §2.1 + §2.2（jd_structured 表）：
    source 必填，其余可选；responsibilities/requirements 始终为 list。
    needs_user_review 为 True 时表示数据不可信，前端必须给校对界面。
    parse_notes 记录降级 / OCR 警告等诊断信息。
    """

    jd_id: Optional[int] = None
    user_id: str = "default"
    source: Literal["text", "image", "rag"] = "text"
    raw_text: str = ""
    company: Optional[str] = None
    title: Optional[str] = None
    industry: Optional[str] = None
    function: Optional[str] = None
    level: Optional[str] = None
    responsibilities: List[str] = field(default_factory=list)
    requirements: List[str] = field(default_factory=list)
    needs_user_review: bool = False
    parse_notes: List[str] = field(default_factory=list)

    def to_db_dict(self) -> Dict[str, Any]:
        """Convert to dict suitable for BaseBackend.insert_jd_structured."""
        return {
            "user_id": self.user_id,
            "source": self.source,
            "raw_text": self.raw_text,
            "company": self.company,
            "title": self.title,
            "industry": self.industry,
            "function": self.function,
            "level": self.level,
            "responsibilities": self.responsibilities,
            "requirements": self.requirements,
        }


# 关键词兜底策略（LLM 不可用时用）
_COMPANY_PATTERNS = [
    r"([一-鿿]{2,30}(?:有限公司|公司|集团|科技|网络|信息|有限|股份))",
    r"([A-Z][a-zA-Z\s&.,]{2,40}(?:Inc\.|LLC|Ltd\.|Co\.|Corp\.|GmbH))",
]
_TITLE_PATTERNS = [
    r"招聘[：: ]?\s*([一-鿿\w\s]{2,30})",
    r"岗位[：: ]?\s*([一-鿿\w\s]{2,30})",
    r"职位[：: ]?\s*([一-鿿\w\s]{2,30})",
    r"((?:Senior|Junior|Lead|Principal|Staff)\s+[\w\s]{2,30})",
]


class BaseJDParser(Protocol):
    """JD 解析器统一接口（Protocol）。"""

    def parse(self, input: Any) -> "StructuredJD": ...


class TextJDParser:
    """粘贴文本 JD 解析：关键词 + LLM 抽结构（LLM 失败降级到关键词）。"""

    def __init__(self, llm_client: Optional[Any] = None):
        self.llm_client = llm_client

    async def parse(self, text: str) -> StructuredJD:
        if not text or not text.strip():
            return StructuredJD(raw_text=text or "", parse_notes=["空文本"])

        if self.llm_client is not None:
            try:
                return await self._parse_with_llm(text)
            except Exception as exc:
                logger.warning(f"[TextJDParser] LLM 解析失败，降级到关键词: {exc}")
                return self._parse_with_keywords(text, notes=[f"LLM 失败: {exc}"])

        return self._parse_with_keywords(text)

    async def _parse_with_llm(self, text: str) -> StructuredJD:
        _, LLMMessage = _try_llm_types()
        if LLMMessage is None:
            raise RuntimeError("LLMMessage 不可用（tools.llm 未加载）")

        schema = {
            "company": "公司名（如 '字节跳动'/'Tencent'，无则 null）",
            "title": "岗位名（如 'AI 产品经理'，无则 null）",
            "industry": "行业（如 '互联网'/'金融'，无则 null）",
            "function": "职能（如 '产品'/'研发'/'市场'，无则 null）",
            "level": "级别（junior / mid / senior，无则 null）",
            "responsibilities": ["职责 1", "职责 2"],
            "requirements": ["要求 1", "要求 2"],
        }
        prompt = (
            "你是 JD 结构化助手。下面是一份粘贴的 JD 文本（可能格式不规整）。\n"
            "请把内容完整抽取为结构化 JSON。要求：\n"
            "1. company/title/industry/function/level 找不到填 null，不要瞎编\n"
            "2. responsibilities 列出所有职责（不要遗漏）；requirements 列出所有要求\n"
            "3. 中英文混排时按原文保留\n\n"
            f"JD 文本：\n===\n{text}\n===\n"
        )
        messages = [LLMMessage(role="user", content=prompt)]
        result = await self.llm_client.analyze_with_structured_output(
            messages=messages,
            output_schema=schema,
            max_tokens=4000,
            temperature=0.1,
        )
        return StructuredJD(
            source="text",
            raw_text=text,
            company=result.get("company"),
            title=result.get("title"),
            industry=result.get("industry"),
            function=result.get("function"),
            level=result.get("level"),
            responsibilities=result.get("responsibilities") or [],
            requirements=result.get("requirements") or [],
        )

    def _parse_with_keywords(
        self, text: str, notes: Optional[List[str]] = None
    ) -> StructuredJD:
        company: Optional[str] = None
        for pat in _COMPANY_PATTERNS:
            m = re.search(pat, text)
            if m:
                company = m.group(1).strip()
                break

        title: Optional[str] = None
        for pat in _TITLE_PATTERNS:
            m = re.search(pat, text)
            if m:
                # 第 1 个捕获组是岗位名；fallback 到整段
                raw_title = (m.group(1) or m.group(0)).strip()
                # 截到第一个换行/段头关键词，避免贪婪匹配吞掉后续内容
                title = re.split(r"[\n\r]|(?<=\S)\s+(?:职责|要求|responsibilit|requirement)", raw_title, maxsplit=1)[0].strip()
                break

        responsibilities: List[str] = []
        requirements: List[str] = []
        in_resp = False
        in_req = False
        for line in text.split("\n"):
            line = line.strip()
            if not line:
                continue
            lower = line.lower()
            if "职责" in line or "responsibilit" in lower or "工作内容" in line or "你要做" in line:
                in_resp, in_req = True, False
                continue
            if "要求" in line or "requirement" in lower or "任职" in line or "你需要" in line or "qualification" in lower:
                in_resp, in_req = False, True
                continue
            # bullet 行（•·-、数字.）
            if re.match(r"^[•·\-]\s*", line) or re.match(r"^\d+[.、)]\s*", line):
                item = re.sub(r"^[•·\-]\s*|^\d+[.、)]\s*", "", line).strip()
                if not item:
                    continue
                if in_req:
                    requirements.append(item)
                elif in_resp:
                    responsibilities.append(item)
                else:
                    responsibilities.append(item)
            elif line.startswith(("【职责", "【要求")):
                # 段头标记，跳过
                continue

        return StructuredJD(
            source="text",
            raw_text=text,
            company=company,
            title=title,
            responsibilities=responsibilities,
            requirements=requirements,
            parse_notes=notes or ["关键词降级解析（无 LLM 客户端）"],
        )


class ImageJDParser:
    """图片 JD 解析：PaddleOCR + LLM 抽结构（强制 needs_user_review=True）。"""

    def __init__(self, llm_client: Optional[Any] = None):
        self.llm_client = llm_client
        self.text_parser = TextJDParser(llm_client=llm_client)
        self._ocr_engine: Optional[Any] = None  # 懒加载 PaddleOCR 实例

    def _get_ocr_engine(self):
        """懒加载 PaddleOCR（首次调用时初始化）。"""
        if self._ocr_engine is not None:
            return self._ocr_engine
        PaddleOCR = _try_paddleocr()
        if PaddleOCR is None:
            raise RuntimeError(
                "PaddleOCR 未安装。请运行 `pip install paddleocr>=2.7.0 paddlepaddle`。"
            )
        self._ocr_engine = PaddleOCR(use_angle_cls=True, lang="ch", show_log=False)
        return self._ocr_engine

    def _ocr(self, image_path: str) -> str:
        """对图片文件做 OCR，返回原始文本。"""
        path = Path(image_path)
        if not path.exists():
            raise FileNotFoundError(f"图片不存在: {image_path}")
        engine = self._get_ocr_engine()
        result = engine.ocr(str(path), cls=True)
        lines: List[str] = []
        if not result or not result[0]:
            return ""
        # result[0]: [[bbox, (text, confidence)], ...]
        for line_items in result[0]:
            for item in line_items:
                if isinstance(item, (list, tuple)) and len(item) >= 2:
                    text = item[1][0] if isinstance(item[1], (list, tuple)) else item[1]
                    if text:
                        lines.append(text)
        return "\n".join(lines)

    async def parse(self, image_path: str) -> StructuredJD:
        """解析图片 JD，返回 StructuredJD（needs_user_review=True）。"""
        try:
            raw_text = self._ocr(image_path)
        except Exception as exc:
            logger.warning(f"[ImageJDParser] OCR 失败: {exc}")
            return StructuredJD(
                source="image",
                raw_text="",
                needs_user_review=True,
                parse_notes=[f"OCR 失败: {exc}"],
            )

        if not raw_text or not raw_text.strip():
            return StructuredJD(
                source="image",
                raw_text="",
                needs_user_review=True,
                parse_notes=["OCR 输出空文本"],
            )

        jd = await self.text_parser.parse(raw_text)
        jd.source = "image"
        jd.needs_user_review = True  # OCR 不可信，强制用户校对
        jd.parse_notes.append("OCR 文本需用户校对")
        return jd


class RAGJDRetriever:
    """RAG 库检索：从 rag_industry_function 调真实 JD 样本（数据待补充）。"""

    def __init__(self, db: Optional[Any] = None):
        self.db = db

    async def parse(self, query: Dict[str, str]) -> StructuredJD:
        """按 (industry, function, level) 调 RAG 库。

        query: ``{"industry": "...", "function": "...", "level": "..."}``
        """
        industry = query.get("industry", "")
        function = query.get("function", "")
        level = query.get("level")

        if not industry or not function:
            return StructuredJD(
                source="rag",
                parse_notes=["RAG 检索缺 industry/function 参数"],
            )
        if self.db is None:
            return StructuredJD(
                source="rag",
                industry=industry,
                function=function,
                level=level,
                parse_notes=["RAG 数据库未配置（db=None）"],
            )

        rows = self.db.list_rag_by_industry_function(
            industry, function, level=level, limit=5
        )
        if not rows:
            return StructuredJD(
                source="rag",
                industry=industry,
                function=function,
                level=level,
                parse_notes=[
                    f"RAG 库暂无 ({industry}/{function}/{level}) 数据"
                    "（数据渠道待定，见 update_plan.md §5.3）"
                ],
            )

        first = rows[0]
        samples = first.get("sample_jds") or []
        if not samples:
            return StructuredJD(
                source="rag",
                industry=industry,
                function=function,
                level=level,
                parse_notes=[
                    f"RAG 库 ({industry}/{function}/{level}) 无 sample_jds 数据"
                ],
            )
        sample = samples[0]
        return StructuredJD(
            source="rag",
            raw_text=json.dumps(sample, ensure_ascii=False),
            company=sample.get("company"),
            title=sample.get("title"),
            industry=industry,
            function=function,
            level=level,
            responsibilities=sample.get("responsibilities", []),
            requirements=sample.get("requirements", []),
            parse_notes=[f"RAG 库查到 {len(rows)} 条候选，取第一条作为基础"],
        )


class JDParserRouter:
    """JD 解析路由：按 source 选 parser。"""

    def __init__(
        self,
        llm_client: Optional[Any] = None,
        db: Optional[Any] = None,
    ):
        self.text_parser = TextJDParser(llm_client=llm_client)
        self.image_parser = ImageJDParser(llm_client=llm_client)
        self.rag_retriever = RAGJDRetriever(db=db)

    async def parse(self, source: str, input: Any) -> StructuredJD:
        if source == "text":
            return await self.text_parser.parse(input)
        if source == "image":
            return await self.image_parser.parse(input)
        if source == "rag":
            return await self.rag_retriever.parse(input)
        raise ValueError(f"Unknown JD source: {source!r}（应为 text/image/rag）")