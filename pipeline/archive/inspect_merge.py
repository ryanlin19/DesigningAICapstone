"""Check the multi-location merge in the built data."""
import json
import re
from collections import Counter
from pathlib import Path

root = Path(__file__).resolve().parents[2]
d = json.loads(re.sub(r"^window\.BOARD_DATA = |;$", "", (root / "site" / "data.js").read_text(encoding="utf-8")))
jobs = d["jobs"]
print("roles:", len(jobs))
print("location counts:", dict(sorted(Counter(j["n_locations"] for j in jobs).items())))
multi = [j for j in jobs if j["n_locations"] > 1]
print("multi-location roles:", len(multi))
sep_urls = [j for j in multi if len({e["url"] for e in j["locations"]}) > 1]
print("  of which have a different apply link per location:", len(sep_urls))
print("  roles where salary varies by location:", sum(j["salary_varies"] for j in jobs))
print("\nTwitch roles:")
for j in jobs:
    if j["company"].lower() == "twitch":
        print(" ", j["title"], "|", [e["name"] for e in j["locations"]], "| urls:", len({e["url"] for e in j["locations"]}))
print("\nExamples of merged roles with separate links:")
for j in sep_urls[:6]:
    print(f"  {j['company']} | {j['title'][:50]} | {[e['name'][:22] for e in j['locations']]}")
