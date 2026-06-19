
import sys
from pathlib import Path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from database.jd_db import JDDatabase

db = JDDatabase()
jobs = db.get_all()

print(f"Total jobs in DB: {len(jobs)}")
print("=" * 80)

for i, job in enumerate(jobs[:5], 1):  # 查看前5个
    has_raw_text = bool(job.get('raw_text'))
    raw_text_length = len(job['raw_text']) if has_raw_text else 0
    print(f"\n{i}. {job['title']}")
    print(f"   Company: {job['company']}")
    print(f"   Has JD: {'YES' if has_raw_text else 'NO'}")
    print(f"   JD length: {raw_text_length} characters")

print("\n" + "=" * 80)
print("\nChecking if all jobs have descriptions...")
jobs_with_jd = sum(1 for job in jobs if job.get('raw_text'))
print(f"Jobs with full JD: {jobs_with_jd} / {len(jobs)}")

