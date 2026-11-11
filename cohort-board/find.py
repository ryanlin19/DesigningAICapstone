"""Find a job: resume -> profile, and job search by broad category with fit buckets.

Fit is judged on two things only:
  field  - the job's broad category against yours: same (strong), a neighbour (partial), or different (none)
  level  - the years the job asks (or its level) against your experience, counting an MBA

            asks 2+ more years   about right    well below you
  strong    Reach                Ready          Overqualified
  partial   Reach                Reach          Overqualified
  none      Serious pivot        Serious pivot  Serious pivot

The resume text is analysed in memory and not stored; the page keeps the resulting profile in the browser.
"""
import hashlib
import json
import re
import sys
from collections import Counter
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO / "pipeline"))
import categories as cats  # noqa: E402
from match_index import Matcher, normalize  # noqa: E402

BUCKETS = ["ready", "reach", "overqualified", "pivot"]
BUCKET_LABEL = {"ready": "Ready", "reach": "Reach", "overqualified": "Overqualified", "pivot": "Serious pivot"}
_matcher = None


def matcher():
    global _matcher
    if _matcher is None:
        _matcher = Matcher()
    return _matcher


# ---------- resume -> profile ----------

_MON = "jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec"
_SPAN = re.compile(r"(?:(" + _MON + r")[a-z]*\.?\s+)?((?:19|20)\d\d)\s*(?:-|–|—|to)\s*(?:(present|current|now)|(?:(" + _MON +
                   r")[a-z]*\.?\s+)?((?:19|20)\d\d))", re.I)
_EDU_LINE = re.compile(r"universit|college|school|bachelor|\bb\.?[sa]\.?\b|\bmba\b|master|\bm\.?s\.?\b|ph\.?d|\bgpa\b|degree|"
                       r"diploma|expected|coursework", re.I)


def estimate_years(text):
    """Years of work experience from date ranges on non-education lines (overlaps merged); same idea as the
    classic board's resume reader."""
    today = date.today()
    now = today.year + (today.month - 1) / 12
    mi = lambda m: (_MON.split("|").index(m.lower()[:3]) if m else 0) / 12
    spans = []
    for line in normalize(text).splitlines():
        if _EDU_LINE.search(line):
            continue
        for m in _SPAN.finditer(line):
            a = int(m.group(2)) + mi(m.group(1))
            b = now if m.group(3) else int(m.group(5)) + mi(m.group(4))
            if b >= a and a > 1980 and b - a < 40:
                spans.append((a, b))
    spans.sort()
    total, cur = 0.0, None
    for a, b in spans:
        if not cur or a > cur[1]:
            if cur:
                total += cur[1] - cur[0]
            cur = [a, b]
        elif b > cur[1]:
            cur[1] = b
    if cur:
        total += cur[1] - cur[0]
    said = max([int(x) for x in re.findall(r"(\d{1,2})\+?\s*years?\s+(?:of\s+)?(?:[a-z\- ]{0,30}\s)?experience", text, re.I)] or [0])
    return min(40, round(total if total > 0 else said))


def resume_profile(text, history_titles=()):
    """-> {years, mba, categories, category_scores, skills, inds}. history_titles: the person's own job titles
    from their loaded LinkedIn export, which count toward their categories."""
    t = normalize(text)
    scores = Counter()
    for line in t.splitlines():                      # lines that read like job titles say the most
        line = line.strip()
        if 3 <= len(line) <= 90 and not _EDU_LINE.search(line):
            c = cats.category(line)
            if c != "Other":
                scores[c] += 1
    for title in history_titles:
        c = cats.category(title)
        if c != "Other":
            scores[c] += 3
    top = scores.most_common()
    # up to three fields with real evidence; a short resume may name a field only once
    chosen = [c for c, n in top[:3] if n >= max(1, top[0][1] * 0.3)] if top else []
    m = matcher()
    return {"years": estimate_years(text), "mba": bool(re.search(r"\bmba\b|master of business administration", t)),
            "categories": chosen, "category_scores": dict(top[:6]),
            "skills": sorted(m.terms_in(text)), "inds": sorted({m.in_idx[x] for x in m.in_re.findall(t)})}


# ---------- fit ----------

def field_of(job, p):
    """strong (your field) | partial (a neighbour) | none."""
    mine = p.get("categories") or []
    jc = job["category"]
    if jc in mine:
        return "strong"
    if any(jc in cats.ADJACENT.get(c, ()) for c in mine):
        return "partial"
    return "none"


