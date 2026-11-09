"""One-time start of data/history.json (the record behind the "What's new" tab).

It records today's download as the baseline and turns the Oct 23 -> Oct 27 comparison (logs/refresh-changes-2026-10-27.csv) into
the first update. After this, every full download (build.py without --cached) adds its own update automatically.
Run: python pipeline/seed_history.py   (only once; it refuses to overwrite an existing history file)
"""
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "pipeline"))
from build import DATA, norm_url   # noqa: E402

target = DATA / "history.json"
if target.exists():
    sys.exit("data/history.json already exists; not overwriting it")

raw = json.loads((DATA / "raw_fetch.json").read_text(encoding="utf-8"))
raw_urls = sorted({norm_url(j["url"]) for hit in raw.values() if hit for j in hit[2]})

text = (ROOT / "public" / "data.js").read_text(encoding="utf-8")
jobs = json.loads(text[len("window.BOARD_DATA = "):].rstrip().rstrip(";"))["jobs"]
board = [{"urls": sorted({loc["url"] for loc in j["locations"]}), "company": j["company"], "title": j["title"],
          "visa": j["visa"], "mba": bool(j["mba"])} for j in jobs]
by_key = {}
for j in jobs:
    by_key.setdefault((j["company"], j["title"].strip().lower()), []).append(j["url"])

rows = list(csv.DictReader(open(ROOT / "logs" / "refresh-changes-2026-10-27.csv", encoding="utf-8-sig")))
added = sorted({u for r in rows if r["Change"] == "ADDED" for u in by_key.get((r["Company"], r["Role"].strip().lower()), [])})
removed = [{"company": r["Company"], "title": r["Role"], "visa": r["Visa signal"], "mba": r["In MBA roles"] == "yes"}
           for r in rows if r["Change"] == "REMOVED"]
history = {"date": "2026-10-27", "raw_urls": raw_urls, "board": board,
           "batches": [{"date": "2026-10-27", "since": "2026-10-23", "added": added, "removed": removed}]}
target.write_text(json.dumps(history, ensure_ascii=False), encoding="utf-8")
print(f"history started: {len(raw_urls)} posting links, {len(board)} roles; first update has {len(added)} new and {len(removed)} no longer listed")
