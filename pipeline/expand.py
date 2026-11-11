"""Every US posting from the last download, labelled instead of filtered (Peter's branch).

Ryan's build keeps only the titles its rules accept. This keeps every posting located in the US (or remote)
and labels it: broad category, level, years asked, MBA mention, visa signal, pay, skill terms. The
Find-a-job page filters and judges fit on those labels.

    python pipeline/build.py           # downloads everything into data/raw_fetch.json
    python pipeline/expand.py          # -> data/all_jobs.json
    python pipeline/descriptions.py    # -> data/descriptions.db (full text for the "Job description" toggle)
    python cohort-api/push_jobs.py --kind all --file data/all_jobs.json     # into the cohort database

Note: the custom readers (Workday, SuccessFactors, ...) only open postings whose title passes Ryan's rules, so
for those firms this sees the same titles his board does. Greenhouse, Lever and Ashby feeds are complete.
"""
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build                      # noqa: E402  (Ryan's helpers: visa_label, split_locations, norm_url, read_seed)
import categories                 # noqa: E402
import classify as cl             # noqa: E402
import salary as salary_text      # noqa: E402
from match_index import Matcher   # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SNIPPET = 220
MAX_SKILLS = 12


def targets():
    """(name, group) exactly as build.py assembles them."""
    firms = json.loads((DATA / "firms.json").read_text(encoding="utf-8"))
    custom = {k: v for k, v in json.loads((DATA / "custom_boards.json").read_text(encoding="utf-8")).items() if not k.startswith("_")}
    out = [(f["name"], "consulting") for f in firms]
    names = {f["name"] for f in firms}
    out += [(n, "tech") for n in build.read_seed() if n not in names]
    listed = {n for n, _ in out}
    out += [(n, c.get("group", "consulting")) for n, c in custom.items() if n not in listed]
    return out, {f["name"]: f for f in firms}


def us_ok(loc):
    """Same location rule as classify(): keep US places, and a bare Remote / Hybrid with no foreign place named."""
    loc = loc or ""
    if not loc or cl.US_STRONG.search(loc):
        return True
    return not cl.NON_US.search(loc) and bool(re.search(r"\bremote\b|\bhybrid\b|\bmultiple\b|\banywhere\b", loc, re.I))


def iso(d):
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", (d or "").strip())
    return f"{m.group(3)}-{int(m.group(1)):02d}-{int(m.group(2)):02d}" if m else (d or "")[:10]


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", type=Path, default=DATA / "raw_fetch.json")
    ap.add_argument("--out", type=Path, default=DATA / "all_jobs.json")
    a = ap.parse_args()
    raw_path = a.raw
    if not raw_path.exists():
        sys.exit("data/raw_fetch.json is missing: run pipeline/build.py first (it downloads everything).")
    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    tlist, sheet = targets()
    stance_over = {k: v for k, v in json.loads((DATA / "stance_overrides.json").read_text(encoding="utf-8")).items() if not k.startswith("_")}
    matcher = Matcher()
    roles, seen, dropped = {}, 0, Counter()

    for name, group in tlist:
        hit = raw.get(name)
        if not hit:
            continue
        for j in hit[2]:
            seen += 1
            title = (j.get("title") or "").strip()
            if not title or not us_ok(j.get("location")):
                dropped["outside the US" if title else "no title"] += 1
                continue
            desc = j.get("description") or ""
            years = cl._min_years(desc[:6000])
            key = (name, re.sub(r"\s+", " ", title.lower()))
            places, remote = build.split_locations(j.get("location") or "")
            url = build.norm_url(j.get("url") or "")
            posted = iso(j.get("posted"))
            if key in roles:                                   # same title posted for several places
                r = roles[key]
                have = {loc["name"] for loc in r["locations"]}
                r["locations"] += [{"name": p, "url": url} for p in places if p not in have]
                r["remote"] = r["remote"] or remote
                if posted > (r["posted"] or ""):
                    r["posted"] = posted
                continue
            immig_offers, immig_declines = cl.immigration_support(desc)
            tags = {"requires_clearance": bool(cl.CLEARANCE.search(desc)),
                    "says_no_sponsorship": bool(cl.NO_SPONSOR.search(desc)) or immig_declines,
                    "says_sponsors": bool(cl.YES_SPONSOR.search(desc)),
                    "immigration_support": immig_offers and not immig_declines}
            stance = stance_over.get(name) or (sheet[name]["visa_stance"] if name in sheet else None)
            visa, reasons, _ = build.visa_label(tags, stance)
            sal = j.get("salary") or salary_text.from_text(desc)[0]
            m = matcher.counts(title, desc)
            skills = sorted(m["k"].items(), key=lambda kv: -kv[1])[:MAX_SKILLS]
            roles[key] = {
                "company": name, "group": group, "title": title,
                "category": categories.category(title, group == "consulting"),
                "level": categories.level(title, years), "min_years": years,
                "mba": cl.mba_kind(title, desc),
                "on_classic_board": cl.classify(j, group == "consulting", allow_vp=name in build.VP_FIRMS) is not None,
                "visa": visa, "visa_reasons": reasons, "posted": posted, "url": url,
                "locations": [{"name": p, "url": url} for p in places], "remote": remote,
                "salary": sal if isinstance(sal, dict) else None,
                "snippet": re.sub(r"\s+", " ", desc[:SNIPPET * 2]).strip()[:SNIPPET],
                "sk": [[int(k), int(w)] for k, w in skills], "ind": [int(n) for n in m["i"]],
            }

    jobs = list(roles.values())
    for i, r in enumerate(jobs):
        r["id"] = i
        names = list(dict.fromkeys(loc["name"] for loc in r["locations"]))
        r["location"] = names[0] if len(names) == 1 else f"{names[0]} + {len(names) - 1} more" if names else ""
    out = {"generated": str(build.TODAY), "kind": "all", "postings_seen": seen, "dropped": dict(dropped),
           "categories": categories.CATEGORIES, "levels": categories.LEVELS,
           "vocab": {"skills": [s["l"] for s in matcher.vocab["skills"]], "inds": [s["l"] for s in matcher.vocab["inds"]]},
           "jobs": jobs}
    a.out.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    by_cat = Counter(r["category"] for r in jobs)
    by_lvl = Counter(r["level"] for r in jobs)
    print(f"{seen} postings seen, {len(jobs)} US roles kept ({dict(dropped)})")
    print("by category:", dict(by_cat.most_common()))
    print("by level:", {lv: by_lvl[lv] for lv in categories.LEVELS})
    print(f"on Ryan's board's rules: {sum(r['on_classic_board'] for r in jobs)}")


if __name__ == "__main__":
    main()
