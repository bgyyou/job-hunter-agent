"""LLM-as-judge for RAG recall eval (P0-模块 6 子任务 1, 2026-07-24).

两种调用模式：
1. judge(query, jd_id, title, text) → 单个 (query, candidate) 打分（1-5）
2. judge_batch_per_query(queries, candidates_per_query) → 每个 query 一次 LLM 调用，
   返回 10 个候选的分数。10× call 缩减，Agnes free tier 限流下必备。

Judge 模型：默认走 Agnes (LLM_API_KEY/LLM_BASE_URL/LLM_MODEL)。
若 LLM_API_KEY 缺失 / API 失败 → 自动 fallback 到 mock judge，并在结果中标注 MOCK。
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(PROJECT_ROOT / ".env")


JUDGE_PROMPT = """You are evaluating how relevant a candidate Job Description (JD) is to a recruiter search query.

Query: {query}

Candidate JD (title + snippet):
{candidate}

Rate the relevance on a 1-5 scale:
- 5 = Highly relevant: the JD is exactly the role the searcher is looking for
- 4 = Strongly relevant: very close match, same role / skills / industry
- 3 = Moderately relevant: overlapping skills or related role, but not a perfect match
- 2 = Weakly relevant: tangentially related (same broad industry, or one skill matches)
- 1 = Not relevant: different role / industry / skills

Return only a single digit (1, 2, 3, 4, or 5). No explanation."""


BATCH_JUDGE_PROMPT = """You are evaluating how relevant multiple candidate Job Descriptions (JDs) are to a single recruiter search query.

Query: {query}

Rate EACH candidate on a 1-5 scale (5 = highly relevant exact match, 1 = not relevant).
Output ONLY a JSON array of N integers, one per candidate in order:
[cand_1_score, cand_2_score, ..., cand_N_score]

Candidates:
{candidates_block}

