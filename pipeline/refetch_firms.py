"""Re-download the feeds of named custom firms into data/raw_fetch.json, so build.py --cached picks them up.
Usage: python pipeline/refetch_firms.py "Accenture" "Oliver Wyman" ..."""
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
import ats
from build import title_worth_opening

cfgs = json.loads((ROOT / "data" / "custom_boards.json").read_text(encoding="utf-8"))


def one(name):
    c = cfgs[name]
    jobs = ats.run_custom(c, want=title_worth_opening)
    slug = next((c[k] for k in ("slug", "tenant", "board", "sub", "host", "base") if c.get(k)), name)
    print(f"{name}: {None if jobs is None else len(jobs)} jobs", flush=True)
    return name, [c["platform"], slug, jobs] if jobs is not None else None


with ThreadPoolExecutor(max_workers=4) as ex:
    results = list(ex.map(one, sys.argv[1:]))
raw = json.loads((ROOT / "data" / "raw_fetch.json").read_text(encoding="utf-8"))
for name, val in results:
    if val is not None:
        raw[name] = val
(ROOT / "data" / "raw_fetch.json").write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
print("saved", flush=True)
