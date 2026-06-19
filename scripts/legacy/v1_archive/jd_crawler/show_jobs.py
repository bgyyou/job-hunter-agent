"""
显示数据库中的职位标题和公司名
"""
import sys
from pathlib import Path

# 添加项目根目录
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(Path(__file__).parent))

from database.jd_db import JDDatabase

db = JDDatabase()
jobs = db.get_all()

print("=" * 80)
print(f"数据库中共有 {len(jobs)} 个职位")
print("=" * 80)
print()

for i, job in enumerate(jobs, 1):
    title = job.get("title", "N/A")
    company = job.get("company", "N/A")
    url = job.get("url", "")
    days_old = job.get("days_old", "N/A")
    search_keyword = job.get("search_keyword", "")

    days_str = f"{days_old}d" if days_old is not None else "N/A"

    print(f"{i}. [{days_str}] {title}")
    print(f"   公司: {company}")
    if search_keyword:
        print(f"   关键词: {search_keyword}")
    print(f"   链接: {url}")
    print()

print("=" * 80)
