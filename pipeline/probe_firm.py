"""Fetch one firm-specific board, cache the raw postings in data/probe_cache, and show what the classifier keeps.
Usage: python pipeline/probe_firm.py "EY" [cached]"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
import ats
from build import title_worth_opening
from classify import classify

name = sys.argv[1]
cache = ROOT / "data" / "probe_cache" / (name.replace(" ", "_").replace("(", "").replace(")", "") + ".json")
if len(sys.argv) > 2 and sys.argv[2] == "cached" and cache.exists():
    jobs = json.loads(cache.read_text(encoding="utf-8"))
else:
    cfg = json.loads((ROOT / "data" / "custom_boards.json").read_text(encoding="utf-8"))[name]
    jobs = ats.run_custom(cfg, want=title_worth_opening)
    cache.parent.mkdir(exist_ok=True)
    cache.write_text(json.dumps(jobs, ensure_ascii=False), encoding="utf-8")
print(name, len(jobs), "fetched")
for j in jobs:
    t = classify(j, True)
    print(("KEEP " if t else "drop ") + f"{j['title'][:70]:<70} | {j['location'][:45]:<45} | {(t or {}).get('category', '')[:14]}")
