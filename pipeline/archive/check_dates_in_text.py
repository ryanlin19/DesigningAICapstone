"""Show the posting text around each detected deadline so a human can confirm it is a real deadline."""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from deadline import _DATED, _ROLLING, _ASAP

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
root = Path(__file__).resolve().parents[2]
raw = json.loads((root / "data" / "raw_fetch.json").read_text(encoding="utf-8"))
want = {("Guidehouse", "Energy Efficiency Consultant"), ("Gallup Consulting", "Associate Consultant")}
shown = 0
for company, hit in raw.items():
    if not hit:
        continue
    for job in hit[2]:
        text = job.get("description") or ""
        for pat, label in ((_DATED, "DATE"), (_ROLLING, "ROLLING"), (_ASAP, "ASAP")):
            m = pat.search(text)
            if m and shown < 18 and (label != "DATE" or True):
                if label == "DATE" or any(c == company for c, _ in want) or shown < 18:
                    s = max(0, m.start() - 70)
                    print(f"[{label}] {company} | {job['title'][:48]}\n    ...{text[s:m.end() + 60]!r}\n")
                    shown += 1
                break
