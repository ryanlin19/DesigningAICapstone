"""Unit checks for the MBA tag, then a look at how it does on real postings."""
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parent))
from classify import classify, mba_kind, MBA_RE

cases = [
    ("MBA Consultant - Semiconductors", "", "title"),
    ("Associate", "Master of Business Administration (MBA) preferred.", "preferred"),
    ("Associate", "MBA degree preferred", "preferred"),
    ("Manager", "Bachelor's degree required; MBA preferred", "preferred"),
    ("Manager", "An MBA is required for this position.", "required"),
    ("Manager", "MBA or equivalent graduate degree", "preferred"),
    ("Manager", "You are currently pursuing an MBA and graduating in 2027", "preferred"),
    ("Manager", "We are looking for MBA candidates with strategy experience", "preferred"),
    ("Manager", "Advanced degree preferred (e.g., MBA, MHA, MPH)", None),
    ("Manager", "Master's degree (MBA, MPP, MPA, or equivalent)", None),
    ("Manager", "Our team includes alumni of top MBA programs and engineers", None),
    ("Manager", "Bonus Points If: You have a CPA, CMA, ACCA, MBA, or equivalent accounting/finance credential.", None),
    ("Manager", "", None),
    ("Senior Strategy Manager", "5+ years of experience in consulting or strategy", None),
]
bad = 0
for title, desc, want in cases:
    got = mba_kind(title, desc)
    ok = got == want
    bad += not ok
    print(("ok   " if ok else "FAIL ") + f"{title[:30]:<30} | {desc[:62]:<62} -> {got}" + ("" if ok else f"  (wanted {want})"))
print("ALL PASSED\n" if not bad else f"{bad} FAILED\n")

raw = json.loads((Path(__file__).resolve().parent.parent / "data" / "raw_fetch.json").read_text(encoding="utf-8"))
rows = []
for name, hit in raw.items():
    for j in (hit[2] if hit else []):
        t = classify(j, True) or classify(j, False)
        if t:
            rows.append((name, j, t["mba_kind"]))
print("real postings that pass the role filter:", len(rows), "| kinds:", dict(Counter(r[2] for r in rows)))
for kind in ("title", "required", "preferred"):
    print(f"\n--- sample '{kind}' (company | title | text around MBA) ---")
    seen = set()
    for name, j, k in rows:
        if k != kind or (name, j["title"]) in seen:
            continue
        seen.add((name, j["title"]))
        d = j.get("description") or ""
        m = MBA_RE.search(d)
        ctx = d[max(0, m.start() - 45): m.end() + 55].replace("\n", " ") if m else ""
        print(f"  {name[:16]:<16} | {j['title'][:36]:<36} | ...{ctx}")
        if len(seen) >= 9:
            break
sys.exit(1 if bad else 0)
