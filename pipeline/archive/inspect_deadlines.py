"""How did the deadline reader do, and did the location/Epic fixes work?"""
import datetime
import json
import re
from collections import Counter
from pathlib import Path

root = Path(__file__).resolve().parents[2]
d = json.loads(re.sub(r"^window\.BOARD_DATA = |;$", "", (root / "public" / "data.js").read_text(encoding="utf-8")))
jobs = d["jobs"]
today = datetime.date.today()
print(f"{len(jobs)} roles")
print("deadline kinds:", dict(Counter(j["deadline"]["kind"] for j in jobs)))
dated = [j for j in jobs if j["deadline"]["kind"] == "date"]
print(f"  dated: {len(dated)}; already passed: {sum(1 for j in dated if j['deadline']['date'] < today.isoformat())}")
print("\nroles with a date (check these against the posting text):")
for j in sorted(dated, key=lambda j: j["deadline"]["date"])[:14]:
    print(f"  {j['deadline']['date']} | {j['company'][:20]:<20} | {j['title'][:60]}")
print("\nby company, non-unknown deadlines:", Counter(j["company"] for j in jobs if j["deadline"]["kind"] != "unknown").most_common(8))
big = [j for j in jobs if j["n_locations"] > 15]
print(f"\nroles with >15 locations: {len(big)}; stored location entries per role: {sorted({len(j['locations']) for j in big})}")
print("Huron/Epic/billing/supervisor titles still present:", [j["title"] for j in jobs if re.search(r"epic|hospital|billing|supervisor", j["title"], re.I)])
print("public/data.js size:", (root / "public" / "data.js").stat().st_size, "bytes")
