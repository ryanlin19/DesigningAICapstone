"""Fetchers for the public job-board feeds of Greenhouse, Lever and Ashby.

Each fetcher returns a list of normalized job dicts, or None if the company has
no board on that platform. Standard library only.
"""
import http.client
import json
import re
import threading
import time
import urllib.error
import urllib.request

UA = "Mozilla/5.0 (compatible; job-board/0.1)"

# Why the last request on this thread failed ("HTTP 403 at <url>"), so build.py can say why a firm came back empty.
_why = threading.local()


def _note(url, problem):
    _why.last = f"{problem} at {url}"


def why(clear=True):
    """The last failure noted on this thread (None if there was none). build.py calls it after each firm."""
    out = getattr(_why, "last", None)
    if clear:
        _why.last = None
    return out


def _err(e):
    if isinstance(e, urllib.error.HTTPError):
        return f"HTTP {e.code}"
    if isinstance(e, urllib.error.URLError):
        return f"unreachable ({e.reason})"
    return f"{type(e).__name__}" + (f" ({e})" if str(e) else "")
TIMEOUT = 20


def _get_json(url, retries=2, data=None, headers=None):
    """GET (or POST when `data` is a dict) a JSON feed. None means no usable board (404 or repeated failure)."""
    h = {"User-Agent": UA, "Accept": "application/json"}
    body = None
    if data is not None:
        body, h["Content-Type"] = json.dumps(data).encode(), "application/json"
    h.update(headers or {})
    req = urllib.request.Request(url, data=body, headers=h)
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            _note(url, _err(e))
            if e.code in (404, 400, 410):
                return None
            # 429 / 5xx: back off and retry
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ConnectionError, http.client.IncompleteRead) as e:
            _note(url, _err(e))   # IncompleteRead: a large reply cut off mid-way (Phenom widgets at Corning, RBC); try again
        time.sleep(1.5 * (attempt + 1))
    return None


def _strip_html(s):
    s = re.sub(r"<[^>]+>", " ", s or "")
    s = (s.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<")
          .replace("&gt;", ">").replace("&quot;", '"').replace("&#39;", "'"))
    return re.sub(r"\s+", " ", s).strip()


def fetch_greenhouse(slug):
    import html
    d = _get_json(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true")
    if not d or "jobs" not in d:
        return None
    jobs = []
    for j in d["jobs"]:
        jobs.append({
            "title": j.get("title", ""),
            "url": j.get("absolute_url", ""),
            "location": (j.get("location") or {}).get("name", ""),
            "posted": (j.get("first_published") or j.get("updated_at") or "")[:10],
            "description": _strip_html(html.unescape(j.get("content", ""))),
            "salary": None,
            "deadline": j.get("application_deadline"),   # structured field; usually empty, so the text is read too
            "source": "greenhouse",
        })
    return jobs


def fetch_lever(slug):
    d = _get_json(f"https://api.lever.co/v0/postings/{slug}?mode=json")
    if not isinstance(d, list):
        return None
    jobs = []
    for j in d:
        cats = j.get("categories") or {}
        loc = cats.get("location") or ""
        if cats.get("allLocations"):
            loc = " · ".join(cats["allLocations"])
        sal = j.get("salaryRange")
        posted = ""
        if j.get("createdAt"):
            import datetime
            posted = datetime.datetime.fromtimestamp(j["createdAt"] / 1000, datetime.timezone.utc).strftime("%Y-%m-%d")
        jobs.append({
            "title": j.get("text", ""),
            "url": j.get("hostedUrl", ""),
            "location": loc,
            "posted": posted,
            "description": _strip_html(j.get("descriptionPlain") or j.get("description", "")),
            "salary": ({"min": sal.get("min"), "max": sal.get("max"), "currency": sal.get("currency")}
                       if isinstance(sal, dict) else None),
            "source": "lever",
        })
    return jobs


def fetch_ashby(slug):
    d = _get_json(f"https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true")
    if not d or "jobs" not in d:
        return None
    jobs = []
    for j in d["jobs"]:
        if j.get("isListed") is False:
            continue
        locs = [j.get("location") or ""] + [
            (s or {}).get("location", "") for s in (j.get("secondaryLocations") or [])
        ]
        comp = (j.get("compensation") or {}).get("compensationTierSummary")
        jobs.append({
            "title": j.get("title", ""),
            "url": j.get("jobUrl", ""),
            "location": " · ".join(x for x in locs if x) + (" · Remote" if j.get("isRemote") else ""),
            "posted": (j.get("publishedAt") or "")[:10],
            "description": j.get("descriptionPlain") or _strip_html(j.get("descriptionHtml", "")),
            "salary": comp,
            "source": "ashby",
        })
    return jobs


FETCHERS = {"greenhouse": fetch_greenhouse, "lever": fetch_lever, "ashby": fetch_ashby}


# ---------------------------------------------------------------------------
# Firm-specific boards (configured by hand in data/custom_boards.json).
# These systems list every job the firm has, so each reader takes a `want(title)`
# filter and only opens the detail page of titles worth classifying.
# ---------------------------------------------------------------------------
WORKDAY_TERMS = ["strategy", "consultant", "consulting", "transformation", "operations", "chief of staff",
                 "program management", "advisory", "business"]
WORKDAY_PAGE = 20          # Workday caps the page size at 20
WORKDAY_MAX_PER_TERM = 200


def _wd_location(loc):
    """'US - GA, Atlanta' -> 'Atlanta, GA'; 'US - Remote' -> 'Remote - US'."""
    loc = (loc or "").strip()
    m = re.match(r"^US\s*-\s*([A-Z]{2}),\s*(.+)$", loc)
    if m:
        return f"{m.group(2)}, {m.group(1)}"
    if re.match(r"^US\s*-\s*Remote", loc, re.I):
        return "Remote - US"
    return loc


def _get_json_patient(url, data=None, tries=4):
    """JSON request that waits and tries again after a temporary failure (429, 5xx, timeout): Workday sometimes answers a
    burst of requests with errors, and giving up on one page would silently lose the rest of a firm's list. A page that is
    simply gone (400/404/410) returns None at once."""
    h = {"User-Agent": UA, "Accept": "application/json"}
    body = None
    if data is not None:
        body, h["Content-Type"] = json.dumps(data).encode(), "application/json"
    req = urllib.request.Request(url, data=body, headers=h)
    for i in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            if e.code in (400, 404, 410):
                return None
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ConnectionError):
            pass
        time.sleep(3 * (i + 1))
    return None


