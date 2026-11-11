"""Company database: every company the cohort is tied to, plus the S&P 500, with vertical, description,
headquarters and US offices. It's a directory: no job fetching here.

    python3 company-db/companies.py targets     # cohort companies (cloud database) + S&P 500 -> targets table
    python3 company-db/companies.py wikidata    # match each target to Wikidata (cached, resumable)
    python3 company-db/companies.py wikipedia   # two-sentence descriptions for tier 1-2 (cached, resumable)
    python3 company-db/companies.py offices     # US offices seen in our job postings (data/all_jobs.json)
    python3 company-db/companies.py batches N   # write research batches for agents (tier 1-2, N per batch)
    python3 company-db/companies.py muse-push   # put every unresearched company in D1's company_research table for Muse
    python3 company-db/companies.py muse-pull   # merge what Muse researched (status 'done') into research/muse.json, then merge
                                                # (both take --local to use the `wrangler dev` copy of D1)
    python3 company-db/companies.py merge       # build the companies / names / offices tables from everything
    python3 company-db/companies.py stats

Output: data/companies.db (SQLite, git-ignored because the target list comes from classmates' connections).
Hand fixes go in company-db/overrides.json; research agents' results land in data/company-db/research/*.json.
Priority tiers: 1 = cohort company with 2+ contacts or a classmate worked there, 2 = S&P 500, 3 = the rest.
"""
import html
import json
import re
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "linkedin-ingest"))
sys.path.insert(0, str(REPO / "cohort-board"))
from ingest import rules  # noqa: E402

DB = REPO / "data" / "companies.db"
WORK = REPO / "data" / "company-db"
RESEARCH = WORK / "research"
OVERRIDES = Path(__file__).resolve().parent / "overrides.json"
UA = "cohort-board-companies/0.1 (private student research tool)"

VERTICALS = {
    "Consulting": ["Strategy consulting", "Management & operations consulting", "Big Four & accounting",
                   "Economic & litigation consulting", "Technology consulting", "Restructuring & turnaround", "Other consulting"],
    "Financial Services": ["Investment banking", "Commercial & retail banking", "Private equity", "Venture capital",
                           "Hedge funds & asset management", "Insurance", "Fintech & payments", "Exchanges & financial data",
                           "Real estate investment", "Other financial services"],
    "Technology": ["Big tech", "Software & SaaS", "AI", "Semiconductors & hardware", "Internet & marketplaces",
                   "Cybersecurity", "IT services", "Other technology"],
    "Consumer & Retail": ["Consumer packaged goods", "Retail & e-commerce", "Restaurants & hospitality",
                          "Apparel & luxury", "Beverages", "Other consumer"],
    "Healthcare & Life Sciences": ["Pharma & biotech", "Medical devices", "Healthcare providers",
                                   "Health insurance & services", "Digital health"],
    "Industrials & Manufacturing": ["Aerospace & defense", "Industrial machinery", "Chemicals & materials",
                                    "Construction & engineering", "Automotive", "Other industrials"],
    "Energy & Climate": ["Oil & gas", "Utilities & power", "Renewables & climate tech", "Other energy"],
    "Agriculture & Food": ["Agribusiness & ag tech", "Food production", "Other agriculture"],
    "Media, Entertainment & Telecom": ["Media & publishing", "Entertainment & gaming", "Telecommunications",
                                       "Advertising & marketing"],
    "Transportation & Logistics": ["Airlines", "Ride-hailing & mobility", "Logistics & shipping", "Other transportation"],
    "Real Estate": ["Real estate development & services", "Proptech"],
    "Education": ["Universities & schools", "Edtech"],
    "Government & Nonprofit": ["Government", "Nonprofit & NGO", "International organizations"],
    "Other": ["Other"],
}
KINDS = ["employer", "school", "recruiter", "student_org", "not_a_company"]

# GICS sector (S&P 500 table) -> vertical, sub-vertical by sub-industry keywords.
GICS = {
    "Information Technology": "Technology", "Communication Services": "Media, Entertainment & Telecom",
    "Financials": "Financial Services", "Health Care": "Healthcare & Life Sciences",
    "Consumer Staples": "Consumer & Retail", "Consumer Discretionary": "Consumer & Retail",
    "Industrials": "Industrials & Manufacturing", "Materials": "Industrials & Manufacturing",
    "Energy": "Energy & Climate", "Utilities": "Energy & Climate", "Real Estate": "Real Estate",
}

