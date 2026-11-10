"""Build the job board: probe boards, fetch jobs, classify, attach visa signals, write site/data.js.

    python pipeline/build.py              # reuse cached board map (fast refresh)
    python pipeline/build.py --reprobe    # rediscover every company's board

Inputs:  data/firms.json (run clean_firms.py first), data/seed_companies.txt,
         data/board_overrides.json. (USCIS H-1B files are no longer used.)
Outputs: site/data.js, data/boards.json (cache), data/build_report.txt
"""
import datetime
import json
import re
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ats
import deadline
import match_index
import places
import salary as salary_text
from classify import NON_US, advanced_degree_mentioned, classify, location_ok, stronger_mba

ROOT = Path(__file__).resolve().parent.parent
DATA, SITE, PUBLIC = ROOT / "data", ROOT / "site", ROOT / "public"
TODAY = datetime.date.today()
MAX_LISTED_LOCATIONS = 15

# Careers pages for the firms people ask about most; others fall back to a search link.
CAREERS_URL = {
    "McKinsey & Company": "https://www.mckinsey.com/careers",
    "Boston Consulting Group (BCG)": "https://careers.bcg.com",
    "Bain & Company": "https://www.bain.com/careers/",
    "Deloitte": "https://www.deloitte.com/us/en/careers.html",
    "PwC": "https://www.pwc.com/us/en/careers.html",
    "EY": "https://www.ey.com/en_us/careers",
    "EY-Parthenon": "https://www.ey.com/en_us/careers",
    "KPMG": "https://www.kpmguscareers.com",
    "Accenture": "https://www.accenture.com/us-en/careers",
    "Strategy&": "https://www.strategyand.pwc.com/gx/en/careers.html",
    "Oliver Wyman": "https://www.oliverwyman.com/careers.html",
    "Kearney": "https://www.kearney.com/careers",
    "L.E.K. Consulting": "https://www.lek.com/careers",
    "ZS Associates": "https://www.zs.com/careers",
}


# Account executive postings are usually one job posted once per territory ("Territory Account Executive, Atlanta", "..., Boston"). They are
# folded into one role with several locations (user decision 2026-11-09): the territory, state, country and language are taken out of the title.
_US_STATES = (r"alabama|alaska|arizona|arkansas|california|colorado|connecticut|delaware|florida|georgia|hawaii|idaho|illinois|indiana|iowa|"
              r"kansas|kentucky|louisiana|maine|maryland|massachusetts|michigan|minnesota|mississippi|missouri|montana|nebraska|nevada|"
              r"new hampshire|new jersey|new mexico|new york|north carolina|north dakota|ohio|oklahoma|oregon|pennsylvania|rhode island|"
              r"south carolina|south dakota|tennessee|texas|utah|vermont|virginia|washington|west virginia|wisconsin|wyoming")
_AE_GEO = re.compile(r"\b(" + _US_STATES + r"|east|west|north|south|central|northeast|southeast|northwest|southwest|midwest|coast|pacific|"
                     r"bay area|metro|remote|hybrid|nyc|usa|us|americas|dach|nordics|benelux|anz)\b", re.I)
_AE_WORD = re.compile(r"account executive|sales executive", re.I)
_AE_LANG = re.compile(r"^(spanish|mandarin|cantonese|korean|french|german|japanese|portuguese|vietnamese|arabic|hindi|russian|italian)$", re.I)


