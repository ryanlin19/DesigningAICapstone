"""Spike step 2: run the classifier over the probed jobs and report what matches."""
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from classify import classify

DATA = Path(__file__).resolve().parents[2] / "data"


def main():
    results = json.loads((DATA / "spike_jobs.json").read_text(encoding="utf-8"))
    matches, total = [], 0
    for r in results:
        if not r["found"]:
            continue
        for j in r["jobs"]:
            total += 1
            tags = classify(j, r["group"] == "consulting")
            if tags:
                matches.append({"company": r["name"], "group": r["group"], **j, **tags})
    (DATA / "spike_matches.json").write_text(json.dumps(matches, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"{total} jobs scanned -> {len(matches)} matches "
          f"({sum(m['review'] for m in matches)} flagged for review)\n")
    print("By category:", dict(Counter(m["category"] for m in matches).most_common()))
    print("By seniority:", dict(Counter(m["seniority"] for m in matches).most_common()))
    print("By group:", dict(Counter(m["group"] for m in matches)))
    print("Companies with >=1 match:", len({m["company"] for m in matches}))
    print("MBA mentioned:", sum(m["mba_mentioned"] for m in matches),
          "| says no sponsorship:", sum(m["says_no_sponsorship"] for m in matches),
          "| says sponsors:", sum(m["says_sponsors"] for m in matches),
          "| has salary:", sum(bool(m["salary"]) for m in matches))
    print("\nSample titles per category (confident matches first):")
    for cat, _ in Counter(m["category"] for m in matches).most_common():
        ms = sorted((m for m in matches if m["category"] == cat), key=lambda m: m["review"])[:8]
        print(f"\n[{cat}]")
        for m in ms:
            print(f"  {'?' if m['review'] else ' '} {m['company'][:22]:<22} | {m['title'][:70]:<70} | {m['seniority']}")


if __name__ == "__main__":
    main()