# Keyword rules over name + Wikidata industries + descriptions. First match wins; order matters.
RULES = [
    (r"universit|college|school of|business school|\bschool\b|academy", "Education", "Universities & schools"),
    (r"strategy consult|management consult", "Consulting", "Strategy consulting"),
    (r"accounting|audit|professional services?", "Consulting", "Big Four & accounting"),
    (r"economic consult|litigation consult|expert witness", "Consulting", "Economic & litigation consulting"),
    (r"consult", "Consulting", "Other consulting"),
    (r"investment bank", "Financial Services", "Investment banking"),
    (r"private equity|buyout", "Financial Services", "Private equity"),
    (r"venture capital", "Financial Services", "Venture capital"),
    (r"hedge fund|asset management|investment management|alternative invest", "Financial Services", "Hedge funds & asset management"),
    (r"insurance|insurer|reinsur", "Financial Services", "Insurance"),
    (r"payment|fintech|financial technology", "Financial Services", "Fintech & payments"),
    (r"stock exchange|financial data|credit rating", "Financial Services", "Exchanges & financial data"),
    (r"\bbank|banking", "Financial Services", "Commercial & retail banking"),
    (r"financ|invest", "Financial Services", "Other financial services"),
    (r"pharmac|biotech|drug|life science", "Healthcare & Life Sciences", "Pharma & biotech"),
    (r"medical device|medical equipment", "Healthcare & Life Sciences", "Medical devices"),
    (r"hospital|health ?care provider|health system|clinic", "Healthcare & Life Sciences", "Healthcare providers"),
    (r"health", "Healthcare & Life Sciences", "Health insurance & services"),
    (r"artificial intelligence|\bai\b|machine learning", "Technology", "AI"),
    (r"semiconductor|computer hardware|electronics", "Technology", "Semiconductors & hardware"),
    (r"cyber ?security|computer security", "Technology", "Cybersecurity"),
    (r"software|saas|cloud computing", "Technology", "Software & SaaS"),
    (r"e-commerce|online marketplace|internet", "Technology", "Internet & marketplaces"),
    (r"information technology|\bit services|technology", "Technology", "Other technology"),
    (r"agri|crop|seed|farm", "Agriculture & Food", "Agribusiness & ag tech"),
    (r"food|meat|dairy", "Agriculture & Food", "Food production"),
    (r"beverage|brew|soft drink|wine|spirits", "Consumer & Retail", "Beverages"),
    (r"consumer goods|fast-moving|personal care|household", "Consumer & Retail", "Consumer packaged goods"),
    (r"restaurant|hotel|hospitality|coffee", "Consumer & Retail", "Restaurants & hospitality"),
    (r"apparel|fashion|luxury|clothing|footwear", "Consumer & Retail", "Apparel & luxury"),
    (r"retail|supermarket|department store", "Consumer & Retail", "Retail & e-commerce"),
    (r"aerospace|defen[cs]e|arms industry", "Industrials & Manufacturing", "Aerospace & defense"),
    (r"automo|car manufactur|vehicle", "Industrials & Manufacturing", "Automotive"),
    (r"chemical|materials|glass|steel|mining", "Industrials & Manufacturing", "Chemicals & materials"),
    (r"construction|engineering", "Industrials & Manufacturing", "Construction & engineering"),
    (r"manufactur|industrial|machinery|conglomerate", "Industrials & Manufacturing", "Other industrials"),
    (r"renewable|solar|wind power|climate|clean energy|sustainab", "Energy & Climate", "Renewables & climate tech"),
    (r"petroleum|oil|natural gas", "Energy & Climate", "Oil & gas"),
    (r"utility|electric power|electricity", "Energy & Climate", "Utilities & power"),
    (r"telecom", "Media, Entertainment & Telecom", "Telecommunications"),
    (r"advertis|marketing", "Media, Entertainment & Telecom", "Advertising & marketing"),
    (r"video game|entertainment|film|music|sport", "Media, Entertainment & Telecom", "Entertainment & gaming"),
    (r"media|publish|news|magazine|broadcast", "Media, Entertainment & Telecom", "Media & publishing"),
    (r"airline", "Transportation & Logistics", "Airlines"),
    (r"ride|mobility", "Transportation & Logistics", "Ride-hailing & mobility"),
    (r"logistic|shipping|freight|transport", "Transportation & Logistics", "Logistics & shipping"),
    (r"real estate|property", "Real Estate", "Real estate development & services"),
    (r"government|agency|ministry|department of", "Government & Nonprofit", "Government"),
    (r"non-?profit|charit|foundation|ngo", "Government & Nonprofit", "Nonprofit & NGO"),
]
RULES = [(re.compile(rx, re.I), v, s) for rx, v, s in RULES]
NON_EMPLOYER = [(re.compile(r"recruit|staffing|talent acquisition|executive search|headhunt", re.I), "recruiter"),
                (re.compile(r"\b(club|association|society|ventures? club|big red)\b", re.I), "student_org")]


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def db():
    DB.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    con.executescript("""
    CREATE TABLE IF NOT EXISTS targets (
      id TEXT PRIMARY KEY, name TEXT NOT NULL, tier INTEGER NOT NULL, contacts INTEGER DEFAULT 0, classmates INTEGER DEFAULT 0,
      worked INTEGER DEFAULT 0, sp500 INTEGER DEFAULT 0, norms TEXT, gics_sector TEXT, gics_sub TEXT, sp_hq TEXT, updated_at TEXT);
    CREATE TABLE IF NOT EXISTS companies (
      id TEXT PRIMARY KEY, name TEXT NOT NULL, kind TEXT, vertical TEXT, sub_vertical TEXT,
      description TEXT, short_description TEXT, website TEXT, wikidata_id TEXT, wikipedia_title TEXT,
      hq_city TEXT, hq_region TEXT, hq_country TEXT, hq_lat REAL, hq_lon REAL,
      employees INTEGER, ownership TEXT, ticker TEXT, parent TEXT, founded INTEGER,
      tier INTEGER, sp500 INTEGER, researched INTEGER DEFAULT 0, confidence TEXT, sources TEXT, notes TEXT, updated_at TEXT);
    CREATE TABLE IF NOT EXISTS names (alias TEXT PRIMARY KEY, company_id TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS offices (
      company_id TEXT NOT NULL, city TEXT, region TEXT, country TEXT, metro TEXT, lat REAL, lon REAL,
      is_hq INTEGER DEFAULT 0, source TEXT, source_url TEXT, job_count INTEGER);
    """)
    return con


def slug(name):
    return re.sub(r"[^a-z0-9]+", "-", (rules.normalize_company(name) or name).lower()).strip("-")


