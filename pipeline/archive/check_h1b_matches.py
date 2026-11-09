"""List each firm's H-1B tier with the USCIS entities it matched, so false matches are easy to spot."""
import json
import re
from pathlib import Path

root = Path(__file__).resolve().parents[2]
d = json.loads(re.sub(r"^window\.BOARD_DATA = |;$", "", (root / "site" / "data.js").read_text(encoding="utf-8")))
rows = [f for f in d["firms"] if f["h1b"]["tier"] != "None found"]
print(len(rows), "firms matched of", len(d["firms"]))
for f in sorted(rows, key=lambda f: -f["h1b"]["initial"]):
    print(f"{f['name'][:38]:<38} {f['h1b']['tier']:<10} {f['h1b']['initial']:>5}  <- {' | '.join(f['h1b']['matched'])[:90]}")
