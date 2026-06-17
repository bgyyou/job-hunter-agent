"""
Job Database - 职位数据存储模块

功能：
- SQLite 存储职位数据
- 去重
- 查询和统计
"""
import sqlite3
import re
from typing import Dict, List, Optional
from datetime import datetime
from pathlib import Path
from loguru import logger


class JobDatabase:
    """职位数据库"""

    def __init__(self, db_path: Optional[Path] = None):
        """
        初始化数据库

        Args:
            db_path: 数据库文件路径，默认为 ~/.job_hunter/crawler.db
        """
        if db_path is None:
            db_path = Path.home() / ".job_hunter" / "crawler.db"

        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db_path = str(db_path)
        self._init_db()

    def _init_db(self):
        """初始化数据库表"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS crawled_jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    url TEXT UNIQUE NOT NULL,
                    title TEXT,
                    company TEXT,
                    raw_text TEXT,
                    location TEXT,
                    salary_str TEXT,
                    salary_min INTEGER,
                    salary_max INTEGER,
                    source TEXT DEFAULT 'jobsdb',
                    search_keyword TEXT,
                    days_old INTEGER,
                    crawled_at TEXT,
                    is_analyzed INTEGER DEFAULT 0,
                    platform TEXT DEFAULT 'jobsdb',
                    job_id TEXT
                )
            """)

            conn.execute("CREATE INDEX IF NOT EXISTS idx_url ON crawled_jobs(url)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_platform ON crawled_jobs(platform)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_crawled_at ON crawled_jobs(crawled_at)")

            # 添加缺失的列（数据库迁移）
            self._add_column_if_missing(conn, "search_keyword", "TEXT")
            self._add_column_if_missing(conn, "days_old", "INTEGER")
            self._add_column_if_missing(conn, "platform", "TEXT")
            self._add_column_if_missing(conn, "job_id", "TEXT")
            self._add_column_if_missing(conn, "salary_str", "TEXT")
            self._add_column_if_missing(conn, "salary_min", "INTEGER")
            self._add_column_if_missing(conn, "salary_max", "INTEGER")

    def _add_column_if_missing(self, conn, column_name: str, column_type: str):
        """添加列（如果不存在）"""
        try:
            cursor = conn.execute("PRAGMA table_info(crawled_jobs)")
            columns = [row[1] for row in cursor.fetchall()]
            if column_name not in columns:
                conn.execute(f"ALTER TABLE crawled_jobs ADD COLUMN {column_name} {column_type}")
                conn.commit()
                logger.info(f"添加列成功: {column_name}")
        except Exception as e:
            pass

    def normalize_url(self, url: str) -> str:
        """规范化 URL：只保留 /job/XXXXX 部分，去掉查询参数"""
        match = re.search(r"(https?://[^/]+/job/\d+)", url)
        if match:
            return match.group(1)
        return url.split('?')[0].split('#')[0]

    def exists(self, url: str) -> bool:
        """
        检查 URL 是否已存在

        Args:
            url: 职位 URL

        Returns:
            是否存在
        """
        normalized_url = self.normalize_url(url)
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT 1 FROM crawled_jobs WHERE url = ?", (normalized_url,))
            return cursor.fetchone() is not None

    def insert(self, job: Dict) -> int:
        """
        插入新职位

        Args:
            job: 职位字典

        Returns:
            插入的 ID
        """
        url = self.normalize_url(job.get("url", ""))

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                INSERT OR IGNORE INTO crawled_jobs
                (url, title, company, raw_text, location, salary_str, salary_min, salary_max,
                 source, search_keyword, days_old, crawled_at, platform, job_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                url,
                job.get("title", ""),
                job.get("company", ""),
                job.get("raw_text", job.get("description", "")),
                job.get("location", ""),
                job.get("salary_str", ""),
                job.get("salary_min"),
                job.get("salary_max"),
                job.get("source", "jobsdb"),
                job.get("search_keyword", ""),
                job.get("days_old"),
                job.get("crawled_at", datetime.now().isoformat()),
                job.get("platform", "jobsdb"),
                job.get("job_id", "")
            ))

            if cursor.lastrowid:
                logger.debug(f"插入职位: {job.get('title', '')}")
            else:
                logger.debug(f"跳过重复职位: {url}")

            return cursor.lastrowid

    def batch_insert(self, jobs: List[Dict]) -> int:
        """
        批量插入职位

        Args:
            jobs: 职位列表

        Returns:
            成功插入的数量
        """
        count = 0
        for job in jobs:
            if self.insert(job):
                count += 1
        return count

    def get_all(self, platform: Optional[str] = None, limit: Optional[int] = None) -> List[Dict]:
        """
        获取所有职位

        Args:
            platform: 过滤平台
            limit: 限制返回数量

        Returns:
            职位列表
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row

            query = "SELECT * FROM crawled_jobs"
            params = []

            if platform:
                query += " WHERE platform = ?"
                params.append(platform)

            query += " ORDER BY crawled_at DESC"

            if limit:
                query += " LIMIT ?"
                params.append(limit)

            cursor = conn.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def get_count(self, platform: Optional[str] = None) -> int:
        """
        获取职位总数

        Args:
            platform: 过滤平台

        Returns:
            职位数量
        """
        with sqlite3.connect(self.db_path) as conn:
            if platform:
                cursor = conn.execute("SELECT COUNT(*) FROM crawled_jobs WHERE platform = ?", (platform,))
            else:
                cursor = conn.execute("SELECT COUNT(*) FROM crawled_jobs")
            return cursor.fetchone()[0]

    def get_recent(self, days: int = 7, limit: int = 100) -> List[Dict]:
        """
        获取最近的职位

        Args:
            days: 最近天数
            limit: 限制数量

        Returns:
            职位列表
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("""
                SELECT * FROM crawled_jobs
                WHERE days_old <= ? OR days_old IS NULL
                ORDER BY crawled_at DESC
                LIMIT ?
            """, (days, limit))
            return [dict(row) for row in cursor.fetchall()]

    def get_stats(self) -> Dict:
        """
        获取统计信息

        Returns:
            统计字典
        """
        with sqlite3.connect(self.db_path) as conn:
            stats = {}

            # 总数
            cursor = conn.execute("SELECT COUNT(*) FROM crawled_jobs")
            stats["total"] = cursor.fetchone()[0]

            # 按平台统计
            cursor = conn.execute("""
                SELECT platform, COUNT(*) as count
                FROM crawled_jobs
                GROUP BY platform
            """)
            stats["by_platform"] = {row[0]: row[1] for row in cursor.fetchall()}

            # 薪资统计
            cursor = conn.execute("""
                SELECT AVG(salary_min), AVG(salary_max), COUNT(*)
                FROM crawled_jobs
                WHERE salary_min IS NOT NULL AND salary_max IS NOT NULL
            """)
            avg_min, avg_max, count = cursor.fetchone()
            stats["salary"] = {
                "avg_min": avg_min,
                "avg_max": avg_max,
                "count": count
            }

            return stats

    def delete_old(self, days: int = 90) -> int:
        """
        删除旧职位

        Args:
            days: 删除多少天前的

        Returns:
            删除的数量
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                DELETE FROM crawled_jobs
                WHERE julianday('now') - julianday(crawled_at) > ?
            """, (days,))
            conn.commit()
            return cursor.rowcount