def http(url, data=None, accept="application/json", tries=4):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, data=data, headers={"User-Agent": UA, "Accept": accept})
            with urllib.request.urlopen(req, timeout=120) as r:
                return r.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and i < tries - 1:
                wait = int(e.headers.get("Retry-After") or 0) or 10 * (i + 1)
                print(f"  {e.code}, waiting {wait}s", flush=True)
                time.sleep(min(wait, 120))
                continue
            raise
        except (urllib.error.URLError, TimeoutError):
            if i < tries - 1:
                time.sleep(10 * (i + 1))
                continue
            raise


def sparql(q):
    body = urllib.parse.urlencode({"query": q}).encode()
    res = json.loads(http("https://query.wikidata.org/sparql", body, "application/sparql-results+json"))
    time.sleep(1)
    return [{k: v["value"] for k, v in b.items()} for b in res["results"]["bindings"]]


def cache(name):
    p = WORK / f"{name}.json"
    return json.loads(p.read_text()) if p.exists() else {}


def save_cache(name, obj):
    WORK.mkdir(parents=True, exist_ok=True)
    tmp = WORK / f"{name}.tmp"
    tmp.write_text(json.dumps(obj, indent=0, ensure_ascii=False))
    tmp.replace(WORK / f"{name}.json")


# ---------------------------------------------------------------- targets

def cohort_companies():
    """{root norm: {name, contacts, classmates, worked, norms}} from the cohort's cloud database (through the cohort API,
    cohort-board/.api), read only."""
    import store
    db = store.make_store()
    reg, snap = db.registry(), db.snapshot()
    disp = {c["company_norm"]: c["display_name"] for c in reg["companies"]}
    parent = {c["company_norm"]: c["parent_norm"] for c in reg["companies"] if c["parent_norm"]}
    aliases = {a["alias"]: a["company_norm"] for a in reg["aliases"]}

    def root(n):
        n = aliases.get(n) or aliases.get(rules.compress(n)) or n
        return parent.get(n, n)
    out = defaultdict(lambda: {"contacts": 0, "who": set(), "worked": set(), "norms": set()})
    keyed = {r["connector_id"] for r in snap["contact_buckets"]}
    for x in snap["counts"]:                 # older count rows; fingerprinted contacts are counted below
        if x["connector_id"] in keyed:
            continue
        r = out[root(x["company_norm"])]; r["contacts"] += x["count"]; r["who"].add(x["connector_id"]); r["norms"].add(x["company_norm"])
    for x in snap["contact_buckets"]:
        r = out[root(x["company_norm"])]; r["contacts"] += x["n"]; r["who"].add(x["connector_id"]); r["norms"].add(x["company_norm"])
    for x in snap["positions"]:
        if x["company_norm"]:
            r = out[root(x["company_norm"])]; r["worked"].add(x["person_id"]); r["who"].add(x["person_id"]); r["norms"].add(x["company_norm"])
    alias_of = defaultdict(set)
    for a, n in aliases.items():
        alias_of[root(n)].add(a)
    return {n: {"name": disp.get(n) or n.title(), "contacts": r["contacts"], "classmates": len(r["who"]),
                "worked": len(r["worked"]),
                "norms": sorted(r["norms"] | {n} | alias_of[n] | {rules.normalize_company(disp.get(n) or "") or n})}
            for n, r in out.items()}