def fetch_workday(cfg, want=None):
    """cfg: {"tenant", "host" (e.g. wd1), "site"}. Searches a handful of role keywords, then opens matching titles."""
    root = f"https://{cfg['tenant']}.{cfg['host']}.myworkdayjobs.com"
    api = f"{root}/wday/cxs/{cfg['tenant']}/{cfg['site']}"
    found, reachable = {}, False
    cap = cfg.get("max_per_term", WORKDAY_MAX_PER_TERM)
    for term in cfg.get("terms", WORKDAY_TERMS):
        offset, grand_total = 0, 0
        while offset < cap:
            d = _get_json_patient(f"{api}/jobs", data={"appliedFacets": {}, "limit": WORKDAY_PAGE, "offset": offset, "searchText": term})
            if d is None:
                break
            reachable = True
            grand_total = d.get("total") or grand_total      # Workday reports the total on the first page only
            posts = d.get("jobPostings") or []
            for p in posts:
                if p.get("externalPath") and p.get("title"):
                    found.setdefault(p["externalPath"], p)
            offset += WORKDAY_PAGE
            if not posts or offset >= grand_total:
                break
            time.sleep(0.15)
    if not reachable:
        return None
    jobs = []
    for path, p in found.items():
        if want and not want(p["title"]):
            continue
        if cfg.get("us_only"):
            # a worldwide board (PwC): skip postings whose listed place shows no sign of being in the US.
            # "3 Locations" can't be judged from the list, so those are opened.
            from classify import US_STRONG
            lt = p.get("locationsText") or ""
            if not re.match(r"^\d+ Locations?$", lt) and not US_STRONG.search(lt):
                continue
        d = _get_json_patient(f"{api}{path}")
        info = (d or {}).get("jobPostingInfo")
        if not info:
            continue
        locs = [_wd_location(x) for x in [info.get("location")] + list(info.get("additionalLocations") or []) if x]
        jobs.append({
            "title": info.get("title") or p["title"],
            "url": info.get("externalUrl") or f"{root}/{cfg['site']}{path}",
            "location": " · ".join(dict.fromkeys(locs)),
            "posted": (info.get("startDate") or "")[:10],
            "description": _strip_html(info.get("jobDescription", "")),
            "salary": None,
            "source": "workday",
        })
        time.sleep(0.1)
    return jobs


def _age_to_date(txt):
    """'NEW' / '3d' / '2w' / '1mo' -> approximate posting date (YYYY-MM-DD)."""
    import datetime
    today = datetime.date.today()
    t = (txt or "").strip().lower()
    m = re.match(r"(\d+)\s*(d|w|mo|m|y)", t)
    if t == "new":
        return today.isoformat()
    if not m:
        return ""
    n, unit = int(m.group(1)), m.group(2)
    days = n * {"d": 1, "w": 7, "mo": 30, "m": 30, "y": 365}[unit]
    return (today - datetime.timedelta(days=days)).isoformat()


