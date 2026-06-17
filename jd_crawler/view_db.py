
import sys
from pathlib import Path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from database.jd_db import JDDatabase

db = JDDatabase()
jobs = db.get_all()

output_file = "db_output.txt"
with open(output_file, "w", encoding="utf-8") as f:
    f.write(f"Total jobs in DB: {len(jobs)}\n")
    f.write("=" * 80 + "\n")

    for i, job in enumerate(jobs, 1):
        f.write(f"\nJob #{i}\n")
        f.write(f"Title: {job['title']}\n")
        f.write(f"Company: {job['company']}\n")
        f.write(f"URL: {job['url']}\n")
        f.write(f"Source: {job['source']}\n")
        f.write(f"Keyword: {job['search_keyword']}\n")
        f.write(f"Crawled: {job['crawled_at']}\n")
        f.write("-" * 80 + "\n")
        f.write("Description:\n")
        f.write(job['raw_text'][:5000])
        f.write("\n" + "=" * 80 + "\n")

print(f"Output written to {output_file}")
