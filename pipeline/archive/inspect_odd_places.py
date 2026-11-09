"""Which raw location strings produce the odd-looking place labels?"""
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from places import labels

root = Path(__file__).resolve().parents[2]
d = json.loads(re.sub(r"^window\.BOARD_DATA = |;$", "", (root / "public" / "data.js").read_text(encoding="utf-8")))
src = defaultdict(set)
for j in d["jobs"]:
    for e in j["locations"]:
        for lab in labels(e["name"]):
            src[lab].add((e["name"], j["company"]))
odd = ["Ca", "Ia", "In", "Ks", "Nj", "Ny", "Ok", "Or", "Va", "Wi", "Arlington", "Aurora", "Carmel", "Albany", "Morristown",
       "Sacramento", "Overland Park", "Des Moines", "Bentonville", "Walnut Creek", "Hillsboro – 1915 NE Stucki", "Beaverton",
       "Aberdeen Proving Ground", "Shaw AFB", "Huntsville"]
for lab in odd:
    rows = sorted(src.get(lab, []))[:3]
    print(f"{lab!r:<32} <- {rows}")
