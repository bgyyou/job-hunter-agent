import sqlite3
from pathlib import Path

db_path = Path.home() / ".job_hunter" / "crawler.db"

with sqlite3.connect(str(db_path)) as conn:
    # 检查现有列
    cursor = conn.execute("PRAGMA table_info(crawled_jds)")
    columns = [row[1] for row in cursor.fetchall()]
    print(f"现有列: {columns}")

    # 添加缺失的列
    if "days_old" not in columns:
        try:
            conn.execute("ALTER TABLE crawled_jds ADD COLUMN days_old INTEGER")
            conn.commit()
            print("添加列 days_old 成功")
        except Exception as e:
            print(f"添加 days_old 失败: {e}")

    if "search_keyword" not in columns:
        try:
            conn.execute("ALTER TABLE crawled_jds ADD COLUMN search_keyword TEXT")
            conn.commit()
            print("添加列 search_keyword 成功")
        except Exception as e:
            print(f"添加 search_keyword 失败: {e}")

    # 验证结果
    cursor = conn.execute("PRAGMA table_info(crawled_jds)")
    columns = [row[1] for row in cursor.fetchall()]
    print(f"更新后列: {columns}")
