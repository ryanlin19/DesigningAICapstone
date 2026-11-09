"""Check the new firm-specific boards: visa labels, Kearney roles, and a sample of the other firms."""
import json
import random
import re
from collections import Counter
from pathlib import Path

root = Path(__file__).resolve().parents[2]
d = json.loads(re.sub(r"^window\.BOARD_DATA = |;$", "", (root / "site" / "data.js").read_text(encoding="utf-8")))
jobs = d["jobs"]
print("roles:", len(jobs))
unl = [j for j in jobs if j["visa"] == "Unlikely"]
print("Unlikely by company:", Counter(j["company"] for j in unl).most_common(8))
print("Unlikely reasons:", Counter(r for j in unl for r in j["visa_reasons"]).most_common(4))
print("\nKearney roles:")
for j in jobs:
    if j["company"] == "Kearney":
        print(f"  {j['title'][:62]:<62} | {j['n_locations']} loc | {j['seniority']:<13} | visa={j['visa']} | {j['posted']}")
random.seed(5)
for firm in ["Accenture", "Booz Allen Hamilton", "Protiviti", "Huron Consulting Group"]:
    js = [j for j in jobs if j["company"] == firm]
    print(f"\n{firm}: {len(js)} roles; sample:")
    for j in random.sample(js, min(5, len(js))):
        print(f"  {j['title'][:60]:<60} | {j['location'][:28]:<28} | {j['category'][:12]:<12} | {j['seniority']}")
