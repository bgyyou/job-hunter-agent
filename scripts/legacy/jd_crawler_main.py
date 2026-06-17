#!/usr/bin/env python3
"""
JobHunter - JD爬虫主程序
一键启动JobsDB爬虫，支持多关键词、时间范围、自动去重
"""
import sys
import re
import asyncio
import argparse
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict
from loguru import logger

# 添加项目路径
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.scraper.jobsdb_scraper import JobsDBScraper


# =====================================================
# 数据库模块 - SQLite存储
# =====================================================
import sqlite3

class JDDatabase:
    """JD数据库 - SQLite存储"""

    def __init__(self, db_path: Optional[Path] = None):
        if db_path is None:
            db_path = Path.home() / ".job_hunter" / "crawler.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db_path = str(db_path)
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS crawled_jds (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    url TEXT UNIQUE NOT NULL,
                    title TEXT,
                    company TEXT,
                    raw_text TEXT,
                    location TEXT,
                    salary TEXT,
                    source TEXT DEFAULT 'jobsdb',
                    search_keyword TEXT,
                    days_old INTEGER,
                    crawled_at TEXT,
                    is_analyzed INTEGER DEFAULT 0
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_url ON crawled_jds(url)")

            # 数据库迁移：添加缺失的列
            self._add_column_if_missing(conn, "search_keyword", "TEXT")
            self._add_column_if_missing(conn, "days_old", "INTEGER")

    def _add_column_if_missing(self, conn, column_name, column_type):
        try:
            # 检查列是否存在
            cursor = conn.execute(f"PRAGMA table_info(crawled_jds)")
            columns = [row[1] for row in cursor.fetchall()]
            if column_name in columns:
                return

            # 列不存在，添加它
            conn.execute(f"ALTER TABLE crawled_jds ADD COLUMN {column_name} {column_type}")
            conn.commit()
        except Exception as e:
            pass

    def exists(self, url: str) -> bool:
        """检查URL是否已存在"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT 1 FROM crawled_jds WHERE url = ?", (url,))
            return cursor.fetchone() is not None

    def insert(self, job: Dict) -> int:
        """插入新JD"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                INSERT OR IGNORE INTO crawled_jds
                (url, title, company, raw_text, location, salary, source, search_keyword, days_old, crawled_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                job.get("url"),
                job.get("title"),
                job.get("company"),
                job.get("raw_text"),
                job.get("location"),
                job.get("salary"),
                job.get("source", "jobsdb"),
                job.get("search_keyword"),
                job.get("days_old"),
                job.get("crawled_at", datetime.now().isoformat()),
            ))
            return cursor.lastrowid

    def get_all(self) -> List[Dict]:
        """获取所有JD"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("SELECT * FROM crawled_jds ORDER BY crawled_at DESC")
            return [dict(row) for row in cursor.fetchall()]

    def get_count(self) -> int:
        """获取JD总数"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM crawled_jds")
            return cursor.fetchone()[0]


# =====================================================
# 辅助函数
# =====================================================

def normalize_url(url: str) -> str:
    """规范化 URL：只保留 /job/XXXXX 部分，去掉查询参数和 hash"""
    match = re.search(r'(https?://[^/]+/job/\d+)', url)
    if match:
        return match.group(1)
    return url.split('?')[0].split('#')[0]


def extract_company(raw_text: str) -> str:
    """从 raw_text 提取公司名"""
    if not raw_text:
        return ""
    lines = raw_text.split('\n')
    for i, line in enumerate(lines):
        line = line.strip()
        if line == "View all jobs" and i > 0:
            return lines[i-1].strip()
    return ""


def extract_title(raw_text: str) -> str:
    """从 raw_text 提取真实职位标题"""
    if not raw_text:
        return ""
    lines = raw_text.split('\n')
    for i, line in enumerate(lines):
        line = line.strip()
        if line == "View all jobs" and i > 1:
            return lines[i-2].strip()
    for line in lines:
        line = line.strip()
        if line and len(line) > 5 and len(line) < 100:
            return line
    return ""