def years_of(job, p):
    """(years the job asks, your effective years: an MBA counts 2)."""
    years = max(0, int(p.get("years") or 0))
    asks = job["min_years"] if job.get("min_years") is not None else cats.LEVEL_YEARS[job["level"]]
    return asks, years + (2 if p.get("mba") else 0)


def fit(job, p):
    """-> (bucket, reason). p: {years, mba, categories}."""
    mine = p.get("categories") or []
    jc = job["category"]
    field = field_of(job, p)
    years = max(0, int(p.get("years") or 0))
    mba = bool(p.get("mba"))
    lvl = job["level"]
    asks, eff = years_of(job, p)
    you = f"you have about {years} yr{'s' if years != 1 else ''}" + (" + an MBA" if mba else "")
    asks_txt = f"asks {job['min_years']}+ yrs" if job.get("min_years") is not None else f"{lvl.lower()}-level role"
    if lvl == "Internship":
        level, why_level = "over", "an internship"
    elif lvl == "Entry" and (mba or years >= 4):
        level, why_level = "over", f"entry-level role; {you}"
    elif eff - asks > 6:
        level, why_level = "over", f"{asks_txt}; {you}"
    elif asks - eff >= 2 or (lvl == "Executive" and eff < 12):
        level, why_level = "under", f"{asks_txt}; {you}"
    else:
        level, why_level = "right", f"{asks_txt}; {you}"

    if field == "none":
        yours = ", ".join(mine) if mine else "none picked yet"
        return "pivot", f"Different field: {jc} (yours: {yours})"
    if level == "over":
        return "overqualified", why_level[0].upper() + why_level[1:]
    if level == "under":
        return "reach", "Stretch on experience: " + why_level
    if field == "partial":
        return "reach", f"Neighbouring field: {jc}; " + why_level
    return "ready", f"Your field ({jc}); " + why_level


# ---------- what you want: ranking, what would make you closer, and your path ----------

# Skill terms too generic (or too much a domain) to be useful advice in "Closer with".
GENERIC_SKILLS = {"Leadership", "Communication", "Hiring and recruiting", "Stakeholder management", "Cross-functional leadership",
                  "Problem solving", "People management", "Executive communication", "Negotiation", "Manufacturing",
                  "Data center and infrastructure", "Public sector and policy"}
# Industries named in a posting -> directory verticals, for companies the company database doesn't cover (a weaker signal).
IND_VERTICAL = {"Healthcare": "Healthcare & Life Sciences", "Life sciences": "Healthcare & Life Sciences",
                "Health tech": "Healthcare & Life Sciences", "Financial services": "Financial Services", "Fintech": "Financial Services",
                "Software and SaaS": "Technology", "AI and data": "Technology", "Consumer and retail": "Consumer & Retail",
                "Travel and hospitality": "Consumer & Retail", "Media and entertainment": "Media, Entertainment & Telecom",
                "Telecom and infrastructure": "Media, Entertainment & Telecom", "Energy and utilities": "Energy & Climate",
                "Industrials": "Industrials & Manufacturing", "Transportation and logistics": "Transportation & Logistics",
                "Real estate and construction": "Real Estate", "Education": "Education", "Public sector": "Government & Nonprofit",
                "Professional services": "Consulting"}
FEASIBLE = {"ready": 1.0, "reach": 0.6, "overqualified": 0.25, "pivot": 0.1}
_CRED = re.compile(r"\b(CPA|CFA|PMP|security clearance|clearance required|active clearance|bar admission|licensed attorney)\b", re.I)
_idf_cache = {"key": None, "idf": None}


def skill_idf(data):
    """Rarer skill terms say more about a job: weight them up (cached per job set)."""
    if _idf_cache["key"] != id(data):
        import math
        n = max(1, len(data["jobs"]))
        df = Counter(k for j in data["jobs"] for k, _ in j.get("sk", []))
        _idf_cache.update(key=id(data), idf={k: math.log((n + 1) / (c + 1)) + 0.5 for k, c in df.items()})
    return _idf_cache["idf"]


def clean_want(w):
    w = w or {}
    lst = lambda k: [str(x).strip() for x in (w.get(k) or []) if str(x).strip()][:20]
    try:
        floor = max(0, int(w.get("salary_min") or 0))
    except (TypeError, ValueError):
        floor = 0
    return {"categories": lst("categories"), "levels": lst("levels"), "verticals": lst("verticals"),
            "companies": [c.lower() for c in lst("companies")], "avoid": [a.lower() for a in lst("avoid")], "salary_min": floor}