def sp500():
    """[{name, sector, sub, hq}] from Wikipedia's S&P 500 table, cached in data/company-db/sp500.html."""
    p = WORK / "sp500.html"
    if not p.exists():
        WORK.mkdir(parents=True, exist_ok=True)
        p.write_text(http("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies", accept="text/html"))
    t = p.read_text()
    t = t[t.find('id="constituents"'):]
    t = t[:t.find("</table>")]
    out = []
    for row in t.split("<tr")[2:]:
        cells = [html.unescape(re.sub(r"<[^>]+>", "", c)).strip() for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
        if len(cells) >= 6:
            out.append({"name": cells[1], "sector": cells[2], "sub": cells[3], "hq": cells[4]})
    return out


SP_KEY_STOP = re.compile(r"\b(inc|corp|corporation|company|co|plc|holdings|group|the|ltd|platforms|incorporated|class [ab])\b")


def sp_key(name):
    n = rules.normalize_company(name) or name.lower()
    return re.sub(r"[^a-z0-9]", "", SP_KEY_STOP.sub("", n))


def cmd_targets():
    con = db()
    co = cohort_companies()
    sp = sp500()
    print(f"cohort companies: {len(co)} | S&P 500 rows: {len(sp)}")
    by_key = {sp_key(r["name"]): n for n, r in co.items()}
    by_key.update({sp_key(rules.compress(n)): n for n in co})
    for n, r in co.items():                      # every alias the cohort database knows (Citigroup -> Citi, Alphabet -> Google)
        for a in r["norms"]:
            by_key.setdefault(sp_key(a), n)
    con.execute("DELETE FROM targets")
    seen = set()
    for n, r in sorted(co.items(), key=lambda kv: (-kv[1]["contacts"], kv[0])):
        tier = 1 if (r["contacts"] >= 2 or r["worked"]) else 3
        base = tid = slug(r["name"]) or "company"
        k = 2
        while tid in seen:
            tid, k = f"{base}-{k}", k + 1
        seen.add(tid)
        con.execute("INSERT OR REPLACE INTO targets VALUES (?,?,?,?,?,?,0,?,NULL,NULL,NULL,?)",
                    (tid, r["name"], tier, r["contacts"], r["classmates"], r["worked"], json.dumps(r["norms"]), now()))
    hits = 0
    for s in sp:
        n = by_key.get(sp_key(s["name"]))
        if n:
            hits += 1
            tid = con.execute("SELECT id FROM targets WHERE norms LIKE ?", (f'%"{n}"%',)).fetchone()[0]
            con.execute("UPDATE targets SET sp500=1, tier=MIN(tier, 2), gics_sector=?, gics_sub=?, sp_hq=? WHERE id=?",
                        (s["sector"], s["sub"], s["hq"], tid))
        else:
            tid = slug(s["name"])
            norm = rules.normalize_company(s["name"]) or tid
            con.execute("INSERT OR IGNORE INTO targets VALUES (?,?,2,0,0,0,1,?,?,?,?,?)",
                        (tid, s["name"], json.dumps([norm]), s["sector"], s["sub"], s["hq"], now()))
    con.commit()
    print(f"S&P 500 companies already in cohort list: {hits}")
    for t, n in con.execute("SELECT tier, COUNT(*) FROM targets GROUP BY tier"):
        print(f"  tier {t}: {n}")


# ---------------------------------------------------------------- wikidata

ORG = re.compile(r"compan|business|enterprise|firm|bank|corporation|conglomerate|organi[sz]ation|fund|insurer|subsidiar|"
                 r"startup|manufacturer|retail|airline|agency|consultan|partnership|universit|school|college|institut|"
                 r"holding|chain|publisher|brand|nonprofit|foundation|investment|studio|laborator", re.I)


def search_names(name):
    """Search strings for one company: its own name, then without a trailing descriptor."""
    out = [name]
    short = re.sub(r"\s*\(.*?\)\s*", " ", name).strip()
    short = re.sub(r",?\s+(Inc\.?|LLC|L\.L\.C\.|Ltd\.?|Corp\.?|Corporation|Co\.|plc|LLP|LP|Group)$", "", short, flags=re.I).strip()
    if short and short != name:
        out.append(short)
    return out


def cmd_wikidata(limit=None):
    con = db()
    cached = cache("wikidata")          # {target id: {"queries": [...], "hits": [[rank, qid]], "details": {qid: {...}}}}
    todo = [dict(r) for r in con.execute("SELECT * FROM targets ORDER BY tier, contacts DESC")
            if cached.get(r["id"], {}).get("queries") != search_names(r["name"])]
    if limit:
        todo = todo[:limit]
    print(f"wikidata: {len(cached)} cached, {len(todo)} to look up", flush=True)
    for i in range(0, len(todo), 20):
        chunk = todo[i:i + 20]
        queries = {t["id"]: search_names(t["name"]) for t in chunk}
        terms = sorted({q for qs in queries.values() for q in qs})
        hits = sparql("""SELECT ?name ?item ?rank WHERE { VALUES ?name { %s }
          SERVICE wikibase:mwapi { bd:serviceParam wikibase:endpoint "www.wikidata.org"; wikibase:api "EntitySearch";
            mwapi:search ?name; mwapi:language "en"; mwapi:limit "6". ?item wikibase:apiOutputItem mwapi:item.
            ?rank wikibase:apiOrdinal true. } }""" % " ".join(json.dumps(s) for s in terms))
        by_term = defaultdict(list)
        for h in hits:
            by_term[h["name"]].append((int(h["rank"]), h["item"].rsplit("/", 1)[1]))
        ids = sorted({q for v in by_term.values() for _, q in v})
        det = details(ids) if ids else {}
        for t in chunk:
            cand = []
            for k, q in enumerate(queries[t["id"]]):
                cand += [[k * 10 + r, qid] for r, qid in sorted(by_term.get(q, []))]
            cached[t["id"]] = {"queries": queries[t["id"]], "hits": cand,
                               "details": {qid: det[qid] for _, qid in cand if qid in det}}
        save_cache("wikidata", cached)
        print(f"  {min(i + 20, len(todo))}/{len(todo)}", flush=True)


def details(ids):
    out = {}
    for i in range(0, len(ids), 60):
        rows = sparql("""SELECT ?item (SAMPLE(?lab) AS ?label) ?desc ?links ?article
          (GROUP_CONCAT(DISTINCT ?typeL; separator="|") AS ?types) (GROUP_CONCAT(DISTINCT ?indL; separator="|") AS ?inds)
          (SAMPLE(?hqL) AS ?hq) (SAMPLE(?hqCountryL) AS ?hqCountry) (SAMPLE(?hqRegionL) AS ?hqRegion) (SAMPLE(?coord) AS ?hqCoord)
          (MAX(?emp) AS ?employees) (SAMPLE(?site) AS ?website) (SAMPLE(?tick) AS ?ticker) (SAMPLE(?parL) AS ?parent)
          (MIN(YEAR(?inc)) AS ?founded) (SAMPLE(?dis) AS ?dissolved) WHERE {
          VALUES ?item { %s } ?item wikibase:sitelinks ?links .
          OPTIONAL { ?item rdfs:label ?lab FILTER(lang(?lab) IN ("en", "mul")) }
          OPTIONAL { ?item schema:description ?desc FILTER(lang(?desc)="en") }
          OPTIONAL { ?article schema:about ?item ; schema:isPartOf <https://en.wikipedia.org/> }
          OPTIONAL { ?item wdt:P31 ?t . ?t rdfs:label ?typeL FILTER(lang(?typeL) IN ("en", "mul")) }
          OPTIONAL { ?item wdt:P452 ?ind . ?ind rdfs:label ?indL FILTER(lang(?indL) IN ("en", "mul")) }
          OPTIONAL { ?item wdt:P159 ?h . ?h rdfs:label ?hqL FILTER(lang(?hqL) IN ("en", "mul"))
                     OPTIONAL { ?h wdt:P625 ?coord } OPTIONAL { ?h wdt:P17 ?hc . ?hc rdfs:label ?hqCountryL FILTER(lang(?hqCountryL) IN ("en", "mul")) }
                     OPTIONAL { ?h wdt:P131 ?hr . ?hr rdfs:label ?hqRegionL FILTER(lang(?hqRegionL) IN ("en", "mul")) } }
          OPTIONAL { ?item wdt:P1128 ?emp } OPTIONAL { ?item wdt:P856 ?site }
          OPTIONAL { ?item p:P414 ?ex . ?ex pq:P249 ?tick }
          OPTIONAL { ?item wdt:P749 ?par . ?par rdfs:label ?parL FILTER(lang(?parL) IN ("en", "mul")) }
          OPTIONAL { ?item wdt:P571 ?inc } OPTIONAL { ?item wdt:P576 ?dis }
        } GROUP BY ?item ?desc ?links ?article""" % " ".join("wd:" + q for q in ids[i:i + 60]))
        for r in rows:
            out.setdefault(r["item"].rsplit("/", 1)[1], r)
    return out


def norm_label(s):
    return re.sub(r"[^a-z0-9]", "", (rules.normalize_company(s or "") or "").lower())


def pick(entry, name):
    """Best Wikidata match for a target, or None. Organisation-like, not dissolved, and the name must resemble the label."""
    want = norm_label(name)
    cands = []
    for rank, qid in sorted(entry["hits"]):
        r = entry["details"].get(qid)
        if not r or r.get("dissolved"):
            continue
        if not ORG.search(r.get("types", "") + " " + r.get("desc", "")):
            continue
        lab = norm_label(r.get("label", ""))
        close = bool(lab) and (lab == want or lab.startswith(want) or want.startswith(lab) or want in lab)
        if not close:
            continue
        cands.append((rank, int(r["links"]), qid, r))
    if not cands:
        return None
    top = cands[0]
    big = max(cands, key=lambda c: c[1])
    return (big if big[1] > 3 * top[1] + 5 else top)[3] | {"id": (big if big[1] > 3 * top[1] + 5 else top)[2]}


# ---------------------------------------------------------------- wikipedia

def cmd_wikipedia(max_tier=2):
    con = db()
    wd = cache("wikidata")
    wp = cache("wikipedia")
    ov = overrides()
    todo = []
    for t in con.execute("SELECT * FROM targets WHERE tier <= ? ORDER BY tier, contacts DESC", (max_tier,)):
        o = ov.get(t["id"], {})
        if "wikipedia_title" in o:
            title = o["wikipedia_title"]
        else:
            m = pick(wd[t["id"]], t["name"]) if t["id"] in wd else None
            title = urllib.parse.unquote(m["article"].rsplit("/", 1)[1]) if m and m.get("article") else None
        if title and title not in wp:
            todo.append(title)
    print(f"wikipedia: {len(wp)} cached, {len(todo)} to fetch", flush=True)
    for k, title in enumerate(todo):
        try:
            d = json.loads(http("https://en.wikipedia.org/api/rest_v1/page/summary/" + urllib.parse.quote(title.replace(" ", "_"), safe="")))
            wp[title] = {"extract": d.get("extract"), "description": d.get("description"),
                         "url": d.get("content_urls", {}).get("desktop", {}).get("page")}
        except urllib.error.HTTPError as e:
            wp[title] = {"error": e.code}
        time.sleep(0.5)
        if k % 25 == 24:
            save_cache("wikipedia", wp)
            print(f"  {k + 1}/{len(todo)}", flush=True)
    save_cache("wikipedia", wp)


# ---------------------------------------------------------------- offices from postings

def cmd_offices():
    import regions
    con = db()
    jobs = json.loads((REPO / "data" / "all_jobs.json").read_text())["jobs"]
    by_co = defaultdict(Counter)
    for j in jobs:
        for r in regions.regions_for([l["name"] if isinstance(l, dict) else l for l in j.get("locations") or []], j.get("remote")):
            by_co[j["company"]][r] += 1
    xy = {r["name"]: (r["lat"], r["lon"], r["kind"]) for r in regions.REGIONS}
    names = {}
    for t in con.execute("SELECT id, norms FROM targets"):
        for n in json.loads(t["norms"]):
            names[n] = t["id"]
            names[rules.compress(n)] = t["id"]
    out = {}
    for co, cnt in by_co.items():
        n = rules.normalize_company(co)
        tid = names.get(n) or names.get(rules.compress(n or ""))
        if not tid:
            continue
        if tid in out:                       # several posting names for one company: keep the bigger
            if sum(o["jobs"] for o in out[tid]) >= sum(cnt.values()):
                continue
        out[tid] = [{"metro": m, "jobs": c, "lat": xy.get(m, (None,))[0], "lon": xy.get(m, (None, None))[1],
                     "kind": xy.get(m, (0, 0, None))[2]} for m, c in cnt.most_common() if m in xy and xy[m][2] == "metro"]
    save_cache("posting_offices", out)
    print(f"offices from postings for {len(out)} target companies")


# ---------------------------------------------------------------- research batches

def research_item(t, wd, po):
    """What a researcher gets for one company: its names, an automatic Wikidata guess (may be wrong), where it posts jobs."""
    m = pick(wd[t["id"]], t["name"]) if t["id"] in wd else None
    return {
        "id": t["id"], "name": t["name"], "linkedin_names": json.loads(t["norms"]), "sp500": bool(t["sp500"]),
        "gics": [t["gics_sector"], t["gics_sub"]] if t["gics_sector"] else None, "sp500_hq": t["sp_hq"],
        "wikidata_guess": None if not m else {k: m.get(k) for k in ("id", "label", "desc", "hq", "hqRegion", "hqCountry", "inds", "website", "employees")},
        "offices_seen_in_our_job_postings": [o["metro"] for o in po.get(t["id"], [])][:15],
    }


def cmd_batches(size=25, prefix="batch", tiers=(1, 2)):
    con = db()
    wd = cache("wikidata")
    po = cache("posting_offices")
    done = {r["id"] for f in RESEARCH.glob("*.json") for r in json.loads(f.read_text())} if RESEARCH.exists() else set()
    rows = [dict(t) for t in con.execute("SELECT * FROM targets ORDER BY tier, contacts DESC, name") if t["tier"] in tiers]
    rows = [t for t in rows if t["id"] not in done]
    bdir = WORK / "batches"
    bdir.mkdir(parents=True, exist_ok=True)
    for f in bdir.glob(f"{prefix}_*.json"):
        f.unlink()
    for b in range(0, len(rows), size):
        items = [research_item(t, wd, po) for t in rows[b:b + size]]
        (bdir / f"{prefix}_{b // size + 1:02d}.json").write_text(json.dumps(items, indent=1, ensure_ascii=False))
    print(f"{len(rows)} companies in {(len(rows) + size - 1) // size} batches of {size} -> {bdir}")


# ---------------------------------------------------------------- Muse: research through the cohort database (D1)

MUSE_FILE = RESEARCH / "muse.json"


def _d1(target):
    sys.path.insert(0, str(REPO / "cohort-api"))
    import sync

    def query(sql):
        import subprocess
        r = subprocess.run(["npx", "wrangler", "d1", "execute", sync.D1_NAME, target, "--json", "--command", sql],
                           cwd=REPO / "cohort-api", capture_output=True, text=True)
        out = r.stdout
        try:
            return json.loads(out[out.find("["):out.rfind("]") + 1])[0]["results"]
        except (ValueError, IndexError, KeyError):
            raise sync.SyncError((r.stderr or out)[-800:].strip() or "wrangler failed")
    return sync, query


def cmd_muse_push(target="--remote"):
    """Add every company nobody has researched to company_research (status 'todo'). Rows already there are kept."""
    sync, _ = _d1(target)
    con = db()
    wd, po = cache("wikidata"), cache("posting_offices")
    done = {r["id"] for f in RESEARCH.glob("*.json") for r in json.loads(f.read_text())} if RESEARCH.exists() else set()
    rows = [dict(t) for t in con.execute("SELECT * FROM targets ORDER BY tier, contacts DESC, name") if t["id"] not in done]
    at = now()
    vals = []
    for t in rows:
        item = research_item(t, wd, po)
        info = {k: v for k, v in item.items() if k not in ("id", "name")}
        vals.append(f"({sync.q(t['id'])},{sync.q(t['name'])},{sync.q(json.dumps(info, ensure_ascii=False))},{int(t['tier'] or 3)},'todo',{sync.q(at)})")
    stmts = ["INSERT INTO company_research (id, name, info, tier, status, added_at) VALUES\n" + ",\n".join(vals[i:i + 50]) +
             "\nON CONFLICT (id) DO NOTHING;" for i in range(0, len(vals), 50)]
    if stmts:
        sync.run_sql(stmts, f"company_research: {len(vals)} companies to research", target)
    print(f"{len(vals)} unresearched companies offered to Muse (rows already in the table were left alone).")


def cmd_muse_pull(target="--remote"):
    """Merge Muse's finished rows (status 'done') into research/muse.json, rebuild the directory, mark them 'merged'.
    A result that isn't usable JSON for its company is marked 'needs_fix' with the reason, for Muse to redo."""
    sync, query = _d1(target)
    rows = query("SELECT id, name, result FROM company_research WHERE status = 'done'")
    have = {r["id"]: r for r in json.loads(MUSE_FILE.read_text())} if MUSE_FILE.exists() else {}
    good, bad = [], []
    for r in rows:
        try:
            res = json.loads(r["result"] or "")
            if not isinstance(res, dict):
                raise ValueError("result is not a JSON object")
        except ValueError as e:
            bad.append((r["id"], f"result isn't valid JSON ({e})"))
            continue
        res["id"] = r["id"]
        notes = [res.get("notes")] if res.get("notes") else []
        if res.get("kind") not in KINDS:
            res.pop("kind", None)
        if res.get("vertical") not in VERTICALS:
            notes.append(f"vertical {res.pop('vertical', None)!r} isn't on the list")
            res.pop("sub_vertical", None)
        elif res.get("sub_vertical") not in VERTICALS[res["vertical"]]:
            notes.append(f"sub_vertical {res.pop('sub_vertical', None)!r} isn't under {res['vertical']}")
        if notes:
            res["notes"] = "; ".join(str(n) for n in notes)
        have[r["id"]] = res
        good.append(r["id"])
    if good:
        RESEARCH.mkdir(parents=True, exist_ok=True)
        MUSE_FILE.write_text(json.dumps(list(have.values()), indent=1, ensure_ascii=False))
        cmd_merge()
    at = sync.q(now())
    stmts = [f"UPDATE company_research SET status = 'merged', error = NULL WHERE id IN ({','.join(sync.q(i) for i in good[k:k + 200])});"
             for k in range(0, len(good), 200)]
    stmts += [f"UPDATE company_research SET status = 'needs_fix', error = {sync.q(msg)}, researched_at = COALESCE(researched_at, {at}) "
              f"WHERE id = {sync.q(i)};" for i, msg in bad]
    if stmts:
        sync.run_sql(stmts, f"company_research: {len(good)} merged, {len(bad)} need fixing", target)
    print(f"Merged {len(good)} researched compan{'y' if len(good) == 1 else 'ies'}; {len(bad)} marked needs_fix." +
          ("" if good else " Nothing new to merge."))


# ---------------------------------------------------------------- merge

def overrides():
    return {k: v for k, v in json.loads(OVERRIDES.read_text()).items() if not k.startswith("_")} if OVERRIDES.exists() else {}


def classify(text, gics=None):
    if gics and gics[0] in GICS:
        v = GICS[gics[0]]
        sub = next((s for rx, vv, s in RULES if vv == v and rx.search(gics[1] or "")), None)
        return v, sub or VERTICALS[v][-1]
    for rx, v, s in RULES:
        if rx.search(text):
            return v, s
    return "Other", "Other"


def parse_coord(c):
    m = re.match(r"Point\(([-\d.]+) ([-\d.]+)\)", c or "")
    return (float(m.group(2)), float(m.group(1))) if m else (None, None)


def verify_research_qids(research):
    """Fetch Wikidata details for the IDs agents supplied (some typed from memory) and flag ones whose label
    doesn't resemble the company name. Cached in data/company-db/research_qids.json."""
    rq = cache("research_qids")
    want = sorted({r["wikidata_id"] for r in research.values() if r.get("wikidata_id")} - set(rq))
    if want:
        rq.update(details(want))
        for q in want:
            rq.setdefault(q, {"_missing": True})
    for r in research.values():
        q = r.get("wikidata_id")
        if not q or q not in rq:
            continue
        label = rq[q].get("label") or ""
        toks = lambda x: {t for t in re.findall(r"[a-z0-9]+", (x or "").lower()) if len(t) >= 3 or x.isupper()}
        initials = lambda x: "".join(w[0] for w in re.findall(r"[A-Za-z]+", x or "")).lower()
        names = [r.get("name"), r["id"].replace("-", " ")]
        ok = bool(label) and any(toks(label) & toks(n) or initials(label) == (n or "").lower().replace(" ", "")
                                 or initials(n) == label.lower() or norm_label(n)[:4] == norm_label(label)[:4] for n in names)
        rq[q]["_mismatch"] = not ok
        if not ok:
            print(f"  wikidata mismatch: {r['id']} ({r.get('name')}) -> {q} = {rq[q].get('label')!r}")
    save_cache("research_qids", rq)
    return rq


def cmd_merge():
    import regions
    con = db()
    wd, wp, po, ov = cache("wikidata"), cache("wikipedia"), cache("posting_offices"), overrides()
    research = {}
    for f in sorted(RESEARCH.glob("*.json")) if RESEARCH.exists() else []:
        for r in json.loads(f.read_text()):
            research[r["id"]] = r
    metro_xy = {r["name"]: (r["lat"], r["lon"]) for r in regions.REGIONS}
    rq = verify_research_qids(research)
    con.execute("DELETE FROM companies"); con.execute("DELETE FROM names"); con.execute("DELETE FROM offices")
    stats = Counter()
    for t in con.execute("SELECT * FROM targets").fetchall():
        tid, o, rs = t["id"], ov.get(t["id"], {}), research.get(t["id"], {})
        m = pick(wd[tid], t["name"]) if tid in wd else None
        if "wikidata_id" in o or "wikidata_id" in rs:          # a person or agent decided; null means "no match"
            want = o.get("wikidata_id", rs.get("wikidata_id"))
            if want and rq.get(want, {}).get("_mismatch") and "wikidata_id" not in o:
                pass                                                # agent's ID is for something else: keep the automatic match
            else:
                m = ((wd.get(tid, {}).get("details", {}).get(want) or rq.get(want) or {}) | {"id": want}) if want else None
        m = m or {}
        art = urllib.parse.unquote(m["article"].rsplit("/", 1)[1]).replace("_", " ") if m.get("article") else None
        art = o.get("wikipedia_title", art)
        w = wp.get(art, {}) if art else {}
        text = " ".join([t["name"], m.get("inds", ""), m.get("desc", ""), m.get("types", ""), w.get("description") or ""])
        kind = rs.get("kind") or o.get("kind")
        if not kind:
            kind = next((k for rx, k in NON_EMPLOYER if rx.search(t["name"])), None) or \
                ("school" if re.search(r"universit|college|school", t["name"] + " " + m.get("types", ""), re.I) else "employer")
        v, s = classify(text, [t["gics_sector"], t["gics_sub"]] if t["gics_sector"] else None)
        if kind == "school":
            v, s = "Education", "Universities & schools"
        v, s = rs.get("vertical") or o.get("vertical") or v, rs.get("sub_vertical") or o.get("sub_vertical") or s
        if v not in VERTICALS:
            v = "Other"
        if s not in VERTICALS[v]:
            s = VERTICALS[v][-1]
        hq = rs.get("hq") or {}
        lat, lon = parse_coord(m.get("hqCoord"))
        hq_city = hq.get("city") or m.get("hq") or (t["sp_hq"] or "").split(",")[0] or None
        hq_region = hq.get("region") or m.get("hqRegion") or ((t["sp_hq"] or "").split(",")[1].strip() if "," in (t["sp_hq"] or "") else None)
        hq_country = hq.get("country") or m.get("hqCountry") or ("United States" if t["sp_hq"] else None)
        if hq.get("city") and hq.get("city") != m.get("hq"):
            lat = lon = None
            mreg = regions.regions_for([f'{hq["city"]}, {hq.get("region") or ""}'])
            if mreg and mreg[0] in metro_xy:
                lat, lon = metro_xy[mreg[0]]
        desc = rs.get("description") or o.get("description") or w.get("extract")
        emp = rs.get("employees") or m.get("employees")
        try:
            emp = int(float(emp)) if emp else None
        except (TypeError, ValueError):
            emp = None
        sources = [x for x in [f"https://www.wikidata.org/wiki/{m['id']}" if m.get("id") else None, w.get("url")] if x]
        sources += rs.get("sources") or []
        conf = rs.get("confidence") or ("high" if m.get("id") and int(m.get("links") or 0) >= 10 else "medium" if m.get("id") else "low")
        con.execute("INSERT INTO companies VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
            tid, rs.get("name") or o.get("name") or t["name"], kind, v, s, desc, rs.get("short_description") or m.get("desc"),
            rs.get("website") or m.get("website"), m.get("id"), art, hq_city, hq_region, hq_country, lat, lon, emp,
            rs.get("ownership") or ("public" if (m.get("ticker") or t["sp500"]) else None), rs.get("ticker") or m.get("ticker"),
            rs.get("parent") or m.get("parent"), int(m["founded"]) if (m.get("founded") or "").lstrip("-").isdigit() else None,
            t["tier"], t["sp500"], int(bool(rs)), conf, json.dumps(sources), rs.get("notes"), now()))
        for n in json.loads(t["norms"]):
            con.execute("INSERT OR IGNORE INTO names VALUES (?, ?)", (n, tid))
            con.execute("INSERT OR IGNORE INTO names VALUES (?, ?)", (rules.compress(n), tid))
        seen = set()
        if hq_city:
            mreg = regions.regions_for([f"{hq_city}, {hq_region or ''}"]) if (hq_country or "").startswith("United States") else []
            con.execute("INSERT INTO offices VALUES (?,?,?,?,?,?,?,1,?,?,NULL)", (
                tid, hq_city, hq_region, hq_country, mreg[0] if mreg else None, lat, lon,
                "research" if hq.get("city") else "wikidata" if m.get("hq") else "s&p 500 list", None))
            if mreg:
                seen.add(mreg[0])
        for off in rs.get("us_offices") or []:
            mreg = regions.regions_for([f'{off.get("city", "")}, {off.get("region", "")}'])
            metro = mreg[0] if mreg and mreg[0] in metro_xy else None
            if metro in seen and metro:
                continue
            seen.add(metro)
            xy = metro_xy.get(metro, (None, None))
            con.execute("INSERT INTO offices VALUES (?,?,?,?,?,?,?,0,'research',?,NULL)",
                        (tid, off.get("city"), off.get("region"), "United States", metro, xy[0], xy[1], off.get("source_url")))
        for off in po.get(tid, []):
            if off["metro"] in seen:
                con.execute("UPDATE offices SET job_count=? WHERE company_id=? AND metro=?", (off["jobs"], tid, off["metro"]))
                continue
            seen.add(off["metro"])
            con.execute("INSERT INTO offices VALUES (?,NULL,NULL,'United States',?,?,?,0,'job postings',NULL,?)",
                        (tid, off["metro"], off["lat"], off["lon"], off["jobs"]))
        stats[kind] += 1
        stats["wikidata" if m.get("id") else "no wikidata"] += 1
        stats["researched" if rs else "not researched"] += 1
    con.commit()
    print("merged:", dict(stats))