def fetch_recsolu(cfg, want=None):
    """Kearney, and others on RecSolu / Yello. cfg: {"base": "https://x.recsolu.com", "board": "<board id>"}."""
    import html as htmllib
    base = cfg["base"].rstrip("/")
    rows, reachable = [], False
    for page in range(1, cfg.get("max_pages", 40) + 1):
        d = _get_json(f"{base}/job_boards/{cfg['board']}/search?page_number={page}", headers={"X-Requested-With": "XMLHttpRequest"})
        if d is None or "html" not in d:
            break
        reachable = True
        for li in re.findall(r'<li class="search-results__item">(.*?)</li>', d["html"], re.S):
            m = re.search(r'href="([^"]+)"[^>]*>(.*?)</a>', li, re.S)
            if not m:
                continue
            spans = [htmllib.unescape(re.sub(r"<[^>]+>", "", s)).strip() for s in re.findall(r"<span>(.*?)</span>", li, re.S)]
            age = re.search(r'search-results__post-time[^>]*>(.*?)</div>', li, re.S)
            rows.append((htmllib.unescape(m.group(1)), htmllib.unescape(re.sub(r"<[^>]+>", "", m.group(2))).strip(),
                         spans, re.sub(r"<[^>]+>", "", age.group(1)).strip() if age else ""))
        if not d.get("more_requisitions"):
            break
        time.sleep(0.15)
    if not reachable:
        return None
    jobs = []
    for href, title, spans, age in rows:
        if want and not want(title):
            continue
        url = href if href.startswith("http") else base + href
        desc = ""
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                page_html = r.read(400000).decode("utf-8", "replace")
            page_html = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", page_html, flags=re.S)
            desc = _strip_html(page_html)
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            pass
        # spans look like [job type, region, city, city...]; keep the cities
        cities = [c.strip() for s in spans[2:] for c in s.split(",") if c.strip()]  # one span holds "Atlanta, Boston, ..."
        jobs.append({"title": title, "url": url, "location": " · ".join(cities), "posted": _age_to_date(age),
                     "description": desc, "salary": None, "source": "recsolu"})
        time.sleep(0.1)
    return jobs


# ---------------------------------------------------------------------------
# More firm-specific readers: Pinpoint (Cartesian), Phenom (BCG), SuccessFactors search pages (EY),
# Avature search pages (Deloitte) and Cornerstone (Simon-Kucher). Each reads what the firm's own public
# careers page shows to an ordinary visitor.
# ---------------------------------------------------------------------------
import html as _html
import http.cookiejar
from urllib.parse import quote

HTML_TERMS = ["strategy", "consulting", "consultant", "transformation", "operations", "chief of staff",
              "program management", "business"]
HTML_MAX_PER_TERM = 200


def _get_text(url, opener=None, retries=2, limit=1500000):
    """GET a page as text. None if the page is missing or refuses us (we do not retry around a refusal)."""
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,application/xhtml+xml"})
    for attempt in range(retries + 1):
        try:
            with (opener or urllib.request.build_opener()).open(req, timeout=TIMEOUT) as r:
                return r.read(limit).decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            _note(url, _err(e))
            if e.code in (400, 403, 404, 410):
                return None
        except (urllib.error.URLError, TimeoutError, ConnectionError, http.client.IncompleteRead) as e:
            _note(url, _err(e))
        time.sleep(1.5 * (attempt + 1))
    return None


