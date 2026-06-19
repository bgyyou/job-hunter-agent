
import sqlite3
from pathlib import Path

db_path = Path.home() / ".job_hunter" / "crawler.db"

conn = sqlite3.connect(db_path)
conn.execute("DELETE FROM crawled_jds")
conn.commit()
conn.close()

print("Database cleared!")
