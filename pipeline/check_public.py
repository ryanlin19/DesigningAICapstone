"""Safety check for the public build: nothing from the confidential firm database may be in public/.

Exits non-zero (and prints what leaked) if any of the checks fail. Run before every upload:
    python pipeline/check_public.py
"""
import json
import re
import sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent
pub = root / "public"
failures = []

text = (pub / "data.js").read_text(encoding="utf-8")
data = json.loads(re.sub(r"^window\.BOARD_DATA = |;$", "", text))

if data.get("firms"):
    failures.append(f"public data contains a firm directory ({len(data['firms'])} firms)")
if not data.get("public"):
    failures.append("public flag is not set")

# Firm-database fields, checked as data keys anywhere in the JSON (plain words like "offices" appear in job
# descriptions, so only a quoted key counts), plus phrases that only exist because of the database.
FORBIDDEN_KEYS = ["visa_stance", "school_facilitated", "size_band", "industries", "functions", "offices", "last_modified",
                   "careers_url", "open_roles", "h1b", "matched"]
FORBIDDEN_PHRASES = ["DO NOT SHARE", "Firm says", "Firm sponsors case by case", "School-facilitated"]


def keys_in(node):
    if isinstance(node, dict):
        for k, v in node.items():
            yield k
            yield from keys_in(v)
    elif isinstance(node, list):
        for v in node:
            yield from keys_in(v)


present = set(keys_in(data))
for k in FORBIDDEN_KEYS:
    if k in present:
        failures.append(f"firm-database field '{k}' found as a data key in public/data.js")
for phrase in FORBIDDEN_PHRASES:
    if phrase in text:
        failures.append(f"'{phrase}' found in public/data.js")
# The page source must not carry data, and must not mention the firm database at all (a visitor can View Source).
html = (pub / "index.html").read_text(encoding="utf-8")
if "window.BOARD_DATA = {" in html:
    failures.append("public/index.html has data embedded in it")
for word in ["School-facilitated", "school_facilitated", "database", "stance", "8-31-2026", "stated policy", "PRIVATE", "firmTable", "tab-firms", "visa_stance",
             "USCIS", "H-1B"]:
    if word in html:
        failures.append(f"'{word}' found in the public page source")

# The visa label may be informed by the firm database, but the reasons shown on the page may only be public-source
# evidence or the generic wording below. Anything else (especially text naming the firm's own policy) fails.
allowed = re.compile(r"^(Posting says no sponsorship|Posting mentions sponsorship|Requires U\.S\. citizenship or a security clearance|"
                     r"No sponsorship info found|Sponsorship unlikely based on available information|Sponsorship signals found|"
                     r"Posting mentions immigration support|Sponsorship may be considered on a case-by-case basis)$")
allowed_labels = {"Likely", "Case-by-case", "Unlikely", "Unknown"}
wrong_labels = {j["visa"] for j in data["jobs"]} - allowed_labels
if wrong_labels:
    failures.append(f"unexpected visa labels: {sorted(wrong_labels)}")
bad = {r for j in data["jobs"] for r in j.get("visa_reasons", []) if not allowed.match(r)}
if bad:
    failures.append(f"unexpected visa reasons: {sorted(bad)}")

# No firm-database values (e.g. size bands like '6. 500 - 2000') leaked into job records.
firms = json.loads((root / "data" / "firms.json").read_text(encoding="utf-8"))
sizes = {f["size_band"] for f in firms if f["size_band"]}
for s in sizes:
    if s in text:
        failures.append(f"firm size band '{s}' found in public data")

files = sorted(p.name for p in pub.iterdir())
print("public/ contains:", files)
print(f"{len(data['jobs'])} roles, {data['stats']['companies_with_board']} companies with a feed")
if failures:
    print("\nFAILED:")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print("OK: no firm-database content found in the public build")
