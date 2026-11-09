"""Show the text around the detected date for the board's dated roles outside Charles River."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from deadline import _DATED

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
root = Path(__file__).resolve().parents[2]
raw = json.loads((root / "data" / "raw_fetch.json").read_text(encoding="utf-8"))
seen = set()
for company in ("Guidehouse", "Gallup Consulting", "Planet Labs", "Samsara", "Twilio", "Intercom", "Toast", "Anthropic"):
    hit = raw.get(company)
    for job in (hit[2] if hit else []):
        text = job.get("description") or ""
        m = _DATED.search(text)
        if m and (company, job["title"]) not in seen:
            seen.add((company, job["title"]))
            s = max(0, m.start() - 80)
            print(f"{company} | {job['title'][:50]} | posted {job['posted']}\n    ...{text[s:m.end() + 40]!r}\n")
