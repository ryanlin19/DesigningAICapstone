"""Checks for the location normalizer, using real strings from the job data."""
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parent))
from places import labels, REMOTE_LABEL

NYC, SF, DC, CHI = "New York City area", "San Francisco Bay Area", "Washington, DC area", "Chicago"
cases = [
    ("Chicago - 550 Van Buren", [CHI]), ("CHICAGO", [CHI]), ("Chicago, IL", [CHI]), ("Chicago, Accenture Tower, Corp", [CHI]),
    ("New York", [NYC]), ("NEW YORK CITY", [NYC]), ("New York City, NY", [NYC]), ("New York, NY, United States", [NYC]),
    ("New York - 1166 Ave of Americas", [NYC]), ("New York, One Manhattan West, Corp", [NYC]), ("NYC Office", [NYC]),
    ("New York, USA", [NYC]), ("New York - New York City", [NYC]),
    ("San Francisco", [SF]), ("San Francisco, CA", [SF]), ("San Francisco, California", [SF]), ("South San Francisco HQ", [SF]),
    ("Washington, DC", [DC]), ("Washington DC", [DC]), ("Washington, D.C.", [DC]), ("McLean, VA", [DC]), ("Arlington, VA", [DC]),
    ("Springfield, VA", [DC]), ("Chantilly, VA", [DC]),
    ("Remote", [REMOTE_LABEL]), ("Remote - US", [REMOTE_LABEL]), ("United States", [REMOTE_LABEL]), ("US-Remote", [REMOTE_LABEL]),
    ("Virtual-SC", [REMOTE_LABEL]),
    ("Hybrid - San Francisco, California", [SF]), ("Remote - SF Bay Area", [SF, REMOTE_LABEL]),
    ("San Francisco or Seattle", [SF, "Seattle area"]),
    ("Bellevue, Washington", ["Seattle area"]), ("Seattle, WA", ["Seattle area"]),
    ("Pennsylvania-Philadelphia", ["Philadelphia"]), ("Southfield", ["Detroit area"]), ("TAMPA", ["Tampa"]),
    ("ATLANTA - PEACHTREE RD", ["Atlanta"]), ("DALLAS", ["Dallas-Fort Worth"]), ("Dallas, Texas", ["Dallas-Fort Worth"]),
    ("Boston - 225 Franklin St", ["Boston area"]), ("Salt Lake City, Utah, United States", ["Salt Lake City"]),
    ("Texas, USA", ["Texas (statewide)"]), ("Illinois, USA", ["Illinois (statewide)"]),
    ("CHI Office", [CHI]), ("San Fransisco", [SF]), ("Ft Lauderdale", ["Miami area"]), ("West Coast", []),
    ("KS - Overland Park", ["Overland Park"]), ("IA - Des Moines", ["Des Moines"]), ("NJ-Morristown", ["Morristown"]),
    ("CA", ["California (statewide)"]), ("IN", ["Indiana (statewide)"]), ("NY - New York", [NYC]), ("DC - Washington", [DC]),
    ("Walnut Creek, CA", [SF]), ("Hillsboro – 1915 NE Stucki", ["Portland"]), ("Sacramento, 1610 R Street, Corp", ["Sacramento"]),
    ("Hybrid", []), ("", []),
]
bad = 0
for text, want in cases:
    got = labels(text)
    ok = got == want
    bad += not ok
    if not ok:
        print(f"FAIL  {text!r:<45} -> {got}  (wanted {want})")
print(f"{len(cases) - bad}/{len(cases)} cases ok")

# real data: how clean is the result?
root = Path(__file__).resolve().parent.parent
d = json.loads(re.sub(r"^window\.BOARD_DATA = |;$", "", (root / "public" / "data.js").read_text(encoding="utf-8")))
c, unplaced = Counter(), 0
for j in d["jobs"]:
    names = {e["name"] for e in j["locations"]}
    labs = {lab for n in names for lab in labels(n)}
    unplaced += not labs
    for lab in labs:
        c[lab] += 1
print(f"\n{len(c)} places across {len(d['jobs'])} roles; roles with no place: {unplaced}")
print("places:", ", ".join(f"{k} ({v})" for k, v in sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))))
sys.exit(1 if bad else 0)
