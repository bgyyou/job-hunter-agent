
import sqlite3
from pathlib import Path

db_path = Path.home() / ".job_hunter" / "crawler.db"
print(f"Database path: {db_path}\n")

with sqlite3.connect(str(db_path)) as conn:
    # 表结构
    cursor = conn.execute("PRAGMA table_info(crawled_jds)")
    print("Table schema:")
    for row in cursor:
        print(f"  {row[1]} ({row[2]}) - {'PK' if row[5] else ''}")

    # 行数
    cursor = conn.execute("SELECT COUNT(*) FROM crawled_jds")
    count = cursor.fetchone()[0]
    print(f"\nTotal records: {count}")

    # 预览一条记录
    cursor = conn.execute("SELECT * FROM crawled_jds LIMIT 1")
    row = cursor.fetchone()
    if row:
        print("\nSample record:")
        columns = [desc[0] for desc in cursor.description]
        for col, val in zip(columns, row):
            val_str = str(val)[:50] + "..." if len(str(val)) > 50 else str(val)
            print(f"  {col}: {val_str}")
