"""Where does the immigration-support wording match in real postings, and did it change any label?"""
import json
import sys
from collections import Counter
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from classify import classify, IMMIGRATION_SUPPORT, immigration_support

raw = json.loads((Path(__file__).resolve().parents[2] / "data" / "raw_fetch.json").read_text(encoding="utf-8"))
seen = set()
offers = declines = 0
for company, hit in raw.items():
    for j in (hit[2] if hit else []):
        t = classify(j, True) or classify(j, False)
        if not t:
            continue
        o, d = immigration_support(j.get("description") or "")
        if not (o or d) or (company, j["title"]) in seen:
            continue
        seen.add((company, j["title"]))
        offers += o and not d
        declines += d
        desc = j["description"]
        m = IMMIGRATION_SUPPORT.search(desc)
        print(f"{'OFFERS ' if o and not d else 'DECLINES'} {company[:22]:<22} | {j['title'][:34]:<34} | ...{desc[max(0, m.start() - 55): m.end() + 45]!r}")
print(f"\n{len(seen)} distinct role titles match (offers: {offers}, declines: {declines})")
