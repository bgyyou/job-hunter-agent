
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from pathlib import Path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from database.jd_db import JDDatabase

db = JDDatabase()
jobs = db.get_all()

if jobs:
    job = jobs[0]
    print("First job raw_text:")
    print("=" * 80)
    raw = job['raw_text']
    # Write to file instead
    with open("debug_raw.txt", "w", encoding="utf-8") as f:
        f.write(raw)
    print("Raw text written to debug_raw.txt")
    print("\n" + "=" * 80)
    print(f"\nTitle: {job['title']}")
    print(f"Company: {job['company']}")
