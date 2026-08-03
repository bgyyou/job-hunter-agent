"""v3 M-rebuild-1: JD 解析器测试

覆盖 text/image/rag 三路径 + OCR 校对标志 + LLM 失败降级 + Router 路由。
"""
import pytest
import asyncio

from services.jd_parser import (
    StructuredJD,
    TextJDParser,
    ImageJDParser,
    RAGJDRetriever,
    JDParserRouter,
)


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class FakeLLMClient:
    """测试用 fake LLM client（模拟 analyze_with_structured_output 返回结构化 JD）。"""

    def __init__(self, response=None, raise_exc=False):
        self.response = response or {
            "company": "字节跳动",
            "title": "AI 产品经理",
            "industry": "互联网",
            "function": "产品",
            "level": "senior",
            "responsibilities": ["负责 AI Agent 产品规划", "协调研发团队"],
            "requirements": ["3年以上 AI 经验", "本科及以上"],
        }
        self.raise_exc = raise_exc
        self.calls = []

    async def analyze_with_structured_output(self, messages, output_schema, max_tokens=4000, temperature=0.1):
        self.calls.append({"messages": messages, "schema": output_schema})
        if self.raise_exc:
            raise RuntimeError("LLM 服务不可用")
        return self.response

    async def analyze(self, messages, max_tokens=4096, temperature=0.7, use_cache=True, system_prompt=None):
        from tools.llm import LLMResponse
        return LLMResponse(
            content='{"rewrites": []}',
            model="fake",
            tokens_used=42,
            finish_reason="stop",
        )


class FakeDB:
    """测试用 fake db（v4-2 修复后仍保留，供 schema_v3 测试使用）。"""

    def __init__(self, rows=None):
        self.rows = rows or [
            {
                "id": 1,
                "industry": "互联网",
                "function": "产品",
                "level": "senior",
                "sample_jds": [
                    {
                        "company": "字节跳动",
                        "title": "AI 产品经理",
                        "responsibilities": ["负责 AI 产品规划"],
                        "requirements": ["3年以上 AI 经验"],
                    }
                ],
                "sample_resumes": [],
                "scoring_rubric": None,
                "source": "user_contributed",
            }
        ]

    def list_rag_by_industry_function(self, industry, function, level=None, limit=50):
        return [r for r in self.rows if r["industry"] == industry and r["function"] == function]


class FakeRetriever:
    """v4-2 修复后：mock Retriever 走 RAGJDRetriever 的语义检索路径。"""

    def __init__(self, chunks=None):
        self.chunks = chunks if chunks is not None else []
        self.last_query = None

    def retrieve(self, query, **kwargs):
        self.last_query = query
        return self.chunks


class TestTextJDParser:
    """TextJDParser：关键词 + LLM 抽结构。"""

    def test_empty_text_returns_empty(self):
        """空文本 → 返回 raw_text 为空的 StructuredJD + parse_notes。"""
        parser = TextJDParser(llm_client=None)
        jd = _run(parser.parse(""))
        assert jd.raw_text == ""
        assert "空文本" in jd.parse_notes[0]

    def test_keyword_only_parsing(self):
        """无 LLM 时走关键词兜底，能抽出公司/岗位/职责/要求。"""
        parser = TextJDParser(llm_client=None)
        text = """
字节跳动有限公司

招聘：AI 产品经理

职责：
• 负责 AI Agent 产品规划
• 协调研发团队

要求：
• 3年以上 AI 经验
• 本科及以上
"""
        jd = _run(parser.parse(text))
        assert jd.company == "字节跳动有限公司"
        assert jd.title == "AI 产品经理"
        assert "负责 AI Agent 产品规划" in jd.responsibilities
        assert "3年以上 AI 经验" in jd.requirements
        assert "关键词" in jd.parse_notes[0]
        assert jd.needs_user_review is False

    def test_llm_parsing_overrides_keywords(self):
        """有 LLM 时调用 LLM，返回 LLM 抽出的结构。"""
        fake = FakeLLMClient()
        parser = TextJDParser(llm_client=fake)
        jd = _run(parser.parse("随便一段文本"))
        assert jd.company == "字节跳动"
        assert jd.title == "AI 产品经理"
        assert "负责 AI Agent 产品规划" in jd.responsibilities
        assert len(fake.calls) == 1  # LLM 被调用一次

    def test_llm_failure_falls_back_to_keywords(self):
        """LLM 失败时降级到关键词。"""
        fake = FakeLLMClient(raise_exc=True)
        parser = TextJDParser(llm_client=fake)
        text = "字节跳动有限公司\n招聘：AI 产品经理\n职责：负责 AI Agent 产品规划"
        jd = _run(parser.parse(text))
        assert jd.company == "字节跳动有限公司"
        assert "LLM 失败" in jd.parse_notes[0]


class TestImageJDParser:
    """ImageJDParser：PaddleOCR + 强制 needs_user_review=True。"""

    def test_image_parser_always_needs_review(self, monkeypatch):
        """ImageJDParser 不论 OCR 是否成功，needs_user_review 必须为 True。"""
        # mock OCR
        monkeypatch.setattr(
            "services.jd_parser.ImageJDParser._ocr",
            lambda self, path: "字节跳动\n招聘：AI 产品经理\n职责：负责 AI 产品规划",
        )
        parser = ImageJDParser(llm_client=FakeLLMClient())
        jd = _run(parser.parse("/tmp/fake.png"))
        assert jd.source == "image"
        assert jd.needs_user_review is True
        assert "OCR" in " ".join(jd.parse_notes)

    def test_image_parser_ocr_failure(self, monkeypatch):
        """OCR 失败时仍返回 StructuredJD，needs_user_review=True。"""
        monkeypatch.setattr(
            "services.jd_parser.ImageJDParser._ocr",
            lambda self, path: "",
        )
        parser = ImageJDParser(llm_client=FakeLLMClient())
        jd = _run(parser.parse("/tmp/fake.png"))
        assert jd.source == "image"
        assert jd.needs_user_review is True


