"""The company directory for the Companies tab: data/companies.db (built by company-db/companies.py), with each
company's cohort ties and the jobs we have for it.

    load()                      -> {"companies": [...], "names": {alias: id}, "version": mtime} or None
    job_index(jobs, names)      -> {company id: {"n": count, "label": job company name}}
    rank_key(company)           -> sort key: a classmate works there, then worked there, then connections, then jobs

No network: everything is read from the local database file. The file is git-ignored because its company list
comes from classmates' connections.
"""
import os
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
DB = Path(os.environ.get("COHORT_COMPANIES_DB") or HERE.parent / "data" / "companies.db")
sys.path.insert(0, str(HERE.parent / "linkedin-ingest"))
from ingest import rules  # noqa: E402

KINDS_SHOWN = ("employer",)          # schools, recruiters, student clubs and non-companies stay out of the directory
_cache = {"version": None, "value": None}


def _office_name(o):
    """A metro area when we have one ("Seattle area"); the city itself when the metro is only a state catch-all."""
    metro = o["metro"] or ""
    if metro and not metro.startswith("Elsewhere in"):
        return metro
    return ", ".join(x for x in (o["city"], o["region"]) if x) or metro or None


def load():
    if not DB.exists():
        return None
    version = DB.stat().st_mtime
    if _cache["version"] == version:
        return _cache["value"]
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        offices, metros = defaultdict(list), defaultdict(set)
        for o in con.execute("SELECT * FROM offices ORDER BY is_hq DESC, job_count DESC, source"):
            if o["metro"]:
                metros[o["company_id"]].add(o["metro"])          # map regions, for the Location filter
            name = _office_name(o)
            if not o["is_hq"] and name and name not in offices[o["company_id"]]:
                offices[o["company_id"]].append(name)
        targets = {r["id"]: r["name"] for r in con.execute("SELECT id, name FROM targets")}
        companies = []
        for c in con.execute(f"SELECT * FROM companies WHERE kind IN ({','.join('?' * len(KINDS_SHOWN))})", KINDS_SHOWN):
            hq = ", ".join(x for x in (c["hq_city"], c["hq_region"],
                                       None if (c["hq_country"] or "").startswith("United States") else c["hq_country"]) if x)
            companies.append({
                "id": c["id"], "name": c["name"], "cohort_name": targets.get(c["id"], c["name"]),
                "vertical": c["vertical"], "sub": c["sub_vertical"],
                "desc": c["description"] or c["short_description"] or "", "website": c["website"],
                "hq": hq, "offices": offices.get(c["id"], []), "regions": sorted(metros.get(c["id"], ())), "sp500": bool(c["sp500"]),
                "ownership": c["ownership"], "employees": c["employees"], "researched": bool(c["researched"]),
                "confidence": c["confidence"]})
        names = {a: cid for a, cid in con.execute("SELECT alias, company_id FROM names")}
    finally:
        con.close()
    for c in companies:                   # the directory's own name (agents sometimes cleaned it up) also points here
        n = rules.normalize_company(c["name"])
        if n:
            names.setdefault(n, c["id"])
            names.setdefault(rules.compress(n), c["id"])
    value = {"companies": companies, "names": names, "version": version}
    _cache.update(version=version, value=value)
    return value


def company_id(name, names):
    n = rules.normalize_company(name or "")
    if not n:
        return None
    return names.get(n) or names.get(rules.compress(n))


def job_index(jobs, names):
    """Count postings per directory company; the label is the job feed's own company name (for Find a job links)."""
    count, labels = Counter(), defaultdict(Counter)
    memo = {}
    for j in jobs:
        co = j.get("company")
        if co not in memo:
            memo[co] = company_id(co, names)
        cid = memo[co]
        if cid:
            count[cid] += 1
            labels[cid][co] += 1
    return {cid: {"n": n, "label": labels[cid].most_common(1)[0][0]} for cid, n in count.items()}


def rank_key(c):
    people = c.get("people") or []
    works = any((p.get("worked") or {}).get("current") for p in people)
    worked = any(p.get("worked") for p in people)
    return (not works, not worked, -(c.get("contacts") or 0), -((c.get("jobs") or {}).get("n") or 0), c["name"].lower())
