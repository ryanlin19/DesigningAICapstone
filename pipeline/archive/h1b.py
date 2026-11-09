"""H-1B employer history from the USCIS Employer Data Hub CSVs.

load() aggregates approvals by normalized employer name. lookup() matches a
company name against it and returns a tier plus the evidence.
"""
import csv
import re
from collections import defaultdict
from pathlib import Path

JOB_TRACKER = Path(__file__).resolve().parents[3]

_SUFFIX = {"inc", "llc", "llp", "lp", "ltd", "limited", "corp", "corporation", "co", "company", "plc", "pc", "na",
           "us", "usa", "america", "americas", "holdings", "holding", "group", "the", "of", "and", "services", "intl"}

# Firm names in the sheet that differ from the legal names USCIS lists.
ALIASES = {
    "ey": ["ernst young"],
    "eyparthenon": ["ernst young"],
    "pwc": ["pricewaterhousecoopers"],
    "strategy": ["pricewaterhousecoopers"],
    "bcg": ["boston consulting"],
    "bostonconsultinggroupbcg": ["boston consulting"],
    "mckinsey": ["mckinsey"],
    "bain": ["bain"],
    "kearney": ["a t kearney", "kearney"],
    "lek": ["l e k consulting", "lek consulting"],
    "tcs": ["tata consultancy"],
    "tataconsultancyserviceslimitedtcs": ["tata consultancy"],
    "ocandc": ["oc c strategy"],
    "oliverwyman": ["oliver wyman"],
}


# Firms whose name collides with unrelated USCIS employers; add to this list when check_h1b_matches.py shows a bad match.
NO_MATCH = {"The Keystone Group"}


def norm(name):
    n = (name or "").lower()
    n = re.sub(r"\bd/?b/?a\b.*", "", n)           # drop "DBA ..." trade names
    n = n.replace("&", " ")
    n = re.sub(r"\(.*?\)", " ", n)
    n = re.sub(r"[^a-z0-9 ]", " ", n)
    toks = [t for t in n.split() if t not in _SUFFIX]
    return " ".join(toks)


def load(folder=JOB_TRACKER):
    """-> {normalized employer: {"initial": n, "continuing": n, "years": {fy: n}, "names": set}}"""
    agg = defaultdict(lambda: {"initial": 0, "continuing": 0, "years": defaultdict(int), "names": set()})
    files = sorted(Path(folder).glob("h1b_datahubexport-*.csv"))
    for fp in files:
        with open(fp, encoding="utf-8-sig", newline="", errors="replace") as f:
            for row in csv.DictReader(f):
                key = norm(row.get("Employer"))
                if not key:
                    continue
                ia = int(row.get("Initial Approval") or 0)
                ca = int(row.get("Continuing Approval") or 0)
                a = agg[key]
                a["initial"] += ia
                a["continuing"] += ca
                a["years"][row["Fiscal Year"]] += ia + ca
                if len(a["names"]) < 3:
                    a["names"].add(row["Employer"].strip())
    return agg, [p.name for p in files]


# Words that, after a company name, still mean the same employer (Deloitte Consulting, Notion Labs).
_EXTENSIONS = {"consulting", "advisory", "advisors", "technologies", "technology", "tech", "labs", "ai", "solutions",
               "partners", "associates", "capital", "financial", "tax", "touche", "digital", "software", "systems",
               "pbc", "research", "strategy", "management", "analytics", "health", "data", "cloud", "security",
               "payments", "bank", "securities", "ventures", "networks", "interactive", "education"}

_SQ_CACHE = {}


_GENERIC = {"consulting", "consultants", "consultancy", "advisors", "advisory", "partners", "associates"}


def _core(key):
    """Name with generic firm words dropped: 'gallup consulting' -> 'gallup'."""
    return " ".join(t for t in key.split() if t not in _GENERIC)


def _squashed_index(agg):
    """Index of spaceless names, both as-is and with generic words dropped."""
    idx = _SQ_CACHE.get(id(agg))
    if idx is None:
        idx = defaultdict(list)
        for a in agg:
            idx[a.replace(" ", "")].append(a)
            c = _core(a).replace(" ", "")
            if c and len(c) >= 6 and c != a.replace(" ", ""):
                idx[c].append(a)
        _SQ_CACHE[id(agg)] = idx
    return idx


def tier(total_initial):
    if total_initial >= 20:
        return "Active"
    if total_initial >= 3:
        return "Occasional"
    return "None found"


def lookup(agg, company, extra_aliases=None):
    """Match a company name; sums every USCIS entity whose name starts with it.

    Prefix matching is only used for names of 6+ characters so short, common
    words (Block, Ramp, Lime) don't pull in unrelated employers.
    """
    if company in NO_MATCH:
        return {"tier": "None found", "initial": 0, "continuing": 0, "matched": []}
    key = norm(company)
    squashed = key.replace(" ", "")
    keys = [key] + ALIASES.get(squashed, []) + list((extra_aliases or {}).get(company, []))
    hit_keys = set()
    for k in keys:
        if k in agg:
            hit_keys.add(k)
        if len(k.replace(" ", "")) >= 6:
            pre = k + " "
            for a in agg:
                if a.startswith(pre):
                    # only accept "Kearney Consulting"-style extensions, not "Kearney Regional Medical"
                    extra = a[len(pre):].split()
                    if all(t in _EXTENSIONS for t in extra):
                        hit_keys.add(a)
    idx = _squashed_index(agg)
    core = _core(key).replace(" ", "")
    for sq in {squashed, core if len(core) >= 6 else squashed}:  # "alix partners" vs "ALIXPARTNERS"
        hit_keys.update(idx.get(sq, []))
    if not hit_keys:
        return {"tier": "None found", "initial": 0, "continuing": 0, "matched": []}
    initial = sum(agg[k]["initial"] for k in hit_keys)
    cont = sum(agg[k]["continuing"] for k in hit_keys)
    matched = sorted(hit_keys, key=lambda k: -agg[k]["initial"])[:3]
    return {"tier": tier(initial), "initial": initial, "continuing": cont,
            "matched": [", ".join(sorted(agg[k]["names"]))[:60] for k in matched]}