Return ONLY the JSON array, no explanation, no markdown fences."""


@dataclass
class JudgeVerdict:
    query: str
    candidate_jd_id: Optional[str]
    candidate_title: str
    candidate_text: str
    score: int
    is_mock: bool
    raw_response: str = ""


def _parse_score(raw: str) -> int:
    """Extract single 1-5 score from LLM response."""
    raw = (raw or "").strip()
    m = re.search(r"[1-5]", raw)
    if m:
        return int(m.group(0))
    return 3


def _parse_score_array(raw: str, n: int) -> list[int]:
    """Extract N integer scores (1-5) from JSON array response."""
    raw = (raw or "").strip()
    # 优先尝试 JSON
    try:
        # 容忍 ```json``` 包裹
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        arr = json.loads(raw)
        if isinstance(arr, list) and len(arr) >= n:
            scores = []
            for x in arr[:n]:
                v = int(x)
                v = max(1, min(5, v))
                scores.append(v)
            # pad if short
            while len(scores) < n:
                scores.append(3)
            return scores
    except (json.JSONDecodeError, ValueError, TypeError):
        pass
    # fallback: regex 抓 n 个数字
    digits = re.findall(r"[1-5]", raw)
    if len(digits) >= n:
        return [int(d) for d in digits[:n]]
    # 全部 fallback 到 3
    return [3] * n


def _is_rate_limit_error(exc: Exception) -> bool:
    """识别 429 / rate limit 类异常，用于触发更长退避。"""
    err_text = str(exc).lower()
    return (
        "429" in err_text
        or "rate limit" in err_text
        or "too many requests" in err_text
    )


def _get_retry_config() -> tuple[int, float]:
    """读取 judge retry 配置（stdlib only，无新增依赖）。

    - JUDGE_MAX_RETRIES：429 时最大重试次数（默认 5），非 429 一律 1 次。
    - JUDGE_RETRY_BASE_DELAY：429 指数退避基数秒数（默认 1.0）。
    """
    try:
        n = int(os.environ.get("JUDGE_MAX_RETRIES", "5"))
    except ValueError:
        n = 5
    try:
        base = float(os.environ.get("JUDGE_RETRY_BASE_DELAY", "1.0"))
    except ValueError:
        base = 1.0
    return max(0, n), max(0.0, base)


def _get_default_concurrency() -> int:
    """读取 judge batch 并发上限（默认 1，串行避开限流）。

    环境变量 LLM_JUDGE_CONCURRENCY；非法值回退到 1。
    """
    try:
        return max(1, int(os.environ.get("LLM_JUDGE_CONCURRENCY", "1")))
    except ValueError:
        return 1


def _mock_judge(query: str, jd_id: Optional[str], title: str, text: str) -> JudgeVerdict:
    """Mock judge：基于 query-candidate 词重叠打分。

    - 高重叠（≥40% query 词在 candidate 中）→ 4
    - 中等重叠（≥1）→ 3
    - 无重叠 → 2
    """
    q_words = set(query.lower().split())
    text_lower = (title + " " + text).lower()
    overlap = sum(1 for w in q_words if len(w) > 1 and w in text_lower)
    if overlap >= max(2, len(q_words) * 0.4):
        score = 4
    elif overlap >= 1:
        score = 3
    else:
        score = 2
    return JudgeVerdict(
        query=query, candidate_jd_id=jd_id, candidate_title=title,
        candidate_text=text[:200], score=score, is_mock=True,
        raw_response="MOCK",
    )


class LLMJudge:
    """LLM-as-judge 打分器。"""

    def __init__(self, model: Optional[str] = None, use_anthropic_format: Optional[bool] = None):
        self.model = model or os.environ.get("LLM_MODEL", "agnes-2.0-flash")
        self.api_key = os.environ.get("LLM_API_KEY", "")
        self.base_url = os.environ.get("LLM_BASE_URL", "")
        if use_anthropic_format is None:
            use_anthropic_format = os.environ.get("LLM_USE_ANTHROPIC_FORMAT", "false").lower() == "true"
        self.use_anthropic_format = use_anthropic_format
        self._client = None
        self.is_available = bool(self.api_key and self.base_url)

    def _get_client(self):
        if self._client is not None:
            return self._client
        if not self.is_available:
            return None
        from tools.llm import OpenAICompatibleClient
        self._client = OpenAICompatibleClient(
            api_key=self.api_key,
            api_url=self.base_url,
            model=self.model,
            use_anthropic_format=self.use_anthropic_format,
            user_id="rag_eval_judge",
        )
        return self._client

    async def judge(self, query: str, jd_id: Optional[str], title: str, text: str,
                    retries: int = 2) -> JudgeVerdict:
        """Single (query, candidate) → JudgeVerdict. Mock fallback on API failure.

        429 重试策略由环境变量 JUDGE_MAX_RETRIES / JUDGE_RETRY_BASE_DELAY 控制；
        非 429 异常只重试 1 次（避免无效循环拉长单条 judge 时间）。
        """
        client = self._get_client()
        if client is None:
            return _mock_judge(query, jd_id, title, text)

        from tools.llm import LLMMessage
        prompt = JUDGE_PROMPT.format(
            query=query,
            candidate=f"Title: {title}\nSnippet: {(text or '')[:400]}",
        )
        max_rate_retries, base_delay = _get_retry_config()
        last_err: Optional[Exception] = None
        attempt = 0
        # 最多 max_rate_retries 次 429 重试 + 1 次非 429 重试；先放 429 retry loop
        while True:
            try:
                resp = await client.analyze(
                    [LLMMessage(role="user", content=prompt)],
                    max_tokens=10,
                    temperature=0.0,
                    use_cache=True,
                )
                score = _parse_score(resp.content)
                return JudgeVerdict(
                    query=query, candidate_jd_id=jd_id, candidate_title=title,
                    candidate_text=text[:200], score=score, is_mock=False,
                    raw_response=resp.content,
                )
            except Exception as exc:
                last_err = exc
                is_429 = _is_rate_limit_error(exc)
                # 429：指数退避 1s/2s/4s/8s/16s（最多 max_rate_retries 次）
                # 其他：仅 1 次重试
                if is_429:
                    if attempt >= max_rate_retries:
                        break
                    backoff = base_delay * (2 ** attempt)
                    print(
                        f"[judge] 429 rate limit, retry {attempt + 1}/{max_rate_retries} "
                        f"in {backoff:.1f}s (query={query[:30]}...): {str(exc)[:80]}"
                    )
                    attempt += 1
                    await asyncio.sleep(backoff)
                    continue
                else:
                    if attempt >= 1:
                        break
                    print(
                        f"[judge] non-429 error, retry 1/1 in 0.5s "
                        f"(query={query[:30]}...): {str(exc)[:80]}"
                    )
                    attempt += 1
                    await asyncio.sleep(0.5)
                    continue
        # 全 retry 失败 → mock fallback（区分 429 vs other）
        kind = "429_RATE_LIMIT" if last_err and _is_rate_limit_error(last_err) else "OTHER_ERROR"
        v = _mock_judge(query, jd_id, title, text)
        v.raw_response = f"FALLBACK_MOCK ({kind}, err: {str(last_err)[:80]})"
        return v

    async def _judge_query_batch(self, query: dict, cands: list[dict],
                                  retries: int = 2) -> list[JudgeVerdict]:
        """One LLM call per query, returns N scores for N candidates.

        429 重试策略由环境变量 JUDGE_MAX_RETRIES / JUDGE_RETRY_BASE_DELAY 控制；
        非 429 异常只重试 1 次（避免无效循环拉长单条 judge 时间）。
        """
        if not cands:
            return []
        client = self._get_client()
        if client is None:
            return [_mock_judge(query["query"], c.get("jd_id"), c.get("title", ""), c.get("text", ""))
                    for c in cands]

        from tools.llm import LLMMessage
        cand_lines = []
        for i, c in enumerate(cands):
            cand_lines.append(
                f"[{i+1}] Title: {c.get('title', '')}\n"
                f"    Snippet: {(c.get('text', '') or '')[:300]}"
            )
        candidates_block = "\n".join(cand_lines)
        prompt = BATCH_JUDGE_PROMPT.format(
            query=query["query"], candidates_block=candidates_block,
        )

        max_rate_retries, base_delay = _get_retry_config()
        last_err: Optional[Exception] = None
        attempt = 0
        while True:
            try:
                resp = await client.analyze(
                    [LLMMessage(role="user", content=prompt)],
                    max_tokens=200,  # 10 × "1" + comma = ~30 字符，留 headroom
                    temperature=0.0,
                    use_cache=True,
                )
                scores = _parse_score_array(resp.content, n=len(cands))
                verdicts = []
                for c, s in zip(cands, scores):
                    verdicts.append(JudgeVerdict(
                        query=query["query"],
                        candidate_jd_id=c.get("jd_id"),
                        candidate_title=c.get("title", ""),
                        candidate_text=c.get("text", "")[:200],
                        score=s,
                        is_mock=False,
                        raw_response=resp.content[:120],
                    ))
                return verdicts
            except Exception as exc:
                last_err = exc
                is_429 = _is_rate_limit_error(exc)
                if is_429:
                    if attempt >= max_rate_retries:
                        break
                    backoff = base_delay * (2 ** attempt)
                    print(
                        f"[judge_batch] 429 rate limit, retry {attempt + 1}/{max_rate_retries} "
                        f"in {backoff:.1f}s (qid={query.get('query_id', '?')}): {str(exc)[:80]}"
                    )
                    attempt += 1
                    await asyncio.sleep(backoff)
                    continue
                else:
                    if attempt >= 1:
                        break
                    print(
                        f"[judge_batch] non-429 error, retry 1/1 in 0.5s "
                        f"(qid={query.get('query_id', '?')}): {str(exc)[:80]}"
                    )
                    attempt += 1
                    await asyncio.sleep(0.5)
                    continue
        # 全 retry 失败 → mock fallback for all candidates（区分 429 vs other）
        kind = "429_RATE_LIMIT" if last_err and _is_rate_limit_error(last_err) else "OTHER_ERROR"
        err_short = str(last_err)[:80]
        verdicts = []
        for c in cands:
            v = _mock_judge(query["query"], c.get("jd_id"), c.get("title", ""), c.get("text", ""))
            v.raw_response = f"FALLBACK_MOCK ({kind}, err: {err_short})"
            verdicts.append(v)
        return verdicts


async def judge_batch_per_query(
    queries: list[dict],
    candidates_per_query: list[list[dict]],
    concurrency: Optional[int] = None,
) -> list[list[JudgeVerdict]]:
    """Batch judge: ask LLM once per query with all candidates → N scores.

    queries = [{query_id, query, ...}, ...]
    candidates_per_query[i] = [{jd_id, title, text}, ...]

    Returns verdicts_per_query[i] = [JudgeVerdict for each candidate in order].

    concurrency：未传时从 LLM_JUDGE_CONCURRENCY 环境变量读取，默认 1（串行）。
    默认串行是 [M-v4-1 judge 限流] 节决策：避免并发触发 MiniMax 429。
    """
    if concurrency is None:
        concurrency = _get_default_concurrency()
    judge = LLMJudge()
    sem = asyncio.Semaphore(concurrency)

    async def _one(q: dict, cands: list[dict]) -> list[JudgeVerdict]:
        async with sem:
            await asyncio.sleep(0.05)  # jitter
            return await judge._judge_query_batch(q, cands)

    tasks = [_one(q, cs) for q, cs in zip(queries, candidates_per_query)]
    return await asyncio.gather(*tasks)


# 保留向后兼容的 judge_batch（per-candidate 旧接口）
async def judge_batch(items: list[dict], concurrency: Optional[int] = None) -> list[JudgeVerdict]:
    """Per-candidate judge（向后兼容，新代码用 judge_batch_per_query）。

    items = [{query, jd_id, title, text}, ...]

    concurrency：未传时从 LLM_JUDGE_CONCURRENCY 环境变量读取，默认 1。
    """
    if concurrency is None:
        concurrency = _get_default_concurrency()
    judge = LLMJudge()
    sem = asyncio.Semaphore(concurrency)

    async def _one(it):
        async with sem:
            await asyncio.sleep(0.05)
            return await judge.judge(it["query"], it.get("jd_id"), it.get("title", ""), it.get("text", ""))

    tasks = [_one(it) for it in items]
    return await asyncio.gather(*tasks)


if __name__ == "__main__":
    # 冒烟测试
    async def _smoke():
        v = await LLMJudge().judge(
            "Python 数据分析 5年经验",
            "fake-id",
            "Data Analyst",
            "Looking for Python data analyst with 5 years of experience in SQL and Tableau.",
        )
        print(json.dumps(v.__dict__, ensure_ascii=False, indent=2))

        # batch 测试
        query = {"query_id": "t1", "query": "Python 数据分析"}
        cands = [
            {"jd_id": "a", "title": "Data Analyst", "text": "Python SQL required"},
            {"jd_id": "b", "title": "司机", "text": "Truck driver license required"},
        ]
        results = await judge_batch_per_query([query], [cands])
        print("\nBatch results:")
        for v in results[0]:
            print(f"  {v.candidate_title}: score={v.score} mock={v.is_mock}")

    asyncio.run(_smoke())