"""
JD Crawler Database - SQLite
"""
import sqlite3
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict


class JDDatabase:
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
                    crawled_at TEXT,
                    is_analyzed INTEGER DEFAULT 0
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_url ON crawled_jds(url)")

            # 如果是旧数据库，添加新字段
            try:
                conn.execute("ALTER TABLE crawled_jds ADD COLUMN search_keyword TEXT")
            except sqlite3.OperationalError:
                # 字段已存在，忽略
                pass

    def exists(self, url: str) -> bool:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT 1 FROM crawled_jds WHERE url = ?", (url,))
            return cursor.fetchone() is not None

    def insert(self, job: Dict) -> int:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                INSERT OR IGNORE INTO crawled_jds
                (url, title, company, raw_text, location, salary, source, search_keyword, crawled_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                job.get("url"),
                job.get("title"),
                job.get("company"),
                job.get("raw_text"),
                job.get("location"),
                job.get("salary"),
                job.get("source", "jobsdb"),
                job.get("search_keyword"),
                job.get("crawled_at", datetime.now().isoformat()),
            ))
            return cursor.lastrowid

    def get_all(self) -> List[Dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("SELECT * FROM crawled_jds ORDER BY crawled_at DESC")
            return [dict(row) for row in cursor.fetchall()]

    def get_count(self) -> int:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM crawled_jds")
            return cursor.fetchone()[0]