class TestRAGJDRetriever:
    """RAGJDRetriever（v4-2 修复后）：走 Retriever 语义检索合成 StructuredJD。"""

    def test_missing_industry_returns_error(self):
        """缺 industry 时返回带 note 的空 StructuredJD。"""
        retriever = RAGJDRetriever(db=FakeDB())
        jd = _run(retriever.parse({}))
        assert "缺 industry/function" in jd.parse_notes[0]

    def test_db_none_returns_warning(self):
        """db=None 时返回 warning 不抛异常。"""
        retriever = RAGJDRetriever(db=None)
        jd = _run(retriever.parse({"industry": "互联网", "function": "产品"}))
        assert "数据库未配置" in jd.parse_notes[0]

    def test_no_chunks_returns_hint_to_use_text_image(self, monkeypatch):
        """Retriever 返 0 chunk 时，提示用户用 Text 或 Image 路径。"""
        monkeypatch.setattr(
            "tools.retriever.Retriever", lambda **kw: FakeRetriever(chunks=[])
        )
        retriever = RAGJDRetriever(db=FakeDB())
        jd = _run(retriever.parse({"industry": "互联网", "function": "产品", "position": "AI 产品经理"}))
        assert jd.source == "rag"
        assert "无命中" in jd.parse_notes[0]
        assert "Text" in jd.parse_notes[0] or "Image" in jd.parse_notes[0]

    def test_chunks_synthesize_structured_jd(self, monkeypatch):
        """Retriever 返 chunk 时，按 chunk_type 拆 responsibilities / requirements 合成 StructuredJD。"""
        fake_chunks = [
            {
                "chunk_text": "负责 AI 产品规划与落地",
                "chunk_type": "responsibility",
                "similarity": 0.85,
                "metadata": {"jd_id": "fake-jd-1", "chunk_index": 1},
            },
            {
                "chunk_text": "3年以上 AI 产品经验",
                "chunk_type": "requirement",
                "similarity": 0.78,
                "metadata": {"jd_id": "fake-jd-1", "chunk_index": 2},
            },
            {
                "chunk_text": "熟悉 LLM 应用场景",
                "chunk_type": "requirement",
                "similarity": 0.72,
                "metadata": {"jd_id": "fake-jd-2", "chunk_index": 3},
            },
        ]
        monkeypatch.setattr(
            "tools.retriever.Retriever", lambda **kw: FakeRetriever(chunks=fake_chunks)
        )

        class DBWithGet:
            def get_jd(self, jd_id):
                if jd_id == "fake-jd-1":
                    return {"title": "AI 产品经理", "company": "字节跳动"}
                return None

        retriever = RAGJDRetriever(db=DBWithGet())
        jd = _run(retriever.parse({
            "industry": "互联网", "function": "产品", "level": "senior",
            "position": "AI 产品经理",
        }))

        assert jd.source == "rag"
        assert jd.industry == "互联网"
        assert jd.function == "产品"
        assert jd.title == "AI 产品经理"  # 来自 fake-jd-1
        assert jd.company == "字节跳动"
        assert len(jd.responsibilities) == 1
        assert "AI 产品规划" in jd.responsibilities[0]
        assert len(jd.requirements) == 2
        assert "3年以上" in jd.requirements[0]
        assert "召回" in jd.parse_notes[0]
        assert "3 个 chunk" in jd.parse_notes[0]
        assert "来自 2 个 JD" in jd.parse_notes[0]


class TestJDParserRouter:
    """JDParserRouter：按 source 路由。"""

    def test_text_route(self):
        router = JDParserRouter(llm_client=None)
        jd = _run(router.parse("text", "字节跳动\n招聘：AI 产品经理\n职责：负责 AI 产品"))
        assert jd.source == "text"

    def test_image_route(self, monkeypatch):
        monkeypatch.setattr(
            "services.jd_parser.ImageJDParser._ocr",
            lambda self, path: "字节跳动\n招聘：AI 产品经理",
        )
        router = JDParserRouter(llm_client=None)
        jd = _run(router.parse("image", "/tmp/fake.png"))
        assert jd.source == "image"
        assert jd.needs_user_review is True

    def test_rag_route(self):
        router = JDParserRouter(llm_client=None, db=FakeDB())
        jd = _run(router.parse("rag", {"industry": "互联网", "function": "产品"}))
        assert jd.source == "rag"

    def test_unknown_source_raises(self):
        router = JDParserRouter(llm_client=None)
        with pytest.raises(ValueError, match="Unknown JD source"):
            _run(router.parse("unknown", "x"))


class TestStructuredJDToDb:
    """StructuredJD.to_db_dict() 转换测试。"""

    def test_to_db_dict_keys(self):
        jd = StructuredJD(
            source="text",
            company="字节",
            title="PM",
            responsibilities=["A"],
            requirements=["B"],
        )
        d = jd.to_db_dict()
        assert d["source"] == "text"
        assert d["company"] == "字节"
        assert d["responsibilities"] == ["A"]
        assert "user_id" not in d