def has_want(w):
    return any(w[k] for k in ("categories", "levels", "verticals", "companies"))


def job_vertical(j, co_vertical, inds):
    """(vertical, sure): from the company database when it knows the company, else the industries the posting names."""
    v = co_vertical.get(j["company"])
    if v:
        return [v], True
    out = []
    for i in j.get("ind") or []:
        k = i if isinstance(i, int) else i[0]
        name = IND_VERTICAL.get(inds[k]) if k < len(inds) else None
        if name and name not in out:
            out.append(name)
    return out, False


def blocked(j, w):
    """The want's hard limits: companies or words to avoid, and a salary floor (in $K; unknown pay passes)."""
    if w["avoid"]:
        co, title = j["company"].lower(), j["title"].lower()
        if any(a in co or re.search(r"\b" + re.escape(a) + r"\b", title) for a in w["avoid"]):
            return True
    if w["salary_min"]:
        top = (j.get("salary") or {}).get("max")
        if top and top < w["salary_min"] * 1000:
            return True
    return False


def rank(j, fitinfo, p, w, tie, vert, today):
    """-> (score, reasons). What you want, how reachable it is, cohort warmth, freshness. Reasons: at most 3, best first."""
    b = fitinfo[0]
    s, reasons = 0.0, []
    jc = j["category"]
    if w["companies"] and any(c in j["company"].lower() for c in w["companies"]):
        s += 0.8
        reasons.append("Target company")
    if w["categories"]:
        if jc in w["categories"]:
            s += 1.0
            reasons.append("Target field: " + jc)
        elif any(jc in cats.ADJACENT.get(c, ()) for c in w["categories"]):
            s += 0.4
    if w["levels"] and j["level"] in w["levels"]:
        s += 0.4
    vs, sure = vert
    hit = [v for v in vs if v in w["verticals"]]
    if hit:
        s += 0.6 if sure else 0.3
        reasons.append("Target vertical: " + hit[0])
    feas = FEASIBLE[b]
    if b == "pivot" and jc in w["categories"]:
        feas = 0.45                                        # a pivot into a field you want is worth showing
    s += feas + 0.5 * fitinfo[2]
    if tie:
        if tie.get("alumni"):
            s += 0.4
            reasons.append(tie["alumni"][0] + " worked here" if len(tie["alumni"]) == 1 else f"{len(tie['alumni'])} classmates worked here")
        elif tie.get("contacts"):
            s += 0.2
            reasons.append(f"{tie['contacts']} cohort contact{'s' if tie['contacts'] != 1 else ''} here")
    d = _days_ago(j.get("posted"), today)
    if d is not None:
        s += 0.3 * max(0.0, 1 - d / 60)
    return s, reasons[:3]


def missing_skills(j, skills, vocab, idf, n=2):
    """The posting's most telling skill terms that aren't in your profile (generic ones left out)."""
    ranked = sorted(j.get("sk", []), key=lambda kw: -kw[1] * idf.get(kw[0], 1))
    return [k for k, _ in ranked if k not in skills and k < len(vocab) and vocab[k] not in GENERIC_SKILLS][:n]


def closer(j, fitinfo, p, vocab, idf):
    """What would bring a Reach or Serious pivot job within reach: at most 3 short items, from the posting itself."""
    b = fitinfo[0]
    if b not in ("reach", "pivot"):
        return []
    out = []
    field = field_of(j, p)
    if field != "strong":
        out.append(j["category"] + " experience")
    asks, eff = years_of(j, p)
    if asks - eff >= 2 and j["level"] != "Internship":
        out.append(f"{asks - eff} more year{'s' if asks - eff != 1 else ''}")
    if j.get("mba") in ("title", "required") and not p.get("mba"):
        out.append("an MBA")
    m = _CRED.search((j.get("title") or "") + " " + (j.get("snippet") or ""))
    if m:
        out.append(m.group(1))
    skills = set(p.get("skills") or [])
    out += [vocab[k] for k in missing_skills(j, skills, vocab, idf)]
    return out[:3]


