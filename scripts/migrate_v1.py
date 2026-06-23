#!/usr/bin/env python3
"""
migrate_v1.py — Merge all existing data sources into the unified jobhunter_v2.db.

NOTE: 旧数据（crawler.db、knowledge_bases JSON）已清除。此脚本保留仅作历史参考。
      如需重新迁移旧数据，请先恢复备份文件后取消下方 NOTE 注释。

Usage:
    python scripts/migrate_v1.py              # perform migration
    python scripts/migrate_v1.py --dry-run    # preview only, no writes
"""

import argparse
import json
import re
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
from loguru import logger

# Paths
PROJECT_ROOT = Path(__file__).parent.parent
OLD_DB = Path.home() / ".job_hunter" / "crawler.db"
NEW_DB = PROJECT_ROOT / "data" / "jobhunter_v2.db"
KB_DIR = PROJECT_ROOT / "data" / "knowledge_bases"
SCHEMA = PROJECT_ROOT / "data" / "schema.sql"


def normalize_url(url: str) -> str:
    """Normalize URL: keep only /job/XXXXX part."""
    match = re.search(r"(https?://[^/]+/job/\d+)", url)
    if match:
        return match.group(1)
    return url.split("?")[0].split("#")[0]


# ================================================================
# Phase 1: Backup
# ================================================================

def backup_old_db(dry_run: bool):
    if not OLD_DB.exists():
        logger.info(f"Old DB not found at {OLD_DB}, skipping backup.")
        return
    if dry_run:
        logger.info(f"[DRY-RUN] Would backup {OLD_DB} -> {OLD_DB}.backup")
        return
    backup = Path(str(OLD_DB) + ".backup")
    shutil.copy2(OLD_DB, backup)
    logger.info(f"Backed up {OLD_DB} -> {backup}")


# ================================================================
# Phase 2: Merge crawled_jobs and crawled_jds
# ================================================================

def migrate_crawled_data(db, dry_run: bool) -> Dict[str, int]:
    """Merge crawled_jobs + crawled_jds from crawler.db into new jds table."""
    if not OLD_DB.exists():
        logger.info("No old crawler.db found, skipping crawl migration.")
        return {"crawled_jobs": 0, "crawled_jds": 0, "jds_inserted": 0, "jds_duplicate": 0}

    conn = sqlite3.connect(str(OLD_DB))
    conn.row_factory = sqlite3.Row

    counts = {"crawled_jobs": 0, "crawled_jds": 0, "jds_inserted": 0, "jds_duplicate": 0}

    # --- crawled_jobs ---
    rows = conn.execute("SELECT * FROM crawled_jobs").fetchall()
    counts["crawled_jobs"] = len(rows)
    logger.info(f"Found {counts['crawled_jobs']} records in crawled_jobs")

    for row in rows:
        url = normalize_url(row["url"])
        jd_data = {
            "url": url,
            "title": row.get("title", ""),
            "company": row.get("company", ""),
            "location": row.get("location", ""),
            "salary_str": row.get("salary_str"),
            "salary_min": row.get("salary_min"),
            "salary_max": row.get("salary_max"),
            "raw_text": row.get("raw_text", ""),
            "source": row.get("source", "crawler"),
            "platform": row.get("platform", "jobsdb"),
            "job_id": row.get("job_id"),
            "search_keyword": row.get("search_keyword"),
            "crawled_at": row.get("crawled_at"),
        }
        _insert_jd_with_classification(db, jd_data, counts, dry_run, "crawler")

    # --- crawled_jds ---
    rows = conn.execute("SELECT * FROM crawled_jds").fetchall()
    counts["crawled_jds"] = len(rows)
    logger.info(f"Found {counts['crawled_jds']} records in crawled_jds")

    for row in rows:
        url = normalize_url(row["url"])
        jd_data = {
            "url": url,
            "title": row.get("title", ""),
            "company": row.get("company", ""),
            "location": row.get("location", ""),
            "salary_str": row.get("salary"),
            "raw_text": row.get("raw_text", ""),
            "source": row.get("source", "jd_crawler"),
            "search_keyword": row.get("search_keyword"),
            "crawled_at": row.get("crawled_at"),
        }
        _insert_jd_with_classification(db, jd_data, counts, dry_run, "jd_crawler")

    conn.close()
    return counts


def _insert_jd_with_classification(
    db, jd_data: Dict, counts: Dict, dry_run: bool, default_source: str
):
    """Insert a JD into new DB, classifying it first."""
    url = jd_data.get("url", "")
    if not url:
        return

    # Check if already exists (from crawled_jobs or crawled_jds)
    existing = db.get_jd_by_url(url)
    if existing:
        counts["jds_duplicate"] += 1
        return

    # Classify
    title = jd_data.get("title", "")
    raw_text = jd_data.get("raw_text", "")
    if not title:
        title = "Unknown"
    counts["jds_inserted"] += 1

    if dry_run:
        logger.debug(f"  [DRY-RUN] Would insert JD: {title} ({url})")
        return

    jd_data["source"] = default_source
    db.insert_jd(jd_data)
    logger.debug(f"  Inserted: {title}")


# ================================================================
# Phase 3: Import KnowledgeBase JSON files
# ================================================================

