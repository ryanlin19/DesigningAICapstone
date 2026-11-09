"""Quick look at the built data: why are jobs flagged for review, and what do they look like?"""
import json
import random
import re
from collections import Counter
from pathlib import Path

root = Path(__file__).resolve().parents[2]
d = json.loads(re.sub(r"^window\.BOARD_DATA = |;$", "", (root / "site" / "data.js").read_text(encoding="utf-8")))
jobs = d["jobs"]
print("stats:", d["stats"])
rev = [j for j in jobs if j["review"]]
print("review:", len(rev), "of", len(jobs))
print("review by group/category:", Counter((j["group"], j["category"]) for j in rev).most_common(12))
print("confident by group:", Counter(j["group"] for j in jobs if not j["review"]))
random.seed(3)
print("\n-- random review-flagged --")
for j in random.sample(rev, 18):
    print(f"{j['company'][:16]:<16}|{j['title'][:58]:<58}|{j['category'][:12]:<12}|{j['location'][:28]}")
print("\n-- 12 confident at consulting firms --")
cc = [j for j in jobs if not j["review"] and j["group"] == "consulting"]
for j in random.sample(cc, min(12, len(cc))):
    print(f"{j['company'][:16]:<16}|{j['title'][:58]:<58}|{j['category'][:12]:<12}|{j['location'][:28]}")
print("\nFirms w/ open roles:", Counter(f["name"] for f in d["firms"] if f["open_roles"]).most_common(3), sum(1 for f in d["firms"] if f["open_roles"]))
print("H-1B tiers (firms):", Counter(f["h1b"]["tier"] for f in d["firms"]))