def path(data, p, w, fits, keep, vocab, idf):
    """Your closest gaps across the roles you're aiming at (target fields, else your Reach roles): at most 3 items.

    bridge: target-field roles at your level, where the field is the only gap; skill: a term missing from many of them;
    years: when many of them ask for more experience than you have."""
    if w["categories"]:
        aim = [j for j in data["jobs"] if keep(j) and j["category"] in w["categories"]]
        label = "your target roles"
    else:
        aim = [j for j in data["jobs"] if keep(j) and fits[j["id"]][0] == "reach"]
        label = "your Reach roles"
    if not aim:
        return {"items": [], "basis": label, "n": 0}
    items = []
    mine = set(p.get("categories") or [])
    bridges = []
    for c in w["categories"]:
        if c in mine:
            continue
        n = sum(1 for j in aim if j["category"] == c and years_of(j, p)[0] - years_of(j, p)[1] < 2 and j["level"] != "Internship")
        if n:
            bridges.append({"kind": "bridge", "category": c, "n": n,
                            "text": f"{n:,} {c} roles match your level; the field is the only gap"})
    items += sorted(bridges, key=lambda b: -b["n"])[:1]                 # the biggest bridge; the rest of the space is for skills
    skills = set(p.get("skills") or [])
    gap = Counter()
    for j in aim:
        for k in missing_skills(j, skills, vocab, idf, n=3):
            gap[k] += 1
    for k, n in gap.most_common(2):
        share = n / len(aim)
        if share >= 0.08:
            items.append({"kind": "skill", "skill": k, "n": n, "text": f"{vocab[k]}: in {round(share * 100)}% of {label}"})
    longer = sum(1 for j in aim if years_of(j, p)[0] - years_of(j, p)[1] >= 2) / len(aim)
    if longer >= 0.3:
        items.append({"kind": "years", "text": f"{round(longer * 100)}% of {label} ask for more experience than you have"})
    return {"items": items[:3], "basis": label, "n": len(aim)}


def skill_match(job, skills):
    """(score 0-1, top matched skill indexes) from the job's weighted skill terms."""
    total = sum(w for _, w in job.get("sk", []))
    hit = [(k, w) for k, w in job.get("sk", []) if k in skills]
    got = sum(w for _, w in hit)
    return (got / total) ** 0.5 if total else 0.0, [k for k, _ in sorted(hit, key=lambda x: -x[1])[:3]]


# ---------- search ----------

_fit_cache = {"key": None, "fits": None}
_region_cache = {"key": None, "regions": None}


def job_regions(data):
    """{job id: [regions]} for a job set, worked out once per load (see regions.py)."""
    import regions as R
    if _region_cache["key"] != id(data):
        _region_cache.update(key=id(data), regions={
            j["id"]: R.regions_for([loc["name"] for loc in j.get("locations") or []], j.get("remote")) for j in data["jobs"]})
    return _region_cache["regions"]


def _fits(data, profile):
    key = (id(data), hashlib.sha1(json.dumps({k: profile.get(k) for k in ("years", "mba", "categories", "skills")},
                                             sort_keys=True).encode()).hexdigest())
    if _fit_cache["key"] != key:
        skills = set(profile.get("skills") or [])
        fits = {}
        for j in data["jobs"]:
            b, why = fit(j, profile)
            score, top = skill_match(j, skills)
            fits[j["id"]] = (b, why, score, top)
        _fit_cache.update(key=key, fits=fits)
    return _fit_cache["fits"]


_rank_cache = {"key": None, "ranks": None}


def _ranks(data, profile, w, cohort, co_vertical, inds, fits, today):
    """rank() for every job, cached per job set, profile, want, cohort ties and day (filters don't change a job's score)."""
    key = (id(data), id(fits), json.dumps(w, sort_keys=True), id(cohort), id(co_vertical), today.isoformat())
    if _rank_cache["key"] != key:
        _rank_cache.update(key=key, ranks={j["id"]: rank(j, fits[j["id"]], profile, w, cohort.get(j["company"]),
                                                         job_vertical(j, co_vertical, inds), today) for j in data["jobs"]})
    return _rank_cache["ranks"]


def _days_ago(posted, today):
    try:
        return (today - date.fromisoformat(posted[:10])).days
    except (TypeError, ValueError):
        return None