def extract_days_old(raw_text: str) -> Optional[int]:
    """从 raw_text 提取发布天数"""
    if not raw_text:
        return None
    match = re.search(r'Posted (\d+)d\+? ago', raw_text)
    if match:
        return int(match.group(1))
    match = re.search(r'Posted (\d+)w ago', raw_text)
    if match:
        return int(match.group(1)) * 7
    if "Posted yesterday" in raw_text:
        return 1
    if "Posted today" in raw_text:
        return 0
    match = re.search(r'(\d+)d\+?\s+ago', raw_text.lower())
    if match:
        return int(match.group(1))
    return None


# =====================================================
# 主爬虫程序
# =====================================================

async def crawl_jobs(
    keywords: List[str],
    time_range: str = "7",
    max_jobs: int = 50,
    human_speed: float = 0.5,
    headless: bool = False,
):
    """
    爬取职位主函数

    Args:
        keywords: 关键词列表
        time_range: 时间范围 ("3", "7", "14", "30", "any")
        max_jobs: 最大爬取数量
        human_speed: 人类速度倍数
        headless: 是否无头模式
    """

    print("="*60)
    print("JobHunter - JD爬虫")
    print("="*60)

    # 解析时间参数
    if time_range == "any":
        max_days = 0
        posted_within = None
        time_label = "any time"
    else:
        max_days = int(time_range)
        posted_within = max_days
        time_label = f"{max_days} days"

    # 初始化数据库
    db = JDDatabase()
    initial_count = db.get_count()

    print(f"\n关键词: {', '.join(keywords)}")
    print(f"时间范围: {time_label}")
    print(f"最大数量: {max_jobs}")
    print(f"人类速度: {human_speed}x")
    print(f"数据库: {initial_count} JDs 已存在")
    print("\n开始爬取... (按 Ctrl+C 停止)\n")

    crawled_count = 0
    skipped_count = 0
    filtered_count = 0
    old_count = 0
    seen_urls = set()

    try:
        async with JobsDBScraper(
            headless=headless,
            human_speed=human_speed,
            browser_type="msedge"
        ) as scraper:

            # 遍历所有关键词
            for keyword in keywords:
                if crawled_count >= max_jobs:
                    break

                logger.info(f"搜索关键词: {keyword}")

                # 遍历多页
                for page in range(1, 11):  # 最多10页
                    if crawled_count >= max_jobs:
                        break

                    logger.info(f"搜索第 {page} 页: '{keyword}'")

                    # 搜索职位
                    jobs = await scraper.search_jobs(
                        keyword=keyword,
                        page=page,
                        posted_within=posted_within
                    )
                    logger.info(f"第 {page} 页找到 {len(jobs)} 个职位")

                    # 遍历搜索结果
                    for i, job in enumerate(jobs):
                        if crawled_count >= max_jobs:
                            break

                        raw_url = job.get("url", "")
                        if not raw_url:
                            continue

                        # 规范化 URL 去重
                        url = normalize_url(raw_url)

                        # 检查是否已经处理过
                        if url in seen_urls:
                            continue
                        if db.exists(url):
                            skipped_count += 1
                            logger.debug(f"  跳过重复: {url}")
                            continue

                        seen_urls.add(url)

                        title = job.get("title", "")
                        description = job.get("description", "")

                        try:
                            job_detail = await scraper.get_job_detail(raw_url)

                            # 从 raw_text 提取真实标题和日期
                            raw_text = job_detail.get("raw_text", "")
                            real_title = extract_title(raw_text)
                            if real_title:
                                title = real_title

                            days_old = extract_days_old(raw_text)

                            job_detail["title"] = title
                            job_detail["url"] = url
                            job_detail["company"] = extract_company(raw_text)
                            job_detail["crawled_at"] = datetime.now().isoformat()
                            job_detail["source"] = "jobsdb"
                            job_detail["search_keyword"] = keyword
                            job_detail["days_old"] = days_old

                            days_str = f"{days_old}d old" if days_old is not None else "unknown age"
                            logger.info(f"  [{crawled_count + 1}/{max_jobs}] {title[:50]} ({days_str})")

                            # 存入数据库
                            db.insert(job_detail)
                            crawled_count += 1

                        except Exception as e:
                            logger.error(f"  爬取失败 {url}: {e}")

            # 显示统计
            final_count = db.get_count()
            print(f"\n{'='*60}")
            print(f"完成！")
            print(f"  新增: {crawled_count}")
            print(f"  跳过重复: {skipped_count}")
            print(f"  数据库总数: {final_count}")
            print(f"{'='*60}")

            return {
                "crawled_count": crawled_count,
                "skipped_count": skipped_count,
                "old_count": old_count,
                "final_count": final_count,
            }

    except KeyboardInterrupt:
        print(f"\n\n用户停止爬取")
        print(f"数据库总数: {db.get_count()}")
        return {}

    except Exception as e:
        logger.exception(f"爬虫失败: {e}")
        return {}


