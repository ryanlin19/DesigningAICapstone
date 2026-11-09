"""What do the raw location strings look like? Used to design the location filter."""
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
root = Path(__file__).resolve().parents[2]
d = json.loads(re.sub(r"^window\.BOARD_DATA = |;$", "", (root / "public" / "data.js").read_text(encoding="utf-8")))
names = Counter()
for j in d["jobs"]:
    for n in {e["name"] for e in j["locations"]}:
        names[n] += 1
print(f"{len(d['jobs'])} roles, {len(names)} distinct location strings")
print("\nmost common:")
for n, c in names.most_common(45):
    print(f"  {c:>3}  {n}")
print("\nlong tail sample:")
for n, c in list(names.items())[::9][:45]:
    print(f"  {c:>3}  {n}")
