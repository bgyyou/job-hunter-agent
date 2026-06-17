
import sys
from pathlib import Path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from database.jd_db import JDDatabase

db = JDDatabase()
jobs = db.get_all()

print(f"Total jobs in DB: {len(jobs)}")
print("=" * 80)

for i, job in enumerate(jobs, 1):
    print(f"{i}. {job['title']}")
    print(f"   Company: {job['company']}")
    print(f"   URL: {job['url']}")
    print(f"   Source: {job['source']}")
    print(f"   Keyword: {job['search_keyword']}")
    print(f"   Crawled: {job['crawled_at']}")
    print("-" * 80)
