"""Do any of the job systems expose a structured application deadline? Print every date-like or deadline-like key."""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ats

KEY = re.compile(r"deadline|close|closing|expire|end|valid|until|apply", re.I)


def walk(node, path=""):
    if isinstance(node, dict):
        for k, v in node.items():
            p = f"{path}.{k}" if path else k
            if KEY.search(k) and not isinstance(v, (dict, list)):
                yield p, v
            yield from walk(v, p)
    elif isinstance(node, list):
        for i, v in enumerate(node[:3]):
            yield from walk(v, f"{path}[{i}]")


samples = {
    "greenhouse (Twitch)": "https://boards-api.greenhouse.io/v1/boards/twitch/jobs?content=false",
    "ashby (Notion)": "https://api.ashbyhq.com/posting-api/job-board/notion?includeCompensation=true",
    "lever (Point B)": "https://api.lever.co/v0/postings/pointb?mode=json",
}
for name, url in samples.items():
    d = ats._get_json(url)
    first = (d.get("jobs") if isinstance(d, dict) else d) or []
    first = first[0] if first else {}
    if name.startswith("greenhouse") and first:
        full = ats._get_json(f"https://boards-api.greenhouse.io/v1/boards/twitch/jobs/{first['id']}")
        first = full or first
    print(f"\n{name}: top-level keys = {sorted(first.keys())}")
    print("  deadline-like fields:", dict(walk(first)) or "none")

# Workday: detail record of one Guidehouse posting
api = "https://guidehouse.wd1.myworkdayjobs.com/wday/cxs/guidehouse/External"
lst = ats._get_json(f"{api}/jobs", data={"appliedFacets": {}, "limit": 1, "offset": 0, "searchText": "strategy"})
path = lst["jobPostings"][0]["externalPath"]
det = ats._get_json(f"{api}{path}")
info = det["jobPostingInfo"]
print("\nworkday (Guidehouse): jobPostingInfo keys =", sorted(info.keys()))
print("  deadline-like fields:", {k: info[k] for k in info if KEY.search(k) and not isinstance(info[k], (dict, list))})
