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

def fit(job, p):
    """-> (bucket, reason). p: {years, mba, categories}."""
    mine = p.get("categories") or []
    jc = job["category"]
    if jc in mine:
        field = "strong"
    elif any(jc in cats.ADJACENT.get(c, ()) for c in mine):
        field = "partial"
    else:
        field = "none"
    years = max(0, int(p.get("years") or 0))
    mba = bool(p.get("mba"))
    eff = years + (2 if mba else 0)
    lvl = job["level"]
    asks = job["min_years"] if job.get("min_years") is not None else cats.LEVEL_YEARS[lvl]
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


def skill_match(job, skills):
    """(score 0-1, top matched skill indexes) from the job's weighted skill terms."""
    total = sum(w for _, w in job.get("sk", []))
    hit = [(k, w) for k, w in job.get("sk", []) if k in skills]
    got = sum(w for _, w in hit)
    return (got / total) ** 0.5 if total else 0.0, [k for k, _ in sorted(hit, key=lambda x: -x[1])[:3]]


# ---------- search ----------

_fit_cache = {"key": None, "fits": None}


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


def _days_ago(posted, today):
    try:
        return (today - date.fromisoformat(posted[:10])).days
    except (TypeError, ValueError):
        return None


def search(data, profile, f, cohort=None, offset=0, limit=40):
    """f: {categories, buckets, levels, posted, q, mba, hide_unlikely, warm, sort}. Returns counts and one page."""
    has_profile = bool(profile and (profile.get("categories") or profile.get("skills")))
    fits = _fits(data, profile) if has_profile else {}
    cohort = cohort or {}
    today = date.today()
    want_cats, want_buckets, want_levels = set(f.get("categories") or []), set(f.get("buckets") or []), set(f.get("levels") or [])
    q = (f.get("q") or "").strip().lower()
    posted = int(f.get("posted") or 0)
    p_from, p_to = (f.get("from") or "")[:10], (f.get("to") or "")[:10]     # a period picked on the timeline (ISO dates)
    hidden = set(f.get("hidden") or [])                                      # companies the user chose to hide

    def passes(j, skip=None):
        if hidden and j["company"] in hidden:
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
        if f.get("hide_unlikely") and j.get("visa") == "Unlikely":
            return False
        if f.get("warm") and not cohort.get(j["company"]):
            return False
        return True

    counts = {"categories": Counter(j["category"] for j in data["jobs"] if passes(j, "categories")),
              "levels": Counter(j["level"] for j in data["jobs"] if passes(j, "levels")),
              "buckets": Counter(fits[j["id"]][0] for j in data["jobs"] if passes(j, "buckets")) if has_profile else {}}
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
    order = {b: i for i, b in enumerate(BUCKETS)}
    if f.get("sort") == "fit" and has_profile:
        rows.sort(key=lambda j: (order[fits[j["id"]][0]], -fits[j["id"]][2], -(_days_ago_key(j))))
    else:
        rows.sort(key=lambda j: j.get("posted") or "", reverse=True)
    page = []
    vocab = data.get("vocab", {}).get("skills", [])
    for j in rows[offset:offset + limit]:
        card = {k: j.get(k) for k in ("id", "title", "company", "category", "level", "min_years", "location", "remote",
                                     "posted", "url", "salary", "mba", "visa", "snippet", "on_classic_board")}
        card["n_locations"] = len(j.get("locations") or [])
        if has_profile:
            b, why, score, top = fits[j["id"]]
            card.update(bucket=b, bucket_label=BUCKET_LABEL[b], reason=why,
                        skills_hit=[vocab[k] for k in top if k < len(vocab)], skill_score=round(score, 2))
        c = cohort.get(j["company"])
        if c:
            card["cohort"] = c
        page.append(card)
    return {"total": len(rows), "offset": offset, "jobs": page, "has_profile": has_profile,
            "counts": {k: dict(v) for k, v in counts.items()},
            "timeline": {"days": dict(days), "undated": undated, "weekday": weekday}}


def _days_ago_key(j):
    p = j.get("posted") or ""
    try:
        return date.fromisoformat(p[:10]).toordinal()
    except ValueError:
        return 0