def cmd_stats():
    con = db()
    q = lambda s: [tuple(r) for r in con.execute(s).fetchall()]
    print("targets by tier:", q("SELECT tier, COUNT(*) FROM targets GROUP BY tier"))
    print("companies:", q("SELECT COUNT(*) FROM companies")[0][0])
    print("by kind:", q("SELECT kind, COUNT(*) FROM companies GROUP BY kind ORDER BY 2 DESC"))
    for tier in (1, 2, 3):
        r = q(f"""SELECT COUNT(*), SUM(wikidata_id IS NOT NULL), SUM(description IS NOT NULL), SUM(hq_city IS NOT NULL),
                  SUM(researched), SUM((SELECT COUNT(*) FROM offices o WHERE o.company_id=c.id AND is_hq=0) > 0)
                  FROM companies c WHERE tier={tier} AND kind='employer'""")[0]
        print(f"tier {tier} employers: {r[0]} | wikidata {r[1]} | description {r[2]} | HQ {r[3]} | researched {r[4]} | has non-HQ offices {r[5]}")
    print("by vertical (employers):")
    for v, n in q("SELECT vertical, COUNT(*) FROM companies WHERE kind='employer' GROUP BY 1 ORDER BY 2 DESC"):
        print(f"  {n:5}  {v}")
    print("offices:", q("SELECT source, COUNT(*) FROM offices GROUP BY 1"))


if __name__ == "__main__":
    cmd, *args = sys.argv[1:] or ["stats"]
    {"targets": cmd_targets, "wikidata": lambda: cmd_wikidata(int(args[0]) if args else None), "wikipedia": lambda: cmd_wikipedia(int(args[0]) if args else 2),
     "offices": cmd_offices, "batches": lambda: cmd_batches(int(args[0]) if args else 25, args[1] if len(args) > 1 else "batch",
                                    tuple(int(x) for x in args[2].split(",")) if len(args) > 2 else (1, 2)), "merge": cmd_merge,
     "stats": cmd_stats,
     "muse-push": lambda: cmd_muse_push("--local" if "--local" in args else "--remote"),
     "muse-pull": lambda: cmd_muse_pull("--local" if "--local" in args else "--remote")}[cmd]()
