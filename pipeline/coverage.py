"""Coverage report: which firms in the database have live roles on the board, and which don't (and why)."""
import json
import re
from collections import Counter
from pathlib import Path

root = Path(__file__).resolve().parent.parent
d = json.loads(re.sub(r"^window\.BOARD_DATA = |;$", "", (root / "site" / "data.js").read_text(encoding="utf-8")))
boards = json.loads((root / "data" / "boards.json").read_text(encoding="utf-8"))
custom = {k for k in json.loads((root / "data" / "custom_boards.json").read_text(encoding="utf-8")) if not k.startswith("_")}

roles_by_firm = Counter(j["company"] for j in d["jobs"] if j["group"] == "consulting")
firms = d["firms"]
live = [f for f in firms if roles_by_firm.get(f["name"])]
feed_no_match = [f for f in firms if not roles_by_firm.get(f["name"]) and (boards.get(f["name"]) or f["name"] in custom)]
no_feed = [f for f in firms if not roles_by_firm.get(f["name"]) and not boards.get(f["name"]) and f["name"] not in custom]

print(f"{len(firms)} firms | live roles: {len(live)} | feed found but no matching roles right now: {len(feed_no_match)} | no feed: {len(no_feed)}")
print("\nLive:", ", ".join(f"{f['name']} ({roles_by_firm[f['name']]})" for f in sorted(live, key=lambda f: -roles_by_firm[f['name']])))
print("\nFeed found, nothing matching:", ", ".join(f["name"] for f in feed_no_match))
big = [f for f in no_feed if (f["size_band"] or "")[:1] in "1234"]
print(f"\nNo feed, 5,000+ employees ({len(big)}):", ", ".join(f["name"] for f in big))
mid = [f for f in no_feed if (f["size_band"] or "")[:1] in "56"]
print(f"\nNo feed, 500-5,000 employees ({len(mid)}):", ", ".join(f["name"] for f in mid))
print(f"\nNo feed, under 500 employees: {sum(1 for f in no_feed if (f['size_band'] or '')[:1] in '78')}")
print("\nSchool-facilitated firms with no live roles:", ", ".join(f["name"] for f in firms if f["school_facilitated"] == "Yes" and not roles_by_firm.get(f["name"])))
