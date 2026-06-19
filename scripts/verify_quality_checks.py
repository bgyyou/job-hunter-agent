"""验证 quality_checks 埋点真实落库（M5/N2 兜底）。

不依赖 Streamlit UI：直接调 VolcanoClient.analyze 跑一次真实 LLM，
然后从 quality_checks 表读回，确认 details 包含 model/latency_ms/tokens 等字段。

用法：
    DATABASE_URL=sqlite:///data/jobhunter_v2.db python scripts/verify_quality_checks.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")


async def main() -> int:
    from database.factory import get_db
    from tools.llm import LLMMessage, VolcanoClient

    db = get_db()
    backend_name = type(db).__name__
    before = len(db.list_quality_checks(check_type="llm_call"))
    print(f"[setup] backend={backend_name}  llm_call rows before = {before}")

    api_key = os.environ.get("VOLCANO_API_KEY")
    if not api_key or api_key == "your_api_key_here":
        print("[fatal] VOLCANO_API_KEY 未配置")
        return 2

    api_url = os.environ.get("VOLCANO_CODING_API_URL") or os.environ.get(
        "VOLCANO_CHAT_API_URL", "https://ark.cn-beijing.volces.com/api/v3"
    )
    model = os.environ.get("VOLCANO_MODEL", "deepseek-v3-1-250821")
    use_anthropic = os.environ.get("VOLCANO_USE_ANTHROPIC_FORMAT", "false").lower() == "true"

    print(f"[setup] model={model}  url={api_url}  anthropic_fmt={use_anthropic}")

    client = VolcanoClient(
        api_key=api_key,
        api_url=api_url,
        model=model,
        use_anthropic_format=use_anthropic,
    )

    msg = [LLMMessage(role="user", content="只回复一个汉字：好")]

    print("[run] cold call (no cache)…")
    r1 = await client.analyze(msg, max_tokens=16, temperature=0.0, use_cache=False)
    print(f"       reply={r1.content!r}  tokens={r1.tokens_used}")

    print("[run] cached call…")
    r2 = await client.analyze(msg, max_tokens=16, temperature=0.0, use_cache=True)
    print(f"       reply={r2.content!r}  tokens={r2.tokens_used}")

    rows = db.list_quality_checks(check_type="llm_call")
    after = len(rows)
    print(f"[check] llm_call rows after = {after}  (delta={after - before})")

    if after - before < 1:
        print("[fail] quality_checks 没有新行，埋点未落库。")
        return 1

    last = rows[0] if rows else {}
    details = last.get("details") or {}
    print(f"[check] last row score={last.get('score')}  details keys={sorted(details.keys())}")
    required_keys = {"model", "latency_ms", "tokens", "cache_hit", "ok"}
    missing = required_keys - set(details.keys())
    if missing:
        print(f"[fail] details 缺失字段：{missing}")
        return 1

    print("[pass] quality_checks embed real-write OK")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