def search(data, profile, f, cohort=None, offset=0, limit=40, want=None, co_vertical=None, with_path=False):
    """f: {categories, buckets, levels, posted, q, mba, hide_unlikely, warm, sort, skill}. want: "What you want"
    {categories, levels, verticals, companies, avoid, salary_min}. Returns counts and one page (and your path)."""
    has_profile = bool(profile and (profile.get("categories") or profile.get("skills")))
    fits = _fits(data, profile) if has_profile else {}
    cohort = cohort or {}
    w = clean_want(want)
    co_vertical = co_vertical or {}
    inds = data.get("vocab", {}).get("inds", [])
    try:
        want_skill = int(f["skill"]) if f.get("skill") not in (None, "") else None
    except (TypeError, ValueError):
        want_skill = None
    today = date.today()
    want_cats, want_buckets, want_levels = set(f.get("categories") or []), set(f.get("buckets") or []), set(f.get("levels") or [])
    q = (f.get("q") or "").strip().lower()
    posted = int(f.get("posted") or 0)
    p_from, p_to = (f.get("from") or "")[:10], (f.get("to") or "")[:10]     # a period picked on the timeline (ISO dates)
    hidden = set(f.get("hidden") or [])                                      # companies the user chose to hide
    want_regions = set(f.get("regions") or [])                               # picked on the map
    # sponsorship from the "Your search" panel: any | not_no (hide "won't sponsor") | likely
    visa = f.get("visa") or ("not_no" if f.get("hide_unlikely") else "any")
    regs = job_regions(data)

    def keep(j):                                          # hard limits: hidden companies, the want's avoid list and pay floor,
        if hidden and j["company"] in hidden:             # sponsorship and location
            return False
        if blocked(j, w):
            return False
        if visa == "not_no" and j.get("visa") == "Unlikely":
            return False
        if visa == "likely" and j.get("visa") != "Likely":
            return False
        return not want_regions or bool(want_regions.intersection(regs[j["id"]]))

    def passes(j, skip=None):
        if hidden and j["company"] in hidden:
            return False
        if blocked(j, w):
            return False
        if want_skill is not None and not any(k == want_skill for k, _ in j.get("sk", [])):
            return False
        if skip != "regions" and want_regions and not want_regions.intersection(regs[j["id"]]):
            return False
        if skip != "period" and p_from:
            d = (j.get("posted") or "")[:10]
            if not d or d < p_from or d > p_to:
                return False
        if skip != "categories" and want_cats and j["category"] not in want_cats:
            return False
        if skip != "buckets" and has_profile and want_buckets and fits[j["id"]][0] not in want_buckets:
            return False
        if skip != "levels" and want_levels and j["level"] not in want_levels:
            return False
        if posted:
            d = _days_ago(j.get("posted"), today)
            if d is None or d > posted:
                return False
        if q and q not in j["company"].lower():
            return False
        if f.get("mba") and not j.get("mba"):
            return False
        if visa == "not_no" and j.get("visa") == "Unlikely":
            return False
        if visa == "likely" and j.get("visa") != "Likely":
            return False
        if f.get("warm") and not cohort.get(j["company"]):
            return False
        return True

    counts = {"categories": Counter(j["category"] for j in data["jobs"] if passes(j, "categories")),
              "levels": Counter(j["level"] for j in data["jobs"] if passes(j, "levels")),
              "buckets": Counter(fits[j["id"]][0] for j in data["jobs"] if passes(j, "buckets")) if has_profile else {}}
    # map: jobs per region for everything that passes the other filters; a job in n regions counts 1/n in each
    region_raw, region_w = Counter(), Counter()
    for j in data["jobs"]:
        if passes(j, "regions"):
            rs = regs[j["id"]]
            for r in rs:
                region_raw[r] += 1
                region_w[r] += 1 / len(rs)
    counts["regions"] = {r: [region_raw[r], round(region_w[r], 1)] for r in region_raw}

    # timeline: postings per day for everything that passes the other filters (not the period itself)
    days, undated, weekday = Counter(), 0, [0] * 7
    for j in data["jobs"]:
        if passes(j, "period"):
            d = (j.get("posted") or "")[:10]
            try:
                weekday[date.fromisoformat(d).weekday()] += 1
                days[d] += 1
            except ValueError:
                undated += 1
    rows = [j for j in data["jobs"] if passes(j)]
    ranked = _ranks(data, profile, w, cohort, co_vertical, inds, fits, today) if has_profile else {}
    if f.get("sort") == "fit" and has_profile:
        rows.sort(key=lambda j: (-ranked[j["id"]][0], -(_days_ago_key(j))))
    else:
        rows.sort(key=lambda j: j.get("posted") or "", reverse=True)
    page = []
    vocab = data.get("vocab", {}).get("skills", [])
    idf = skill_idf(data) if has_profile else {}
    for j in rows[offset:offset + limit]:
        card = {k: j.get(k) for k in ("id", "title", "company", "category", "level", "min_years", "location", "remote",
                                     "posted", "url", "salary", "mba", "visa", "snippet", "on_classic_board")}
        card["n_locations"] = len(j.get("locations") or [])
        links, seen = [], set()                           # one posting per location when they differ (the Apply menu)
        for loc in j.get("locations") or []:
            u = loc.get("url") if isinstance(loc, dict) else None
            if u and u not in seen:
                seen.add(u)
                links.append({"name": loc.get("name") or "Posting", "url": u})
        if len(links) > 1:
            card["apply"] = links[:40]
        card["regions"] = regs[j["id"]]
        if has_profile:
            b, why, score, top = fits[j["id"]]
            if b == "pivot" and j["category"] in w["categories"]:
                why = f"Pivot into your target field: {j['category']}"
            card.update(bucket=b, bucket_label=BUCKET_LABEL[b], reason=why,
                        skills_hit=[vocab[k] for k in top if k < len(vocab)], skill_score=round(score, 2),
                        reasons=ranked[j["id"]][1], closer=closer(j, fits[j["id"]], profile, vocab, idf))
        c = cohort.get(j["company"])
        if c:
            card["cohort"] = c
        page.append(card)
    out = {"total": len(rows), "offset": offset, "jobs": page, "has_profile": has_profile, "has_want": has_want(w),
           "counts": {k: dict(v) for k, v in counts.items()},
           "timeline": {"days": dict(days), "undated": undated, "weekday": weekday}}
    if with_path and has_profile:
        out["path"] = path(data, profile, w, fits, keep, vocab, skill_idf(data))
    return out