def migrate_knowledge_base(db, dry_run: bool) -> Dict[str, int]:
    """Import all JSON files from data/knowledge_bases/ into jds table."""
    if not KB_DIR.exists():
        logger.info("No knowledge_bases directory found, skipping KB migration.")
        return {"dirs": 0, "files": 0, "imported": 0, "duplicate": 0}

    counts = {"dirs": 0, "files": 0, "imported": 0, "duplicate": 0}

    for role_dir in sorted(KB_DIR.iterdir()):
        if not role_dir.is_dir():
            continue
        counts["dirs"] += 1
        json_files = sorted(role_dir.glob("jd_*.json"))
        if not json_files:
            continue

        counts["files"] += len(json_files)
        logger.info(f"Processing knowledge base '{role_dir.name}': {len(json_files)} files")

        for json_file in json_files:
            counts["files"]  # count already added above
            try:
                data = json.loads(json_file.read_text(encoding="utf-8"))
            except json.JSONDecodeError as e:
                logger.warning(f"Skipping invalid JSON {json_file.name}: {e}")
                continue

            # Extract fields
            raw_text = data.get("raw_text", "")
            parsed = data.get("parsed_data", {})
            title = parsed.get("title", "") or data.get("title", "")
            company = parsed.get("company", "")
            location = parsed.get("location", "")
            skills = parsed.get("skills", [])
            core_reqs = parsed.get("core_requirements", [])
            pref_reqs = parsed.get("preferred_requirements", [])
            keywords = parsed.get("keywords", [])

            # Generate synthetic URL if missing
            url = f"knowledge_base://{role_dir.name}/{data.get('id', json_file.stem)}"

            jd_data = {
                "id": data.get("id"),
                "url": url,
                "title": title or "Unknown",
                "company": company,
                "location": location,
                "raw_text": raw_text,
                "parsed_data": data.get("parsed_data"),
                "source": "manual",
                "skills_required": skills + keywords,
                "requirements": core_reqs,
                "preferred_requirements": pref_reqs,
            }

            counts["files"]  # already counted
            if dry_run:
                logger.debug(f"  [DRY-RUN] Would import: {jd_data.get('title', '?')}")
            else:
                existing = db.get_jd_by_url(url)
                if existing:
                    counts["duplicate"] += 1
                    logger.debug(f"  Duplicate: {jd_data.get('title', '?')}")
                else:
                    db.insert_jd(jd_data)
                    counts["imported"] += 1
                    logger.debug(f"  Imported: {jd_data.get('title', '?')}")

    return counts


# ================================================================
# Phase 4: Schema version
# ================================================================

def init_schema_version(db, dry_run: bool):
    if dry_run:
        logger.info("[DRY-RUN] Would set schema_version = 1")
        return
    # Already set by schema.sql, just verify
    conn = db._get_conn()
    try:
        row = conn.execute("SELECT version FROM schema_version WHERE id = 1").fetchone()
        if row:
            logger.info(f"schema_version = {row[0]}")
        else:
            conn.execute(
                "INSERT INTO schema_version (id, version, description) VALUES (1, 1, 'Migrated v1')"
            )
            conn.commit()
    finally:
        conn.close()


# ================================================================
# Phase 5: Summary report
# ================================================================

def print_report(
    crawl_counts: Dict, kb_counts: Dict, db, dry_run: bool
):
    print("\n" + "=" * 60)
    print("  Migration Report")
    print("=" * 60)
    if dry_run:
        print("  *** DRY RUN - No data was written ***\n")

    print("  Old DB (crawler.db):")
    print(f"    - crawled_jobs: {crawl_counts.get('crawled_jobs', 0)} records")
    print(f"    - crawled_jds:  {crawl_counts.get('crawled_jds', 0)} records")
    print()
    print("  KnowledgeBase:")
    print(f"    - Directories processed: {kb_counts.get('dirs', 0)}")
    print(f"    - JSON files processed:  {kb_counts.get('files', 0)}")
    print(f"    - Imported:              {kb_counts.get('imported', 0)}")
    print(f"    - Duplicates skipped:    {kb_counts.get('duplicate', 0)}")
    print()

    if not dry_run:
        stats = db.get_stats()
        print("  New DB (jobhunter_v2.db):")
        for table, count in stats.items():
            print(f"    - {table}: {count} records")
    else:
        print("  (New DB stats not available in dry-run mode)")

    print("=" * 60)


# ================================================================
# Main
# ================================================================

def main():
    parser = argparse.ArgumentParser(description="Migrate all data to jobhunter_v2.db")
    parser.add_argument("--dry-run", action="store_true", help="Preview migration without writing")
    args = parser.parse_args()

    logger.info("Starting migration...")

    # Ensure new DB is initialized
    if not args.dry_run:
        from database.backends.sqlite_backend import SqliteBackend
        db = SqliteBackend(db_path=str(NEW_DB))
    else:
        # Create a temporary connection for dry-run reads
        import sqlite3
        db = None

    # Phase 1: Backup
    backup_old_db(args.dry_run)

    # Phase 2: Merge crawled data
    if db:
        crawl_counts = migrate_crawled_data(db, args.dry_run)
    else:
        crawl_counts = {"crawled_jobs": 0, "crawled_jds": 0, "jds_inserted": 0, "jds_duplicate": 0}

    # Phase 3: Import KnowledgeBase
    if db:
        kb_counts = migrate_knowledge_base(db, args.dry_run)
    else:
        kb_counts = {"dirs": 0, "files": 0, "imported": 0, "duplicate": 0}

    # Phase 4: Schema version
    if db:
        init_schema_version(db, args.dry_run)

    # Phase 5: Report
    if db:
        print_report(crawl_counts, kb_counts, db, args.dry_run)
    else:
        print("\n  *** DRY RUN (no DB connection) ***")

    print("\nMigration complete.")


if __name__ == "__main__":
    main()
