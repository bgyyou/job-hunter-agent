
import sys
from pathlib import Path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from database.jd_db import JDDatabase

db = JDDatabase()
jobs = db.get_all()

# 检查第一个职位
if jobs:
    job = jobs[0]
    print(f"Title: {job['title']}")
    print(f"Company: {job['company']}")
    print("=" * 80)
    with open("job_debug.txt", "w", encoding="utf-8") as f:
        f.write(job['raw_text'][:3000])
    print("Raw text written to job_debug.txt")