def fold_ae_title(title, location):
    """'Territory Account Executive, Atlanta' -> 'Territory Account Executive'. Falls back to the title when nothing is left."""
    t = re.sub(r"\([^)]*\)", " ", title)
    for place in re.split(r"[·;|]", location or ""):          # a territory title usually repeats a place in the posting's own location
        for part in {place.strip(), *(x.strip() for x in place.split(","))}:
            if len(part) >= 3 and part.lower() not in ("remote", "hybrid", "united states", "usa", "anywhere"):
                t = re.sub(r"\b" + re.escape(part) + r"\b", " ", t, flags=re.I)
    segs = [x.strip(" ,-–—/") for x in re.split(r"\s[-–—]\s|,", t)]
    segs = [x for x in segs if x]
    k = next((i for i, x in enumerate(segs) if _AE_WORD.search(x)), 0)
    keep = []
    for i, x in enumerate(segs):
        if i < k and len(x.split()) <= 2:
            continue                                                   # a leftover place before the role name
        if i != k and (_AE_LANG.match(x) or _AE_GEO.search(x) or NON_US.search(x) or re.fullmatch(r"[A-Za-z]{2}(\s*/\s*[A-Za-z]{2})*", x)):
            continue
        keep.append(x)
    out = re.sub(r"^[A-Z]{2}\s+(?=[A-Z])", "", ", ".join(keep))                                        # a stray state code before the role name
    out = re.sub(r"(account executive)\s+(?:" + NON_US.pattern + r")\s*$", r"\1", out, flags=re.I)   # "... Account Executive Mexico"
    out = re.sub(r"\s+", " ", out).strip(" ,-–—")
    return out or title.strip()


def read_seed():
    names = []
    for line in (DATA / "seed_companies.txt").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            names.append(line)
    return list(dict.fromkeys(names))


