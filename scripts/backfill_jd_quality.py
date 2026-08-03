# -*- coding: utf-8 -*-
"""一次性回填 jds.quality_score：遍历所有非删 jds → compute_jd_quality → 写回。

用法：
    python scripts/backfill_jd_quality.py              # 全量回填
    python scripts/backfill_jd_quality.py --limit 500  # 限速
    python scripts/backfill_jd_quality.py --dry-run    # 只算不写
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from database.factory import get_db  # noqa: E402
from services.jd_quality_service import compute_jd_quality, quality_label  # noqa: E402
from loguru import logger  # noqa: E402


def _iter_all_jds(db, limit: int | None = None):
    """拉全部未删 jds，对 JSON 字段（parsed_sections / tags）做反序列化。"""
    import json

    conn = db._get_conn()
    try:
        sql = "SELECT * FROM jds WHERE deleted_at IS NULL ORDER BY crawled_at DESC"
        params: tuple = ()
        if limit:
            sql += " LIMIT ?"
            params = (limit,)
        try:
            rows = conn.execute(sql, params).fetchall()
        except Exception:
            rows = conn.execute(
                "SELECT * FROM jds WHERE deleted_at IS NULL ORDER BY crawled_at DESC"
            ).fetchall()
        results = []
        for row in rows:
            d = dict(row)
            for field in ("parsed_sections", "tags"):
                val = d.get(field)
                if isinstance(val, str):
                    try:
                        d[field] = json.loads(val)
                    except (json.JSONDecodeError, TypeError):
                        d[field] = {} if field == "parsed_sections" else []
            results.append(d)
        return results
    finally:
        try:
            conn.close()
        except Exception:
            pass


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="Limit number of JDs to score")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    db = get_db()
    rows = _iter_all_jds(db, limit=args.limit or None)
    logger.info(f"backfill scoring {len(rows)} JDs (dry_run={args.dry_run})")

    scored = 0
    buckets = {"★★★★": 0, "★★★": 0, "★★": 0, "★": 0, "未评分": 0}

    for row in rows:
        result = compute_jd_quality(row)
        label = quality_label(result["composite"])
        buckets[label] = buckets.get(label, 0) + 1
        if not args.dry_run:
            now_iso = datetime.now(timezone.utc).isoformat()
            db.update_jd_quality_score(row["id"], result["composite"], now_iso)
            try:
                db.insert_quality_check(
                    {
                        "check_type": "jd_quality",
                        "target_table": "jds",
                        "target_id": row["id"],
                        "score": result["composite"],
                        "details": {
                            "subscores": {
                                k: result[k]
                                for k in (
                                    "parse_completeness",
                                    "source_authority",
                                    "freshness",
                                    "text_richness",
                                )
                            },
                            "is_garbage": result.get("is_garbage", False),
                            "backfill": True,
                        },
                    },
                    user_id="backfill_jd_quality_script",
                )
            except Exception as exc:
                logger.warning(f"quality_checks write failed for {row['id']}: {exc}")
        scored += 1

    logger.info(f"scored {scored} JDs.")
    for label, count in sorted(buckets.items(), key=lambda kv: -kv[1]):
        logger.info(f"  {label}: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