def show_database():
    """显示数据库内容"""
    db = JDDatabase()
    jobs = db.get_all()

    print(f"\n数据库总 JD 数: {len(jobs)}")
    print("="*80)

    for i, job in enumerate(jobs, 1):
        print(f"{i}. {job.get('title', 'N/A')}")
        print(f"   公司: {job.get('company', 'N/A')}")
        print(f"   URL: {job.get('url', 'N/A')}")
        print(f"   来源: {job.get('source', 'N/A')}")
        print(f"   关键词: {job.get('search_keyword', 'N/A')}")
        print(f"   发布天数: {job.get('days_old', 'N/A')}")
        print(f"   爬取时间: {job.get('crawled_at', 'N/A')}")
        print("-"*80)


# =====================================================
# 程序入口
# =====================================================

def main():
    parser = argparse.ArgumentParser(
        description="JobHunter JD爬虫 - 一键爬取JobsDB职位",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python jd_crawler_main.py                                    # 使用默认关键词
  python jd_crawler_main.py --keywords "AI PM" "AI Engineer"  # 指定关键词
  python jd_crawler_main.py --time 3 --max-jobs 20            # 3天内，20个职位
  python jd_crawler_main.py --show                             # 仅显示数据库
  python jd_crawler_main.py --headless                         # 无头模式
        """
    )

    parser.add_argument(
        "--keywords",
        type=str,
        nargs="+",
        default=[
            "AI Product Manager",
            "AI PM",
            "Product Manager AI",
            "AI Product",
            "Artificial Intelligence",
            "Machine Learning",
            "AI Engineer",
            "Data Scientist",
        ],
        help="搜索关键词列表"
    )

    parser.add_argument(
        "--time",
        type=str,
        choices=["3", "7", "14", "30", "any"],
        default="7",
        help="发布时间范围 (默认: 7天)"
    )

    parser.add_argument(
        "--max-jobs",
        type=int,
        default=50,
        help="最大爬取数量 (默认: 50)"
    )

    parser.add_argument(
        "--speed",
        type=float,
        default=0.5,
        help="人类速度倍数，越小越慢越安全 (默认: 0.5)"
    )

    parser.add_argument(
        "--headless",
        action="store_true",
        help="无头模式（不显示浏览器）"
    )

    parser.add_argument(
        "--show",
        action="store_true",
        help="仅显示数据库内容，不爬取"
    )

    args = parser.parse_args()

    if args.show:
        show_database()
        return

    # 运行爬虫
    asyncio.run(crawl_jobs(
        keywords=args.keywords,
        time_range=args.time,
        max_jobs=args.max_jobs,
        human_speed=args.speed,
        headless=args.headless,
    ))


if __name__ == "__main__":
    main()