def load_json(path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def norm_url(url):
    """The apply link as the board shows it: https, and a working host (see LINK_HOST_FIXES)."""
    url = "https://" + url[7:] if url.startswith("http://") else url
    for bad_host, good_host in LINK_HOST_FIXES.items():
        url = url.replace("://" + bad_host + "/", "://" + good_host + "/", 1)
    # Ashby changes the case of the firm's name in its links (crusoe -> Crusoe, Nov 9); the link works either way, so keep one
    # spelling or "What's new" reports the same posting as both new and gone.
    return re.sub(r"(://jobs\.ashbyhq\.com/)([^/?#]+)", lambda m: m.group(1) + m.group(2).lower(), url, count=1)


# The "What's new" tab is a running comparison with this update: every update since then is kept, so the tab shows all roles added
# and removed since this date (user decision 2026-11-02). Move it forward to start a fresh comparison.
CHANGES_SINCE = "2026-10-23"


# Hosts whose own certificate is broken for browsers (every browser, Safari included, blocks the page); the same page works on the
# replacement host. Found with pipeline/check_links_safari.py.
LINK_HOST_FIXES = {"westmonroe.com": "www.westmonroe.com"}      # the bare domain's certificate expired
# Firms that hire MBAs into their consulting ranks even when a posting does not say "MBA" (user decision 2026-10-27). Their strategy and
# management-consulting roles at the Associate to Manager rungs go in the MBA roles tab; technology-implementation, risk and tax
# titles stay in Other roles.
MBA_RECRUITING_FIRMS = {"Altman Solon", "Oliver Wyman", "Baringa Partners", "Boston Consulting Group (BCG)", "Charles River Associates", "ClearView Healthcare Partners",
                        "ECG Management Consultants", "EY", "EY-Parthenon", "Huron Consulting Group", "L.E.K. Consulting",
                        "KPMG", "West Monroe Partners"}
MBA_FIRM_CATEGORIES = {"Strategy Consulting", "Corp Strategy"}
MBA_FIRM_NOT_TITLE = re.compile(r"\b(SAP|Oracle|Workday|ServiceNow|Salesforce|Microsoft|Cloud|Data|Cyber|Cybersecurity|Security|Technology|"
                                r"Technical|Application|Engineer|Architect|Developer|Software|Infrastructure|Risk|Compliance|Audit|Tax|Financial Due Diligence|"
                                r"Financial Crimes?|Mobility|Maximo|UKG|Cost Segregation|SALT)\b", re.I)
# The Big 4 post many generic "Senior Associate" titles that are not strategy work, so there a title must also say what the work is.
MBA_BIG4_TITLE = re.compile(r"strateg|consult|advisory|transformation|operations|growth|M&A|deal|transaction|planning|pricing|business", re.I)
MBA_BIG4 = {"KPMG", "EY"}
# Early-career roles are left off the board: the posting asks for this many years of experience or fewer and never mentions an MBA or
# another degree beyond a bachelor's (user decision 2026-10-27; e.g. Inverto "Consultant, Procurement").
EARLY_CAREER_MAX_YEARS = 2
# ...except at tech companies (their strategy / business-operations roles often ask for 2 years yet are MBA-targeted), and at
# strategy firms where the Consultant / Senior Consultant rung is where post-MBA hires start (checked against the postings,
# e.g. BCG Inverto Senior Consultant, Oliver Wyman Senior Consultant, Altman Solon Consultant, Baringa Senior Consultant).
EARLY_CAREER_EXEMPT_FIRMS = {"Boston Consulting Group (BCG)", "Altman Solon", "Oliver Wyman", "Baringa Partners",
                             "L.E.K. Consulting", "Charles River Associates", "ClearView Healthcare Partners"}
# Roles whose stated pay tops out at this much or less are left off, unless the posting names the MBA (user decision 2026-10-27:
# "MBA roles start around $130K"; $110K was chosen because posted ranges are often a junior band or base pay only).
LOW_PAY_CEILING = 110000
ENTRY_LEVEL_ON_BOARD = False   # pre-MBA ladder titles (user decision 2026-10-23: no Entry-level filter, not shown)
# Manager / Senior Manager roles at consulting firms are left off the board unless they mention the MBA (user decision 2026-10-23).
MANAGERS_NEED_MBA = True
MANAGER_MAX_YEARS_KEPT = 4      # ...or the posting asks for fewer than 5 years of experience
MANAGER_RUNG_CATEGORIES = {"Strategy Consulting", "Tech & Digital Consulting", "Transformation / PMO", "Corp Strategy"}

# Firms whose "Vice President" is a mid-level rung, about a senior associate (user decision 2026-10-23).
VP_FIRMS = {"Alix Partners"}


def hand_kept(company, title):
    """The entry for a role listed in data/early_career_keep.json (company = feed name, title_contains), else None. Such a role skips the
    entry-level, early-career, manager and low-pay rules, and the title filter in classify.py. An entry may carry "mba": "firm"."""
    t = title.lower()
    return next((k for k in load_json(DATA / "early_career_keep.json", {}).get("keep", [])
                 if k["company"] == company and k["title_contains"].lower() in t), None)


def title_worth_opening(title):
    """Cheap pre-check so firm-specific boards only open detail pages for plausible roles."""
    t = title.lower()
    if any(k["title_contains"].lower() in t for k in load_json(DATA / "early_career_keep.json", {}).get("keep", [])):
        return True
    return classify({"title": title, "location": "United States", "description": ""}, True) is not None


def discover(name, cached, custom=None):
    """-> (platform, slug, jobs) or None. Uses the cached board when we have one."""
    cfg = (custom or {}).get(name)
    if cfg:
        jobs = ats.run_custom(cfg, want=title_worth_opening)
        slug = next((cfg[k] for k in ("slug", "tenant", "board", "sub", "host", "base") if cfg.get(k)), name)
        return (cfg["platform"], slug, jobs) if jobs is not None else None
    if cached and name in cached:
        c = cached[name]
        if c is None or c["platform"] not in ats.FETCHERS:      # e.g. "standing" placeholders are not downloadable
            return None
        jobs = ats.FETCHERS[c["platform"]](c["slug"])
        return (c["platform"], c["slug"], jobs) if jobs is not None else None
    return ats.probe(name)


# Words that must not appear anywhere in the public page's source (the firm directory and everything about the firm database).
PUBLIC_BANNED = ["School-facilitated", "school_facilitated", "database", "visa_stance", "8-31-2026", "stated policy", "PRIVATE", "tab-firms", "firmTable"]


def make_public_html(html):
    """Public copy of the page: the firm directory markup and code are removed, not just hidden.

    Private-only blocks in site/index.html are wrapped in <!--PRIVATE-->...<!--/PRIVATE--> (HTML) or
    /*PRIVATE*/ ... /*/PRIVATE*/ (JavaScript).
    """
    out = re.sub(r"<!--PRIVATE-->.*?<!--/PRIVATE-->", "", html, flags=re.S)
    out = re.sub(r"/\*PRIVATE\*/.*?/\*/PRIVATE\*/", "", out, flags=re.S)
    # The page code still refers to PUBLIC / firms in places that only exist in the private blocks; none should remain.
    leaked = [w for w in PUBLIC_BANNED if w in out]
    if leaked:
        sys.exit(f"public page still contains private wording {leaked}: wrap that code in PRIVATE markers in site/index.html")
    return out


_BARE_REMOTE = re.compile(r"\s*(?:fully\s+)?remote(?:\s*[-–(]?\s*(?:us|usa|u\.s\.|united states|north america)\)?)?\s*", re.I)


def split_locations(loc):
    """-> (places, remote_ok). Splits on ; | and ' · ' (not commas, which separate city from state).

    A bare "Remote" listed next to real places is not a place of its own: it says the posting for those places can be
    done remotely. It is returned as the remote_ok flag instead. (Otherwise the Apply menu offers a "Remote" link that
    just opens one of the city postings.) A posting that is only remote keeps a single "Remote" place.
    """
    parts = [p.strip() for p in re.split(r"\s*[;|]\s*|\s+·\s+", loc or "") if p.strip()]
    kept = [p for p in dict.fromkeys(parts) if location_ok(p)]
    if not kept:
        return [(loc or "").strip() or "Location not listed"], False
    real = [p for p in kept if not _BARE_REMOTE.fullmatch(p)]
    if real:
        return real, len(real) != len(kept)
    return ["Remote"], True


# Shown on the public page when the only support for a label comes from the firm database, which is never named there.
GENERIC_REASON = {"Unlikely": "Sponsorship unlikely based on available information",
                  "Likely": "Sponsorship signals found",
                  "Case-by-case": "Sponsorship may be considered on a case-by-case basis"}


def visa_label(job_tags, sheet_stance):
    """Combine the signals into one label: Likely, Case-by-case, Unlikely or Unknown.
    Returns (label, reasons, public_reasons).

    Signals: what the posting says (sponsors / does not sponsor / offers immigration support / needs clearance or
    citizenship) and the firm database's stated stance. Past USCIS H-1B filings are deliberately not used: the rules and
    costs have changed since the FY2021-23 data. The firm database feeds the label, but `public_reasons` leaves out
    anything that came from it, so the public page shows the label and posting evidence only.
    """
    reasons = []  # (text, came_from_firm_database)

    def done(label):
        public = [t for t, from_db in reasons if not from_db]
        if not public and label in GENERIC_REASON:
            public = [GENERIC_REASON[label]]
        return label, [t for t, _ in reasons], public

    if job_tags["requires_clearance"]:
        reasons.append(("Requires U.S. citizenship or a security clearance", False))
    if job_tags["says_no_sponsorship"]:
        reasons.append(("Posting says no sponsorship", False))
    if sheet_stance == "No":
        reasons.append(("Firm says it does not sponsor", True))
    if reasons:
        return done("Unlikely")
    if job_tags["says_sponsors"]:
        reasons.append(("Posting mentions sponsorship", False))
    if sheet_stance in ("Yes", "Yes (STEM)"):
        reasons.append(("Firm says it sponsors", True))
    if reasons:
        return done("Likely")
    # Softer evidence: the firm says "case by case", or the posting offers immigration support (a benefits line such as
    # "in-house immigration support for foreign nationals"). Either one makes the role Case-by-case, never Likely.
    if sheet_stance == "Case By Case":
        reasons.append(("Firm sponsors case by case", True))
    if job_tags.get("immigration_support"):
        reasons.append(("Posting mentions immigration support", False))
    if reasons:
        return done("Case-by-case")
    reasons.append(("No sponsorship info found", False))
    return done("Unknown")


def main():
    reprobe = "--reprobe" in sys.argv
    firms = load_json(DATA / "firms.json", [])
    if not firms:
        sys.exit("data/firms.json missing - run pipeline/clean_firms.py first")
    seed = read_seed()
    overrides = load_json(DATA / "board_overrides.json", {})  # name -> null (wrong match) or {"platform","slug"}
    cached = {} if reprobe else load_json(DATA / "boards.json", {})
    for k, v in overrides.items():
        cached[k] = v
    custom = {k: v for k, v in load_json(DATA / "custom_boards.json", {}).items() if not k.startswith("_")}

    sheet = {f["name"]: f for f in firms}
    stance_over = {k: v for k, v in load_json(DATA / "stance_overrides.json", {}).items() if not k.startswith("_")}  # newer hiring-policy news that outranks the firm database
    targets = [(f["name"], "consulting") for f in firms]
    consulting_names = set(sheet)
    targets += [(n, "tech") for n in seed if n not in consulting_names]
    # Firms with their own job system that are not in the firm database (e.g. Cartesian).
    listed = {n for n, _ in targets}
    targets += [(n, c.get("group", "consulting")) for n, c in custom.items() if n not in listed]

    raw_cache = DATA / "raw_fetch.json"
    if "--cached" in sys.argv and raw_cache.exists():
        print("Using cached job feeds from the last fetch (--cached)")
        stored = json.loads(raw_cache.read_text(encoding="utf-8"))
        found = [tuple(stored[n]) if stored.get(n) else None for n, _ in targets]
    else:
        print(f"Fetching {len(targets)} companies ({len(firms)} firms + {len(targets) - len(firms)} seed)...")
        with ThreadPoolExecutor(max_workers=8) as ex:
            found = list(ex.map(lambda t: discover(t[0], cached, custom), targets))
        raw_cache.write_text(json.dumps({n: list(h) if h else None for (n, _), h in zip(targets, found)},
                                        ensure_ascii=False), encoding="utf-8")

    # Standing roles typed in by hand for firms whose careers pages cannot be read automatically (data/standing_roles.json).
    standing = {}
    for r in load_json(DATA / "standing_roles.json", {}).get("roles", []):
        standing.setdefault(r["company"], []).append({
            "title": r["title"], "url": r["url"], "location": r["location"], "posted": "", "salary": None,
            "description": f"{r['description']} (Standing posting, last checked {r['checked']}.)", "mba": r.get("mba"), "deadline": r.get("deadline"), "source": "standing"})
    for i, (name, _) in enumerate(targets):
        if name in standing:
            hit = found[i]
            found[i] = (hit[0], hit[1], list(hit[2]) + standing[name]) if hit else ("standing", "careers page", standing[name])

    boards = {}
    for (name, _), hit in zip(targets, found):
        boards[name] = {"platform": hit[0], "slug": hit[1]} if hit else None
    (DATA / "boards.json").write_text(json.dumps(boards, indent=1), encoding="utf-8")

    # One entry per role: postings with the same company + title are merged, each keeping its own location and apply link.
    roles = {}
    matcher = match_index.Matcher()
    match_counts = {}
    dropped_managers = Counter()
    dropped_early = []
    dropped_lowpay = []
    for (name, group), hit in zip(targets, found):
        if not hit:
            continue
        platform, slug, jobs = hit
        splits = [(other, re.compile(rx, re.I)) for other, rx in (custom.get(name, {}).get("split") or {}).items()]
        for j in jobs:
            kept = hand_kept(name, j["title"])         # hand-picked role (data/early_career_keep.json): the rules below must not drop it
            tags = classify(j, group == "consulting", allow_vp=name in VP_FIRMS, keep=kept)
            if not tags:
                continue
            if kept and kept.get("mba") and not tags["mba_kind"]:
                tags["mba_kind"] = kept["mba"]     # e.g. "firm": listed for MBAs on the school's job board, so it goes in the MBA roles tab
            if tags["seniority"] == "Entry-level" and kept:
                tags["seniority"] = "Sr. Associate" if re.search(r"\b(senior|sr\.?)\b", j["title"], re.I) else "Associate"
            if tags["seniority"] == "Entry-level" and not ENTRY_LEVEL_ON_BOARD:
                continue                           # "Associate Consultant", "Consultant I" and similar pre-MBA rungs
            if (j.get("source") != "standing" and group == "consulting" and name not in EARLY_CAREER_EXEMPT_FIRMS
                    and not kept
                    and tags["min_years"] is not None and tags["min_years"] <= EARLY_CAREER_MAX_YEARS
                    and not tags["mba_kind"] and not advanced_degree_mentioned(j.get("description"))):
                dropped_early.append(f"{name} | {j['title'].strip()} | {tags['min_years']} yrs")
                continue
            if j.get("source") == "standing":
                tags["mba_kind"] = j.get("mba")    # stated by hand for standing roles (null = not an MBA-pipeline role)
            # Manager and Senior Manager rungs at consulting firms are not where MBAs are hired in. Keep one only when it asks
            # for fewer than 5 years of experience, or (years not stated) the posting itself names the MBA. "MBA" in the title
            # always counts; a posting that asks for 5+ years does not, even if it prefers an MBA.
            if (MANAGERS_NEED_MBA and group == "consulting" and tags["seniority"] in ("Manager", "Sr. Manager")
                    and tags["mba_kind"] != "title" and not kept):
                yrs = tags["min_years"]
                too_senior = yrs is not None and yrs > MANAGER_MAX_YEARS_KEPT
                unproven = yrs is None and not tags["mba_kind"] and tags["category"] in MANAGER_RUNG_CATEGORIES
                if too_senior or unproven:
                    dropped_managers[name] += 1
                    continue
            # One feed can carry a sub-brand (EY-Parthenon, Strategy&): credit those titles to the sub-brand.
            company = next((other for other, rx in splits if rx.search(j["title"].strip())), name)
            if (company in MBA_RECRUITING_FIRMS and not tags["mba_kind"] and tags["category"] in MBA_FIRM_CATEGORIES
                    and tags["seniority"] in ("Associate", "Sr. Associate", "Manager") and not MBA_FIRM_NOT_TITLE.search(j["title"])
                    and (company not in MBA_BIG4 or MBA_BIG4_TITLE.search(j["title"]))):
                tags["mba_kind"] = "firm"
            stance = stance_over.get(company) or (sheet[company]["visa_stance"] if company in sheet else (sheet[name]["visa_stance"] if name in sheet else None))
            shown_title = j["title"].strip()
            if tags["category"] == "Account Executive":
                shown_title = fold_ae_title(shown_title, j.get("location") or "")
            gkey = (company, re.sub(r"\s+", " ", shown_title.lower()), tags["category"],
                    None if tags["category"] == "Account Executive" else tags["seniority"])
            places_here, remote_here = split_locations(j["location"])
            # a pay range written in the posting text fills in when the job feed has no structured one
            sal, sal_several = (j["salary"], False) if j["salary"] else salary_text.from_text(j.get("description"))
            apply_url = norm_url(j["url"])           # firms' feeds sometimes give plain http
            if (j.get("source") != "standing" and not kept and isinstance(sal, dict) and sal.get("max") and sal["max"] <= LOW_PAY_CEILING
                    and tags["mba_kind"] not in ("title", "required", "preferred")):
                dropped_lowpay.append(f"{name} | {j['title'].strip()} | ${sal['min']//1000}K-${sal['max']//1000}K")
                continue
            entries = [{"name": p, "url": apply_url, "posted": j["posted"], "salary": sal,
                        **({"remote": True} if remote_here else {}), **({"salary_several": True} if sal_several else {})}
                       for p in places_here]
            dl = deadline.extract(j.get("description"), j.get("posted"), j.get("deadline"))
            if gkey in roles:
                role = roles[gkey]
                have = {(e["name"], e["url"]) for e in role["locations"]}
                role["locations"] += [e for e in entries if (e["name"], e["url"]) not in have]
                role["deadline"] = deadline.merge(role["deadline"], dl)
                role["mba"] = stronger_mba(role["mba"], tags["mba_kind"])
                continue
            # The firm database feeds the label. Its own wording stays out of the public reasons (see visa_label).
            label, reasons, public_reasons = visa_label(tags, stance)
            roles[gkey] = {
                "visa_reasons_public": public_reasons,
                "company": company,
                "group": group,
                "title": shown_title,
                "locations": entries,
                "category": tags["category"],
                "seniority": tags["seniority"],
                "min_years": tags["min_years"],
                "mba": tags["mba_kind"],   # "title" | "required" | "preferred" | "firm" | None
                "review": tags["review"],
                "visa": label,
                "visa_reasons": reasons,
                "deadline": dl,
                "source": platform,
                "snippet": (j.get("description") or "")[:280],
                "_m": matcher.counts(j["title"], j.get("description") or ""),     # skill and industry terms for resume matching (not sent in data.js)
            }

    jobs_out = []
    per_company = Counter()
    firm_open = Counter()
    for role in roles.values():
        locs = role["locations"]
        names = list(dict.fromkeys(e["name"] for e in locs))
        n_locations = len(names)
        remote_ok = any(e.get("remote") for e in locs)
        cities = places.place_labels(names)           # computed from every location, before any trimming below
        if remote_ok and places.REMOTE_LABEL not in cities:
            cities.append(places.REMOTE_LABEL)
        # The same place can have several postings (separate openings, each with its own link). Number them so the
        # Apply menu does not list two identical lines.
        urls_by_name = {}
        for e in locs:
            urls_by_name.setdefault(e["name"], [])
            if e["url"] not in urls_by_name[e["name"]]:
                urls_by_name[e["name"]].append(e["url"])
        for e in locs:
            urls = urls_by_name[e["name"]]
            if len(urls) > 1:
                e["opening"] = urls.index(e["url"]) + 1
        salaries = {json.dumps(e["salary"], sort_keys=True) for e in locs if e["salary"]}
        if n_locations > MAX_LISTED_LOCATIONS and len({e["url"] for e in locs}) == 1:
            # One posting that lists hundreds of places (e.g. every office): keep a sample for display, the true count
            # for the badge. Roles with a different apply link per location keep every location.
            locs, names = locs[:MAX_LISTED_LOCATIONS], names[:MAX_LISTED_LOCATIONS]
            role["locations"] = locs
        role.update({
            "id": len(jobs_out),
            "url": locs[0]["url"],                     # stable key for the My list tracker
            "location": " · ".join(names),
            "n_locations": n_locations,
            "remote_ok": remote_ok,                    # at least one posting can be done remotely
            "cities": cities,
            "posted": max((e["posted"] for e in locs if e["posted"]), default=""),
            "salary": next((e["salary"] for e in locs if e["salary"]), None),
            "salary_varies": len(salaries) > 1 or any(e.get("salary_several") for e in locs),
        })
        match_counts[role["url"]] = role.pop("_m")
        jobs_out.append(role)
        per_company[role["company"]] += 1
        if role["group"] == "consulting":
            firm_open[role["company"]] += 1

    firms_out = []
    for f in firms:
        firms_out.append({
            **f,
            "careers_url": CAREERS_URL.get(f["name"]),
            "board_url": None,
            "open_roles": firm_open.get(f["name"], 0),
        })

    # ---- what changed since the previous download (feeds the "What's new" tab) ----
    # A posting counts as new only if its link was not in the previous download at all, and as gone only if its link is no longer in
    # this one, so roles that appear or vanish because OUR rules changed are not reported. Compared on links, not titles.
    # Hand-typed standing roles (McKinsey, Bain: they hire year round) are never reported as new or gone (user decision 2026-11-02).
    history_path = DATA / "history.json"
    history = load_json(history_path, {})
    feed_date = datetime.date.fromtimestamp(raw_cache.stat().st_mtime).isoformat()
    # --record: count a cached download as a new one, to redo the history after fixing the download (e.g. a refetched firm).
    if "--cached" not in sys.argv or "--record" in sys.argv:
        cur_raw = {norm_url(j["url"]) for hit in found if hit for j in hit[2]}
        tracked = [r for r in jobs_out if r.get("source") != "standing"]
        cur_board = [{"urls": sorted({e["url"] for e in r["locations"]}), "company": r["company"], "title": r["title"],
                      "visa": r["visa"], "mba": bool(r["mba"])} for r in tracked]
        if history.get("raw_urls") is not None:
            prev_raw = set(history["raw_urls"])
            added = [r["url"] for r in tracked if not any(e["url"] in prev_raw for e in r["locations"])]
            gone = [{k: b[k] for k in ("company", "title", "visa", "mba", "urls")} for b in history.get("board", [])
                    if not any(u in cur_raw for u in b["urls"])]
            if added or gone:
                batches = history.setdefault("batches", [])
                if batches and batches[0]["date"] == feed_date:
                    batches[0]["added"] = sorted(set(batches[0]["added"]) | set(added))
                    batches[0]["removed"] += [g for g in gone if g not in batches[0]["removed"]]
                else:
                    batches.insert(0, {"date": feed_date, "since": history.get("date"), "added": added, "removed": gone})
        history.update({"date": feed_date, "raw_urls": sorted(cur_raw), "board": cur_board})
        history_path.write_text(json.dumps(history, ensure_ascii=False), encoding="utf-8")
    changes = [b for b in history.get("batches", []) if (b.get("since") or b["date"]) >= CHANGES_SINCE]

    payload = {
        "generated": datetime.date.fromtimestamp(raw_cache.stat().st_mtime).isoformat(),   # when the job feeds were downloaded
        "changes": changes, "changes_since": CHANGES_SINCE,
        "stats": {"companies_scanned": len(targets), "companies_with_board": sum(1 for b in boards.values() if b),
                  "jobs": len(jobs_out)},
        "jobs": sorted(jobs_out, key=lambda j: j["posted"] or "", reverse=True),
        "firms": firms_out,
    }
    SITE.mkdir(exist_ok=True)
    # Full version (local use): keeps the per-role visa details. The firm directory has been removed from the page, so no firm records are written.
    full_jobs = [{k: v for k, v in j.items() if k != "visa_reasons_public"} for j in payload["jobs"]]
    (SITE / "data.js").write_text("window.BOARD_DATA = " + json.dumps({**payload, "jobs": full_jobs, "firms": []}, ensure_ascii=False) + ";",
                                  encoding="utf-8")

    # Public version: job listings only. No firm directory. The visa label is the same as the full version's, but
    # the page shows only public-source evidence for it and never names the firm database.
    PUBLIC.mkdir(exist_ok=True)
    public_jobs = []
    for j in payload["jobs"]:
        p = {k: v for k, v in j.items() if k != "visa_reasons_public"}
        p["visa_reasons"] = j["visa_reasons_public"]
        public_jobs.append(p)
    public_payload = {"public": True, "generated": payload["generated"], "changes": changes, "changes_since": CHANGES_SINCE,
                      "stats": {"companies_scanned": payload["stats"]["companies_scanned"],
                                "companies_with_board": payload["stats"]["companies_with_board"], "jobs": len(public_jobs)},
                      "jobs": public_jobs, "firms": []}
    (PUBLIC / "data.js").write_text("window.BOARD_DATA = " + json.dumps(public_payload, ensure_ascii=False) + ";", encoding="utf-8")
    (PUBLIC / "index.html").write_text(make_public_html((SITE / "index.html").read_text(encoding="utf-8")), encoding="utf-8")
    index_bytes = match_index.write_index(match_counts, matcher, SITE, PUBLIC)         # loaded by the page only when a resume is added

    lines = [f"Built {TODAY}: {len(jobs_out)} jobs from {payload['stats']['companies_with_board']} of "
             f"{len(targets)} companies.",
             "By category: " + str(dict(Counter(j['category'] for j in jobs_out).most_common())),
             "By visa label: " + str(dict(Counter(j['visa'] for j in jobs_out))),
             "Review-flagged: " + str(sum(j['review'] for j in jobs_out)),
             f"Low-pay roles left off (stated top of range <= ${LOW_PAY_CEILING//1000}K, no MBA mention): {len(dropped_lowpay)}",
             *["  " + x for x in dropped_lowpay],
             f"Early-career roles left off (<= {EARLY_CAREER_MAX_YEARS} years, no MBA or advanced degree): {len(dropped_early)}",
             *["  " + x for x in dropped_early],
             f"Manager / Senior Manager roles left off (no MBA mention): {sum(dropped_managers.values())} " + str(dict(dropped_managers.most_common(8))),
             "", "Consulting firms with a board (verify these are the right companies):"]
    for (name, group), hit in zip(targets, found):
        if hit and group == "consulting":
            lines.append(f"  {name:<42} {hit[0]:<11} {hit[1]:<28} jobs={len(hit[2])} matched={per_company.get(name, 0)}")
    lines += ["", "Top companies by matches:"] + [f"  {n:<30} {c}" for n, c in per_company.most_common(25)]
    (DATA / "build_report.txt").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines[:5]))


if __name__ == "__main__":
    main()