def _page_text(page_html):
    return _strip_html(re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", page_html or "", flags=re.S))


def _text_of(fragment):
    return _html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", fragment or ""))).strip()


def _with_country(loc, suffix):
    """A US-only careers site often says just "Multiple Locations"; add the country so the US check can see it."""
    if suffix and loc and not re.search(r"united states|\busa\b|\bus\b", loc, re.I):
        return f"{loc}, {suffix}"
    return loc or suffix or ""


def fetch_pinpoint(cfg, want=None):
    """Cartesian and other Pinpoint career sites. cfg: {"sub": "cartesian"}."""
    d = _get_json(f"https://{cfg.get('host') or cfg['sub'] + '.pinpointhq.com'}/postings.json")
    if not d or "data" not in d:
        return None
    jobs = []
    for p in d["data"]:
        if want and not want(p.get("title", "")):
            continue
        loc = p.get("location") or {}
        where = loc.get("name") or ", ".join(x for x in (loc.get("city"), loc.get("province")) if x)
        if p.get("workplace_type") == "remote" and "remote" not in (where or "").lower():
            where = f"{where} · Remote" if where else "Remote"
        lo, hi = p.get("compensation_minimum"), p.get("compensation_maximum")
        salary = ({"min": lo, "max": hi, "currency": p.get("compensation_currency")}
                  if p.get("compensation_visible") and lo and hi else None)
        body = " ".join(p.get(k) or "" for k in ("description", "key_responsibilities", "skills_knowledge_expertise", "benefits"))
        jobs.append({"title": p.get("title", ""), "url": p.get("url", ""), "location": where, "posted": "",
                     "description": _strip_html(body), "salary": salary, "deadline": p.get("deadline_at"), "source": "pinpoint"})
    return jobs


def fetch_phenom(cfg, want=None):
    """BCG and other Phenom career sites. cfg: {"base", "locale": "global/en", "countries": ["United States of America"]}."""
    base = cfg["base"].rstrip("/")
    raw, start, total = [], 0, None
    while total is None or start < total:
        body = {"lang": cfg.get("lang", "en_global"), "deviceType": "desktop", "country": cfg.get("country", "global"), "pageName": "search-results",
                "ddoKey": "refineSearch", "sortBy": "", "subsearch": "", "from": start, "jobs": True, "counts": True,
                "all_fields": ["category", "country", "state", "city", "type"], "size": 50, "clearAll": False,
                "jdsource": "facets", "isSliderEnable": False, "pageId": "page11", "siteType": "external", "keywords": "",
                "global": True, "selected_fields": ({"country": cfg["countries"]} if cfg.get("countries") else {}),
                "sort": {"order": "desc", "field": "postedDate"}, "locationData": {}}
        d = _get_json(f"{base}/widgets", data=body)
        rs = (d or {}).get("refineSearch")
        if not rs or rs.get("status") != 200:
            break
        total = rs.get("totalHits", 0)
        batch = (rs.get("data") or {}).get("jobs") or []
        if not batch:
            break
        raw += batch
        start += len(batch)
        time.sleep(0.15)
    if total is None:
        return None
    jobs = []
    for r in raw:
        title = r.get("title", "")
        if want and not want(title):
            continue
        url = f"{base}/{cfg.get('locale', 'global/en')}/job/{r.get('jobId')}"
        locs = r.get("multi_location") or [r.get("location")]
        locs = [l if isinstance(l, str) else (l or {}).get("location", "") for l in locs]
        # PwC writes "NY-New York" and "US-Remote"
        locs = ["Remote - US" if (l or "").startswith("US-Remote") else re.sub(r"^([A-Z]{2})-(.+)$", r"\2, \1, United States", l or "")
                for l in locs]
        desc = r.get("descriptionTeaser") or ""
        page = _get_text(url)
        m = re.search(r'"description"\s*:\s*"((?:[^"\\]|\\.)*)"', page or "")
        if m:
            try:
                desc = _strip_html(json.loads('"' + m.group(1) + '"'))
            except ValueError:
                pass
        jobs.append({"title": title, "url": url, "location": "; ".join(x for x in locs if x),
                     "posted": (r.get("postedDate") or "")[:10], "description": desc, "salary": None, "source": "phenom"})
        time.sleep(0.1)
    return jobs


def _sf_date(text):
    import datetime as _dt
    for fmt in ("%b %d, %Y", "%B %d, %Y", "%m/%d/%Y"):
        try:
            return _dt.datetime.strptime((text or "").strip(), fmt).date().isoformat()
        except ValueError:
            continue
    return ""


def fetch_sfhtml(cfg, want=None):
    """EY and other SuccessFactors career sites with server-rendered search pages.
    cfg: {"base": "https://careers.ey.com", "path": "/ey", "location": "United States", "country_suffix": "United States"}.
    "page_size" is how many results the site shows per page (EY 25, Bayer 10)."""
    base, path = cfg["base"].rstrip("/"), cfg.get("path", "")
    page_size = cfg.get("page_size", 25)
    found, reachable = {}, False
    for term in cfg.get("terms", HTML_TERMS):
        start = 0
        while start < cfg.get("max_per_term", HTML_MAX_PER_TERM):
            page = _get_text(f"{base}{path}/search/?createNewAlert=false&q={quote(term)}"
                             f"&locationsearch={quote(cfg.get('location', ''))}&startrow={start}")
            if page is None:
                break
            reachable = True
            rows = re.findall(r'<tr class="data-row">(.*?)</tr>', page, re.S)
            for row in rows:
                m = re.search(r'href="(/[^"]*/job/[^"]+)"[^>]*class="jobTitle-link"[^>]*>(.*?)</a>', row, re.S) or \
                    re.search(r'class="jobTitle-link"[^>]*href="(/[^"]+)"[^>]*>(.*?)</a>', row, re.S)
                if not m:
                    continue
                loc = re.search(r'class="jobLocation[^"]*">(.*?)</span>', row, re.S)
                date = re.search(r'class="jobDate[^"]*">(.*?)</span>', row, re.S)
                found.setdefault(m.group(1), (_text_of(m.group(2)), _text_of(loc.group(1)) if loc else "", _text_of(date.group(1)) if date else ""))
            if len(rows) < page_size:
                break
            start += page_size
            time.sleep(0.15)
    if not reachable:
        return None
    jobs = []
    for href, (title, loc, date) in found.items():
        if want and not want(title):
            continue
        url = base + href
        page = _get_text(url)
        m = re.search(r'<span class="jobdescription">(.*?)</span>\s*</div>', page or "", re.S)
        desc = _strip_html(m.group(1)) if m else _page_text(page)
        if cfg.get("country_suffix") and not re.search(r",\s*US\b|\bUnited States\b", loc):
            continue                                                  # the search also returns UK/Ireland postings
        loc = re.sub(r"\s*\+\s*\d+\s*more.*$", "", loc)             # "Chicago, IL, US, 60606 +5 more…"
        loc = re.sub(r",?\s*\b\d{5}(-\d{4})?\b", "", loc).strip(" ,")  # zip codes
        jobs.append({"title": title, "url": url, "location": _with_country(loc, cfg.get("country_suffix")),
                     "posted": _sf_date(date), "description": desc[:20000], "salary": None, "source": "successfactors"})
        time.sleep(0.1)
    return jobs


def fetch_avature(cfg, want=None):
    """Deloitte US and other Avature career sites. cfg: {"base": "https://apply.deloitte.com/en_US/careers", "country_suffix": "United States"}."""
    base = cfg["base"].rstrip("/")
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    found, reachable = {}, False
    for term in cfg.get("terms", HTML_TERMS):
        for offset in range(0, cfg.get("max_per_term", HTML_MAX_PER_TERM), 10):
            page = _get_text(f"{base}/SearchJobs/{quote(term)}?jobRecordsPerPage=10&jobOffset={offset}&sort=relevancy", opener)
            if page is None:
                break
            reachable = True
            arts = re.findall(r'<article class="article(?: article)?--result.*?</article>', page, re.S)
            if not arts:
                break
            for a in arts:
                m = re.search(r'<a href="(https://[^"]*/JobDetail/[^"]+)"[^>]*>(.*?)</a>', a, re.S)
                if not m:
                    continue
                sub = re.search(r'article__header__text__subtitle">(.*?)</div>', a, re.S)
                spans = [_text_of(s) for s in re.findall(r"<span>(.*?)</span>", sub.group(1), re.S)] if sub else []
                found.setdefault(m.group(1), (_text_of(m.group(2)), spans))
            if len(arts) < 10:
                break
            time.sleep(0.15)
    if not reachable:
        return None
    jobs = []
    for url, (title, spans) in found.items():
        if want and not want(title):
            continue
        if cfg.get("units") and not re.search(cfg["units"], spans[1] if len(spans) > 1 else ""):
            continue          # e.g. audit and internal-services entities
        page = _get_text(url, opener)
        desc = _page_text(page)
        loc = spans[-1] if spans else ""
        if loc.lower().startswith("multiple") and page:
            # the results list says "Multiple Locations"; the posting page lists each place
            i = page.find("article__header--locations")
            places = re.findall(r'<p class="paragraph">([^<]+, United States)</p>', page[i:i + 12000]) if i >= 0 else []
            if places:
                loc = " · ".join(dict.fromkeys(p.strip() for p in places))
        jobs.append({"title": title, "url": url, "location": _with_country(loc, cfg.get("country_suffix")),
                     "posted": "", "description": desc[:20000], "salary": None, "source": "avature",
                     "unit": spans[1] if len(spans) > 1 else ""})
        time.sleep(0.1)
    return jobs


def fetch_kpmg(cfg, want=None):
    """KPMG US careers search pages (12 per page, ?keyword=...&spage=N). cfg: {"base": "https://www.kpmguscareers.com"}."""
    base = cfg["base"].rstrip("/")
    found, reachable = {}, False
    for term in cfg.get("terms", HTML_TERMS):
        for pg in range(1, cfg.get("max_per_term", HTML_MAX_PER_TERM) // 12 + 2):
            page = _get_text(f"{base}/job-search/?keyword={quote(term)}&spage={pg}")
            if page is None:
                break
            reachable = True
            blocks = re.findall(r'<div class="search--item.*?</a>\s*</div>', page, re.S)
            if not blocks and pg == 1 and not found:            # a bot check or a new page layout, not "no jobs"
                t = re.search(r"<title[^>]*>(.*?)</title>", page, re.S | re.I)
                _note(f"{base}/job-search/?keyword={quote(term)}", f"page loaded ({len(page):,} chars, title "
                      f"{_text_of(t.group(1))[:80]!r}) but had no job listings" if t else f"page loaded ({len(page):,} chars) but had no job listings")
            new = 0
            for b in blocks:
                m = re.search(r'href="(/jobdetail/\?jobId=\d+)"', b)
                title = re.search(r'<div class="h5 text-dark-grey">(.*?)</div>', b, re.S)
                where = re.search(r'<div class="text-xs text-dark-grey">[^<|]*\|([^<]*)</div>', b)
                if not m or not title or m.group(1) in found:
                    continue
                new += 1
                found[m.group(1)] = (_text_of(title.group(1)), _text_of(where.group(1)) if where else "")
            if not blocks or not new:
                break
            time.sleep(0.15)
    if not reachable:
        return None
    jobs = []
    for href, (title, loc) in found.items():
        if want and not want(title):
            continue
        page = _get_text(base + href)
        desc = _page_text(page)
        locs = [p.strip() for p in loc.split(";") if p.strip()]
        jobs.append({"title": title, "url": base + href, "location": " · ".join(_with_country(p, cfg.get("country_suffix")) for p in locs),
                     "posted": "", "description": desc[:20000], "salary": None, "source": "kpmg"})
        time.sleep(0.1)
    return jobs


def _date_text(s):
    """'30 Oct 2026 23:55 EDT' -> '2026-10-30'."""
    import datetime as _dt
    m = re.search(r"(\d{1,2}) ([A-Za-z]{3}) (\d{4})", s or "")
    if not m:
        return ""
    try:
        return _dt.datetime.strptime(" ".join(m.groups()), "%d %b %Y").date().isoformat()
    except ValueError:
        return ""


def fetch_talnet(cfg, want=None):
    """L.E.K. and other Tal.net career sites. cfg: {"boards": ["<vacancy list url>", ...]} (the Americas list for LEK)."""
    found, reachable = {}, False
    for board in cfg["boards"]:
        page = _get_text(board)
        if page is None:
            continue
        reachable = True
        for tile in re.findall(r'<li class="[^"]*opp-container.*?</li>', page, re.S):
            m = re.search(r'<a class="subject" href="([^"]+)"[^>]*>(.*?)</a>', tile, re.S)
            if not m:
                continue
            loc = re.search(r'Location:</span>(.*?)</div>', tile, re.S)
            close = re.search(r'Closing Date:</span>(.*?)</div>', tile, re.S)
            found.setdefault(m.group(1), (_text_of(m.group(2)), _text_of(loc.group(1)) if loc else "", _text_of(close.group(1)) if close else ""))
    if not reachable:
        return None
    jobs = []
    for url, (title, loc, close) in found.items():
        if want and not want(title):
            continue
        desc = _page_text(_get_text(url))
        places = [p.strip() for p in loc.split(",") if p.strip()]
        jobs.append({"title": title, "url": url, "location": " · ".join(_with_country(p, cfg.get("country_suffix")) for p in places),
                     "posted": "", "description": desc[:20000], "salary": None, "deadline": _date_text(close), "source": "talnet"})
        time.sleep(0.1)
    return jobs


def fetch_jibe(cfg, want=None):
    """ZS and other career sites built on Jibe (their own page calls /api/jobs). cfg: {"host": "jobs.zs.com", "country": "United States"}."""
    host = cfg["host"]
    jobs, page_no, total = [], 1, None
    while total is None or len(jobs) < total:
        d = _get_json(f"https://{host}/api/jobs?page={page_no}&limit=100&country={quote(cfg.get('country', 'United States'))}")
        if d is None or "jobs" not in d:
            return None if total is None else jobs
        total = d.get("totalCount", 0)
        batch = d["jobs"]
        if not batch:
            break
        for item in batch:
            r = item.get("data") or {}
            title = r.get("title", "")
            if want and not want(title):
                continue
            body = " ".join(r.get(k) or "" for k in ("description", "responsibilities", "qualifications"))
            where = r.get("full_location") or ", ".join(x for x in (r.get("city"), r.get("state")) if x)
            jobs.append({"title": title, "url": f"https://{host}/jobs/{r.get('slug') or r.get('req_id')}?lang=en-us",
                         "location": _with_country(where, cfg.get("country_suffix", "United States")),
                         "posted": (r.get("posted_date") or "")[:10], "description": _strip_html(body)[:20000],
                         "salary": None, "source": "jibe"})
        page_no += 1
        time.sleep(0.15)
    return jobs


def fetch_csod(cfg, want=None):
    """Simon-Kucher and other Cornerstone career sites. cfg: {"host": "simon-kucher.csod.com", "site": 6, "corp": "simon-kucher"}."""
    home = _get_text(f"https://{cfg['host']}/ux/ats/careersite/{cfg['site']}/home?c={cfg['corp']}")
    tok = re.search(r'"token"\s*:\s*"(eyJ[A-Za-z0-9_\-\.]+)"', home or "")
    if not tok:
        return None
    jobs, page_no, total = [], 1, None
    while total is None or len(jobs) < total:
        body = {"careerSiteId": cfg["site"], "careerSitePageId": cfg["site"], "pageNumber": page_no, "pageSize": 25, "cultureId": 1,
                "searchText": "", "cultureName": "en-US", "states": [], "countryCodes": [], "cities": [], "placeID": "",
                "radius": None, "postingsWithinDays": None, "customFieldCheckboxKeys": [], "customFieldDropdowns": [],
                "customFieldRadios": []}
        d = _get_json(f"https://{cfg['host']}/services/x/career-site/v1/search", data=body,
                      headers={"Authorization": "Bearer " + tok.group(1)})
        data = (d or {}).get("data") or {}
        batch = data.get("requisitions") or []
        total = data.get("totalCount", 0) if total is None else total
        if not batch:
            break
        for r in batch:
            title = r.get("displayJobTitle", "")
            if want and not want(title):
                continue
            places = []
            for l in r.get("locations") or []:
                if (l.get("country") or "").upper() not in ("US", "USA"):
                    continue     # two-letter country codes such as DE would read as US states downstream
                parts = [l.get("city"), l.get("state"), "United States"]
                places.append(", ".join(x for x in parts if x))
            if not places:
                continue
            jobs.append({"title": title, "url": f"https://{cfg['host']}/ux/ats/careersite/{cfg['site']}/home/requisition/{r.get('requisitionId')}?c={cfg['corp']}",
                         "location": "; ".join(p for p in places if p), "posted": (r.get("postingEffectiveDate") or "")[:10],
                         "description": "", "salary": None, "source": "cornerstone"})
        if len(batch) < 25:
            break
        page_no += 1
        time.sleep(0.15)
    return jobs


def fetch_teamtailor(cfg, want=None):
    """LSC and other Teamtailor career sites (server-rendered list at {base}/jobs). cfg: {"base": "https://careers.consultingls.com"}."""
    base = cfg["base"].rstrip("/")
    page = _get_text(f"{base}/jobs")
    if page is None:
        return None
    jobs = []
    for li in re.findall(r'<li class="w-full">(.*?)</li>', page, re.S):
        m = re.search(r'<a [^>]*href="(https?://[^"]*/jobs/\d+[^"]*)"[^>]*>(.*?)</a>', li, re.S)
        if not m:
            continue
        title = _text_of(m.group(2))
        if want and not want(title):
            continue
        spans = [_text_of(s) for s in re.findall(r"<span>(.*?)</span>", li, re.S)]
        spans = [s for s in spans if s and s != "·"]
        where = spans[-1] if spans else ""
        jobs.append({"title": title, "url": m.group(1), "location": where, "posted": "",
                     "description": _page_text(_get_text(m.group(1)))[:20000], "salary": None, "source": "teamtailor"})
        time.sleep(0.1)
    return jobs


def fetch_capgemini(cfg, want=None):
    """Capgemini. The careers page calls a public search API; cfg: {"country_code": "us-en"}."""
    code = cfg.get("country_code", "us-en")
    jobs, page_no, total = [], 1, None
    while total is None or (page_no - 1) * 100 < total:
        d = _get_json(f"https://cg-jobstream-api.azurewebsites.net/api/job-search?page={page_no}&size=100&country_code={code}")
        if d is None or "data" not in d:
            return None if total is None else jobs
        total = d.get("total", 0)
        batch = d["data"]
        if not batch:
            break
        for r in batch:
            title = r.get("title", "")
            if want and not want(title):
                continue
            places = [x.strip() for x in (r.get("location") or "").split(",") if x.strip()]
            jobs.append({"title": title, "url": r.get("apply_job_url") or "", "posted": (r.get("updated_at") or "")[:10],
                         "location": " \u00b7 ".join(f"{x}, United States" for x in places),
                         "description": (r.get("description_stripped") or "")[:20000], "salary": None, "source": "capgemini"})
        page_no += 1
        time.sleep(0.15)
    return [j for j in jobs if j["url"]]


def fetch_alexander(cfg, want=None):
    """Alexander Group lists its openings as plain text on one page. cfg: {"base": "https://www.alexandergroup.com"}."""
    base = cfg["base"].rstrip("/")
    page = _get_text(f"{base}/careers/current-openings/")
    if page is None:
        return None
    jobs = []
    for href, head in re.findall(r'<li>\s*<a href="(/careers/[^"]+)"[^>]*>\s*<strong class="h4">(.*?)</strong>', page, re.S):
        head = _text_of(head)
        title, _, where = head.partition(" \u2014 ")
        if want and not want(title):
            continue
        where = re.sub(r"\(.*?\)", "", where)
        places = [f"{c.strip()}, {st}" for c, st in re.findall(r"([A-Z][A-Za-z .]+?),\s*([A-Z]{2})\b", where)]
        if not places:
            continue                       # London and other non-US offices
        url = base + href
        jobs.append({"title": title, "url": url, "posted": "", "location": " \u00b7 ".join(places),
                     "description": _page_text(_get_text(url))[:20000], "salary": None, "source": "alexander"})
        time.sleep(0.1)
    return jobs


def fetch_zoho(cfg, want=None):
    """Zoho Recruit career sites (Insero). The page carries its whole job list as JSON in a hidden input. cfg: {"host": "x.zohorecruit.com"}."""
    host = cfg["host"]
    page = _get_text(f"https://{host}/jobs/Careers", limit=4000000)
    m = re.search(r'value="(\[\{&#34;Remote_Job&#34;.*?\}\])"', page or "", re.S)
    if not m:
        return None if page is None else []
    try:
        rows = json.loads(_html.unescape(m.group(1)))
    except ValueError:
        return None
    jobs = []
    for r in rows:
        title = _html.unescape(r.get("Posting_Title") or "")
        if not title or r.get("Publish") not in (True, "True") or (want and not want(title)):
            continue
        where = ", ".join(x for x in (r.get("City"), r.get("State"), r.get("Country")) if x and x != "None")
        body = _strip_html(f"{r.get('Job_Description') or ''} {r.get('Work_Experience') or ''}")
        jobs.append({"title": title, "url": f"https://{host}/jobs/Careers/{r.get('id')}", "location": where,
                     "posted": r.get("Date_Opened") or "", "description": body[:20000], "salary": None, "source": "zoho"})
    return jobs


def fetch_smartrecruiters(cfg, want=None):
    """SmartRecruiters public postings API (Wavestone). cfg: {"slug": "Wavestone1", "country": "us"}."""
    api = f"https://api.smartrecruiters.com/v1/companies/{cfg['slug']}/postings"
    country = cfg.get("country", "us")
    rows, offset, total = [], 0, None
    while total is None or offset < total:
        d = _get_json(f"{api}?country={country}&limit=100&offset={offset}")
        if d is None or "content" not in d:
            return None if total is None else []
        total = d.get("totalFound", 0)
        if not d["content"]:
            break
        rows += d["content"]
        offset += 100
    jobs = []
    for r in rows:
        title = (r.get("name") or "").strip()
        if not title or (want and not want(title)):
            continue
        d = _get_json(f"{api}/{r['id']}")
        if not d:
            continue
        secs = (d.get("jobAd") or {}).get("sections") or {}
        body = _strip_html(" ".join(s.get("text") or "" for s in secs.values()))
        jobs.append({"title": title, "url": d.get("postingUrl") or f"https://jobs.smartrecruiters.com/{cfg['slug']}/{r['id']}",
                     "location": (r.get("location") or {}).get("fullLocation") or "", "posted": (r.get("releasedDate") or "")[:10],
                     "description": body[:20000], "salary": None, "source": "smartrecruiters"})
        time.sleep(0.1)
    return jobs


CUSTOM_FETCHERS = {"workday": fetch_workday, "recsolu": fetch_recsolu, "pinpoint": fetch_pinpoint, "phenom": fetch_phenom,
                   "sfhtml": fetch_sfhtml, "avature": fetch_avature, "csod": fetch_csod, "kpmg": fetch_kpmg,
                   "talnet": fetch_talnet, "jibe": fetch_jibe, "teamtailor": fetch_teamtailor,
                   "capgemini": fetch_capgemini, "alexander": fetch_alexander, "zoho": fetch_zoho,
                   "smartrecruiters": fetch_smartrecruiters,
                   # firms that are not in the firm database but sit on a standard feed
                   "greenhouse": lambda cfg, want=None: fetch_greenhouse(cfg["slug"]),
                   "lever": lambda cfg, want=None: fetch_lever(cfg["slug"]),
                   "ashby": lambda cfg, want=None: fetch_ashby(cfg["slug"])}


def run_custom(cfg, want=None):
    """Run a firm-specific reader. Optional cfg keys (regexes): exclude / include drop or keep titles before their detail
    pages are opened, title_strip removes boilerplate from titles, location_strip removes it from locations."""
    ex = re.compile(cfg["exclude"], re.I) if cfg.get("exclude") else None
    inc = re.compile(cfg["include"], re.I) if cfg.get("include") else None   # keep only titles that match (broad employers)
    strip = cfg.get("title_strip")
    norm = (lambda t: re.sub(strip, "", t, flags=re.I).strip(" -")) if strip else (lambda t: t)
    if ex or inc or strip:
        inner = want
        want = (lambda t: not (ex and ex.search(t)) and (not inc or inc.search(t)) and (inner(norm(t)) if inner else True))
    jobs = CUSTOM_FETCHERS[cfg["platform"]](cfg, want=want)
    if jobs is not None and (ex or inc or strip):
        jobs = [j for j in jobs if want(j["title"])]            # feeds that list everything up front (Greenhouse)
    if jobs is not None and strip:
        for j in jobs:
            j["title"] = norm(j["title"])
    if jobs is not None and cfg.get("location_strip"):
        for j in jobs:
            j["location"] = re.sub(cfg["location_strip"], "", j["location"])
    if jobs is not None and cfg.get("location_sub"):          # [pattern, replacement], e.g. a bare "Washington" -> "Washington, DC"
        for j in jobs:
            j["location"] = re.sub(cfg["location_sub"][0], cfg["location_sub"][1], j["location"])
    return jobs


_STOP = {"consulting", "consultants", "consultancy", "group", "llc", "inc", "ltd", "limited", "partners",
         "associates", "advisors", "advisory", "company", "co", "corp", "corporation", "the", "and",
         "services", "solutions", "systems", "global", "international", "strategy", "llp", "plc", "by"}


def slug_guesses(name):
    """Candidate board slugs for a company name, most likely first."""
    n = re.sub(r"\(.*?\)", " ", name.lower())
    n = n.replace("&", " ").replace("+", " ")
    words = re.findall(r"[a-z0-9]+", n)
    core = [w for w in words if w not in _STOP] or words
    cands = []
    # No first-word-only guess: "applied" would match Applied Intuition, not Applied Value Group.
    for ws in (words, core):
        if not ws:
            continue
        cands += ["".join(ws), "-".join(ws)]
    seen, out = set(), []
    for c in cands:
        if c and c not in seen:
            seen.add(c)
            out.append(c)
    return out


def probe(name, slugs=None):
    """Try each slug guess on each platform. Returns (platform, slug, jobs) or None."""
    for slug in (slugs or slug_guesses(name)):
        for plat, fn in FETCHERS.items():
            jobs = fn(slug)
            if jobs is not None:
                return plat, slug, jobs
    return None
