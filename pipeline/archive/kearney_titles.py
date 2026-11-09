"""List all of Kearney's titles in the Americas (no title filter) to see what the rules are missing."""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ats
from classify import classify, US_STRONG

cfg = json.loads((Path(__file__).resolve().parents[2] / "data" / "custom_boards.json").read_text(encoding="utf-8"))["Kearney"]
jobs = ats.fetch_recsolu(cfg, want=None) if "--details" in sys.argv else None
# list-only pass: reuse the reader but skip detail pages by passing a want() that rejects everything, then re-read rows
rows = []
page = 1
while True:
    d = ats._get_json(f"{cfg['base']}/job_boards/{cfg['board']}/search?page_number={page}", headers={"X-Requested-With": "XMLHttpRequest"})
    if not d:
        break
    for li in re.findall(r'<li class="search-results__item">(.*?)</li>', d["html"], re.S):
        t = re.search(r'req_title[^>]*>(.*?)</a>', li, re.S).group(1)
        spans = [re.sub(r"<[^>]+>", "", s).strip() for s in re.findall(r"<span>(.*?)</span>", li, re.S)]
        rows.append((t, spans))
    if not d.get("more_requisitions"):
        break
    page += 1
print(len(rows), "jobs total")
us = [(t, s) for t, s in rows if s[1:2] == ["Americas"]]
print(len(us), "in Americas\n")
for t, s in us:
    loc = " · ".join(s[2:])
    ok = bool(US_STRONG.search(loc))
    c = classify({"title": t, "location": loc, "description": ""}, True)
    print(f"{'KEEP' if c else '    '} {'US ' if ok else '   '} {t[:70]:<70} | {s[0][:10]:<10} | {loc[:50]}")
