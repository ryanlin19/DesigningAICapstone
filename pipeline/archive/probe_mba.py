"""How often do postings say MBA, and in what wording? Used to design the MBA tag."""
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from classify import classify

root = Path(__file__).resolve().parents[2]
raw = json.loads((root / "data" / "raw_fetch.json").read_text(encoding="utf-8"))

MBA = r"(?:\bMBA\b|master(?:'s|s)? of business administration|master(?:'s|s)? in business administration)"
TITLE = re.compile(MBA, re.I)
# wording that says an MBA is wanted, as opposed to a passing mention
WANTED = re.compile(
    rf"{MBA}[^.\n]{{0,60}}(?:prefer|required|desired|a plus|strongly|beneficial|advantage|or equivalent|highly)|"
    rf"(?:prefer|required|desired|pursuing|completing|currently|candidates?|students?|graduat\w+|holding|possess|with an?)[^.\n]{{0,50}}{MBA}|"
    rf"{MBA}\s+(?:degree|candidate|graduate|student|program|intern|recruit)|"
    rf"\b(?:an?|the)\s+{MBA}\b", re.I)

rows = []
for name, hit in raw.items():
    if not hit:
        continue
    consulting = False  # irrelevant for wording stats
    for j in hit[2]:
        tags = classify(j, True) or classify(j, False)
        if not tags:
            continue
        desc = j.get("description") or ""
        in_title = bool(TITLE.search(j["title"]))
        m = WANTED.search(desc)
        any_mention = bool(TITLE.search(desc))
        rows.append((name, j["title"], in_title, m.group(0) if m else None, any_mention))

print(f"{len(rows)} roles pass the role filter (before merging locations)")
print("MBA in title:", sum(r[2] for r in rows))
print("MBA wanted/preferred wording in description:", sum(1 for r in rows if r[3]))
print("any mention of MBA at all:", sum(r[4] for r in rows))
print("title OR wanted wording:", sum(1 for r in rows if r[2] or r[3]))
print("\nsample 'wanted' phrases:")
for r in [r for r in rows if r[3]][:25]:
    print(f"  {r[0][:18]:<18} | {r[1][:42]:<42} | {r[3][:90]!r}")
print("\nmentions that did NOT count as wanted (to see what we'd skip):")
skipped = [r for r in rows if r[4] and not r[3]][:8]
raw_lookup = {}
for name, hit in raw.items():
    for j in (hit[2] if hit else []):
        raw_lookup[(name, j["title"])] = j.get("description") or ""
for r in skipped:
    d = raw_lookup[(r[0], r[1])]
    m = TITLE.search(d)
    print(f"  {r[0][:18]:<18} | {r[1][:40]:<40} | ...{d[max(0, m.start() - 70):m.end() + 50]!r}")
print("\nby company, title OR wanted:", Counter(r[0] for r in rows if r[2] or r[3]).most_common(10))