def _days_ago_key(j):
    p = j.get("posted") or ""
    try:
        return date.fromisoformat(p[:10]).toordinal()
    except ValueError:
        return 0


# ---------- companies, ranked by your search ----------

_neutral_fits = {"key": None, "fits": None}


def company_scores(data, profile, f, want=None, cohort=None, co_vertical=None):
    """How well each company's open roles fit you and match what you want, for ranking the Companies tab.

    Uses the same per-job score as Find a job (rank(): target company, field, level and vertical, how reachable the job
    is, skills, cohort warmth, freshness), over the jobs that pass your hard filters (sponsorship, location, avoid list,
    pay floor, and the Fit buttons when you have a profile). A company's score is its best role plus a share of its next
    two, plus a little for how many roles fit. Without a profile every job counts as equally reachable, so "What you
    want" alone still ranks companies.

    -> {job feed company name: {"score", "n": roles that pass, "fit": roles Ready or Reach and "ready": Ready (with a profile), "why": [...]}}"""
    import math
    has_profile = bool(profile and (profile.get("categories") or profile.get("skills")))
    if has_profile:
        fits = _fits(data, profile)
    else:
        if _neutral_fits["key"] != id(data):
            _neutral_fits.update(key=id(data), fits={j["id"]: ("reach", "", 0.0, []) for j in data["jobs"]})
        fits = _neutral_fits["fits"]
    w = clean_want(want)
    cohort = cohort or {}
    ranked = _ranks(data, profile or {}, w, cohort, co_vertical or {}, data.get("vocab", {}).get("inds", []), fits, date.today())
    regs = job_regions(data)
    want_regions, buckets = set(f.get("regions") or []), set(f.get("buckets") or [])
    visa = f.get("visa") or "any"
    per = {}
    for j in data["jobs"]:
        if blocked(j, w) or (visa == "not_no" and j.get("visa") == "Unlikely") or (visa == "likely" and j.get("visa") != "Likely"):
            continue
        if want_regions and not want_regions.intersection(regs[j["id"]]):
            continue
        b = fits[j["id"]][0]
        if has_profile and buckets and b not in buckets:
            continue
        x = per.setdefault(j["company"], {"scores": [], "n": 0, "fit": 0, "ready": 0, "why": Counter()})
        s, reasons = ranked[j["id"]]
        x["scores"].append(s)
        x["n"] += 1
        x["fit"] += has_profile and b in ("ready", "reach")
        x["ready"] += has_profile and b == "ready"
        for r in reasons:
            if not r.startswith(("Target field", "Target vertical", "Target company")):
                continue
            x["why"][r] += 1
    out = {}
    for co, x in per.items():
        top = sorted(x["scores"], reverse=True)[:3]
        score = sum(s * wt for s, wt in zip(top, (1.0, 0.5, 0.25))) + 0.15 * math.log2(1 + (x["fit"] if has_profile else x["n"]))
        out[co] = {"score": round(score, 3), "n": x["n"], "fit": x["fit"], "ready": x["ready"], "why": [r for r, _ in x["why"].most_common(2)]}
    return out
