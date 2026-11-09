"""How many roles have a huge number of locations, and which companies do they belong to?"""
import json
import re
from collections import Counter
from pathlib import Path

root = Path(__file__).resolve().parents[2]
d = json.loads(re.sub(r"^window\.BOARD_DATA = |;$", "", (root / "public" / "data.js").read_text(encoding="utf-8")))
jobs = d["jobs"]
big = [j for j in jobs if j["n_locations"] > 15]
print(f"{len(jobs)} roles; {len(big)} have more than 15 locations")
print("by company:", Counter(j["company"] for j in big).most_common())
print("\nthe top of the default list (newest first, which is what visitors see first):")
shown = [j for j in sorted(jobs, key=lambda j: j["posted"] or "", reverse=True) if not j["review"] and j["seniority"] != "Entry-level" and j["visa"] != "Unlikely"][:10]
for j in shown:
    print(f"  {j['company'][:22]:<22} | {j['title'][:62]:<62} | {j['n_locations']:>3} loc | {j['category'][:14]}")
