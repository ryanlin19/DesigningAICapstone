"""Validate research agents' output against their batches: ids, vertical pairs, office sources.

    python3 company-db/check_research.py            # all research files
"""
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from companies import KINDS, RESEARCH, VERTICALS, WORK  # noqa: E402


def check(batch_file):
    out = RESEARCH / batch_file.name
    want = [c["id"] for c in json.loads(batch_file.read_text())]
    if not out.exists():
        return "missing", []
    try:
        got = json.loads(out.read_text())
    except json.JSONDecodeError as e:
        return f"bad JSON: {e}", []
    problems = []
    ids = [r.get("id") for r in got]
    if set(want) - set(ids):
        problems.append(f"missing ids: {sorted(set(want) - set(ids))}")
    if set(ids) - set(want):
        problems.append(f"unknown ids: {sorted(set(ids) - set(want))}")
    for r in got:
        if r.get("kind") not in KINDS:
            problems.append(f"{r.get('id')}: kind {r.get('kind')!r}")
        v, s = r.get("vertical"), r.get("sub_vertical")
        if r.get("kind") == "employer" and (v not in VERTICALS or s not in VERTICALS.get(v, [])):
            problems.append(f"{r.get('id')}: vertical {v!r} / {s!r}")
        for o in r.get("us_offices") or []:
            if not o.get("source_url"):
                problems.append(f"{r.get('id')}: office {o.get('city')} has no source")
    return "ok" if not problems else "problems", problems


if __name__ == "__main__":
    tally = Counter()
    for f in sorted((WORK / "batches").glob("*.json")):
        status, problems = check(f)
        tally[status] += 1
        if status != "missing":
            print(f"{f.name}: {status}" + "".join(f"\n   - {p}" for p in problems[:10]))
    print(dict(tally))
