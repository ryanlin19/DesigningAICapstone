"""Try the firm-specific readers on a few firms and show what the classifier keeps."""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ats
from build import title_worth_opening
from classify import classify

cfgs = json.loads((Path(__file__).resolve().parents[2] / "data" / "custom_boards.json").read_text(encoding="utf-8"))
names = sys.argv[1:] or ["Kearney", "Guidehouse"]
for name in names:
    cfg = cfgs[name]
    t0 = time.time()
    jobs = ats.run_custom(cfg, want=title_worth_opening)
    if jobs is None:
        print(f"{name}: UNREACHABLE")
        continue
    kept = [(j, classify(j, True)) for j in jobs]
    kept = [(j, t) for j, t in kept if t]
    print(f"\n{name}: {len(jobs)} plausible titles opened -> {len(kept)} kept ({time.time() - t0:.0f}s)")
    for j, t in kept[:10]:
        print(f"  {j['title'][:52]:<52} | {j['location'][:34]:<34} | {t['category'][:14]:<14} | {t['seniority']:<13} | {j['posted']}")
