"""Private, password-protected copy of the job board with cohort connections.

Runs on this computer only (127.0.0.1). Nothing here is deployed or uploaded.

    python cohort-board/serve.py            # then open http://127.0.0.1:8765

It serves Ryan's private build (site/) with a connections layer added on the fly,
so his files are never edited and a rebuild of the board shows up on refresh.

Where connections come from:
  - Cloud (when cohort-board/.api exists): the cohort API on Cloudflare (cohort-api/), which holds
    the LinkedIn-export data and the connections added by hand.
  - Local (otherwise): linkedin-ingest/data/cohort.db (read-only) and cohort-board/data/manual_connections.json.

Password: the COHORT_PASSWORD environment variable, else cohort-board/.password.
"""
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timezone
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
SITE = REPO / "site"
STATIC = HERE / "static"
COHORT_DB = Path(os.environ.get("COHORT_INGEST_DB") or REPO / "linkedin-ingest" / "data" / "cohort.db")
DATA = Path(os.environ.get("COHORT_BOARD_DATA") or HERE / "data")     # logins and local hand-added connections
MANUAL = DATA / "manual_connections.json"
HOST, PORT = os.environ.get("COHORT_HOST", "127.0.0.1"), int(os.environ.get("COHORT_PORT", "8765"))
ORIGINS = {f"http://127.0.0.1:{PORT}", f"http://localhost:{PORT}"}
HOSTED = bool(os.environ.get("COHORT_STATE_URL"))       # running in the cloud (deploy/), behind Cloudflare's HTTPS

sys.path.insert(0, str(HERE))
import state  # noqa: E402
if state.enabled():                                       # the hosted board: bring its files down before reading them
    print("state: pulled " + (", ".join(state.pull_all()) or "nothing yet"), flush=True)

sys.path.insert(0, str(REPO / "linkedin-ingest"))
from ingest import contact_keys, rules  # noqa: E402

sys.path.insert(0, str(HERE))
import directory  # noqa: E402
import find  # noqa: E402
import regions  # noqa: E402
import uploads  # noqa: E402
from sync import SyncError  # noqa: E402  (uploads puts cohort-api on the path)


def load_password():
    pw = os.environ.get("COHORT_PASSWORD")
    if not pw and (HERE / ".password").exists():
        pw = (HERE / ".password").read_text(encoding="utf-8").strip()
    if not pw:
        sys.exit("Set a password: put it in cohort-board/.password or the COHORT_PASSWORD variable.")
    return pw


PASSWORD = load_password()
LOCK = threading.Lock()

# Logins survive restarts: sessions are kept in data/sessions.json as hashes of the cookie value.
SESSIONS_FILE = DATA / "sessions.json"
SESSION_DAYS = 30


def _hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def _load_sessions():
    try:
        saved = json.loads(SESSIONS_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}
    out = {}
    for h, v in saved.items():                           # older files held just the expiry time
        rec = v if isinstance(v, dict) else {"exp": v}
        if rec.get("exp", 0) > time.time():
            out[h] = rec
    return out


def _save_sessions():
    SESSIONS_FILE.parent.mkdir(exist_ok=True)
    tmp = SESSIONS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(SESSIONS), encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(SESSIONS_FILE)
    state.push_later("sessions.json")


SESSIONS = _load_sessions()
_current = threading.local()                             # the session of the request being handled


def new_session():
    token = secrets.token_urlsafe(32)
    with LOCK:
        SESSIONS[_hash(token)] = {"exp": time.time() + SESSION_DAYS * 86400}
        _save_sessions()
    return token


def session_ok(token):
    rec = SESSIONS.get(_hash(token or ""))
    ok = bool(rec and rec.get("exp", 0) > time.time())
    _current.key = _hash(token) if ok else None
    return ok


def end_session(token):
    with LOCK:
        SESSIONS.pop(_hash(token or ""), None)
        _save_sessions()


# ---------- the page: Ryan's private build plus small hooks ----------

COHORT_FILTER = ('<div class="intl intlbar cohortbar"><label class="chk"><input type="checkbox" id="onlyConnected"> '
                 '<b>Cohort:</b> only companies where a classmate has connections</label>'
                 '<label class="chk"><input type="checkbox" id="onlyAlumni"> only companies where a classmate worked</label>'
                 '</div>\n        ')

# The top bar shared with Find a job (static/find.html has the same markup).
NAV_HTML = """<header class="cb-nav">
  <div class="cb-nav-row">
    <a class="cb-brand" href="/">Cohort Job Board</a>
    <nav class="cb-tabs" aria-label="Sections">
      <a href="/" data-tab="find">Find a job</a>
      <a href="/map" data-tab="map">Map</a>
      <a href="/companies" data-tab="companies" aria-current="page">Companies</a>
      <a href="/companies?view=bridges" data-tab="cohort">Cohort</a>
    </nav>
    <a class="cb-upload" href="/companies?view=upload" title="Add a LinkedIn export (the upload page links to LinkedIn's data request)">Upload your data</a>
    <span class="cb-private">Private: this computer only</span>
    <button class="cb-logout" type="button">Log out</button>
  </div>
  <div class="cb-sub" hidden><div class="cb-nav-row cohort-views" aria-label="Cohort tools"></div></div>
</header>
"""

# (find, replace, expected count). The build stops with a clear message if Ryan's page changes shape.
PATCHES = [
    ("</head>", '<link rel="stylesheet" href="nav.css">\n</head>', 1),
    ("<body>", "<body>\n" + NAV_HTML, 1),
    ("<title>MBA Job Board</title>", "<title>Cohort Job Board (private)</title>", 1),
    ('<script src="data.js"></script>',
     '<link rel="stylesheet" href="cohort.css">\n<script src="cohort-data.js"></script>\n'
     '<script src="globalbar.js"></script>\n'                      # first: the others register with window.Global
     '<script src="cohort.js"></script>\n<script src="cohort-upload.js"></script>\n'
     '<script src="cohort-connect.js"></script>\n<script src="cohort-timeline.js"></script>\n<script src="describe.js"></script>\n'
     '<script src="data.js"></script>', 1),
    # "Job description" toggle on each role card
    ('badges, fit ? el("div", { class: "fitline", text: fit.why.join(" \\u00b7 ") }) : null, reasons',
     'badges, fit ? el("div", { class: "fitline", text: fit.why.join(" \\u00b7 ") }) : null, reasons, JobDescription.toggle(j.url)', 1),
    ('<div class="searchbar card">', COHORT_FILTER + '<div class="searchbar card">', 1),
    # badge in each company's header
    ('el("span", { class: "gname", text: company }),',
     'el("span", { class: "gname", text: company }), COHORT.headBadge(company),', 1),
    # connections panel at the top of each opened company
    ('function groupBody(rolesList, direct) {\n    var body = el("div", { class: "gbody" });',
     'function groupBody(rolesList, direct) {\n    var body = el("div", { class: "gbody" });\n'
     '    body.appendChild(COHORT.panel(rolesList.length ? rolesList[0].company : direct.co));', 1),
    # the "only companies with connections" filter
    ('if ($("hideUnlikely").checked && j.visa === "Unlikely") return false;',
     'if (COHORT.hide(j.company)) return false;\n    if ($("hideUnlikely").checked && j.visa === "Unlikely") return false;', 1),
    ('DIRECT.forEach(function (f) {\n      if (jobsTab === "new"',
     'DIRECT.forEach(function (f) {\n      if (COHORT.hide(f.co)) return;\n      if (jobsTab === "new"', 1),
    ('["q", "hideUnlikely", "posted",', '["q", "hideUnlikely", "onlyConnected", "onlyAlumni", "cohortPeriod", "posted",', 1),
    # posting timeline: the histogram panel, its period filter, and "Newest" ordering roles inside a company
    ('<div class="note" id="fitHint"', '<div id="cohortTimeline"><input type="hidden" id="cohortPeriod" value=""></div>\n'
     '        <div class="note" id="fitHint"', 1),
    ('if (skip !== "location" && place && (j.cities || []).indexOf(place) < 0) return false;',
     'if (skip !== "location" && place && (j.cities || []).indexOf(place) < 0) return false;\n'
     '    if (skip !== "timeline" && !COHORT.inPeriod(j)) return false;\n'
     '    if (window.Global && !Global.passes(j)) return false;', 1),
    # fit to your resume (from the "Your search" panel) on each role card
    ('fit ? el("span", { class: "badge fit " + fitClass(fit.pct), text: "Fit " + fit.pct + "%" }) : null,',
     'COHORT.bucketBadge(j), fit ? el("span", { class: "badge fit " + fitClass(fit.pct), text: "Fit " + fit.pct + "%" }) : null,', 1),
    ('var list = jobsTab === "new" ? newList : jobsTab === "other" ? otherList : mbaList;',
     'var list = jobsTab === "new" ? newList : jobsTab === "other" ? otherList : mbaList;\n'
     '    COHORT.drawTimeline(jobs.filter(function (j) { return inTabNow(j) && passes(j, "timeline"); }));', 1),
    ('return VISA_ORDER[a.visa] - VISA_ORDER[b.visa]',
     'if (s === "new") return (b.posted || "").localeCompare(a.posted || "") || VISA_ORDER[a.visa] - VISA_ORDER[b.visa];\n'
     '      return VISA_ORDER[a.visa] - VISA_ORDER[b.visa]', 1),
    ('el("span", { class: "gcount", text: rolesList.length',
     'COHORT.newestNote(rolesList), el("span", { class: "gcount", text: rolesList.length', 1),
    ('$("hidePassed").checked = true; $("closingWithin").value = "0";',
     '$("hidePassed").checked = true; $("closingWithin").value = "0"; COHORT.clearPeriod(true);', 1),
    ('$("hideUnlikely").checked = false;',
     '$("hideUnlikely").checked = false; $("onlyConnected").checked = false; $("onlyAlumni").checked = false;', 1),
    # "Classmate worked here" tag on each job card
    ('el("span", { class: "badge " + dl.cls, text: "Deadline: " + dl.text }),',
     'COHORT.jobTag(j.company), el("span", { class: "badge " + dl.cls, text: "Deadline: " + dl.text }),', 1),
]


def build_page():
    html = (SITE / "index.html").read_text(encoding="utf-8")
    for find, repl, n in PATCHES:
        found = html.count(find)
        if found != n:
            raise RuntimeError(f"site/index.html changed: expected {n} of {find[:60]!r}, found {found}. "
                               "Update PATCHES in cohort-board/serve.py.")
        html = html.replace(find, repl)
    return html


# ---------- connection data ----------

_cache = {"key": None, "value": None}


_US_DATE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")


def normalize_dates(data):
    """Posting dates as YYYY-MM-DD everywhere (one reader gives M/D/YYYY), so sorting and the timeline agree."""
    def iso(s):
        m = _US_DATE.match((s or "").strip())
        return f"{m.group(3)}-{int(m.group(1)):02d}-{int(m.group(2)):02d}" if m else s
    for j in data.get("jobs", []):
        j["posted"] = iso(j.get("posted"))
        for loc in j.get("locations") or []:
            loc["posted"] = iso(loc.get("posted"))
        # map regions, broad category and level, so the "Your search" panel's location and resume apply here too
        j["regions"] = regions.regions_for([loc.get("name") for loc in j.get("locations") or []] or [j.get("location") or ""],
                                           j.get("remote_ok"))
        j["bcat"] = find.cats.category(j.get("title") or "", j.get("group") == "consulting")
        j["blevel"] = find.cats.level(j.get("title") or "", j.get("min_years"))
    return data


_db_jobs = {"build": None, "data": None, "text": None, "checked": 0}
_file_jobs = {"key": None, "data": None, "text": None}


def board_data():
    """The job board's roles: (data, page script, version key, source label).

    From the cohort database (cohort-api/push_jobs.py) when it holds a jobs build, else Ryan's site/data.js.
    The database's version is checked at most once a minute; roles are downloaded again only when it changes.
    If the database can't be reached, the last copy downloaded (or the file) is used."""
    if isinstance(STORE, RemoteStore) and time.time() - _db_jobs["checked"] > 60:
        _db_jobs["checked"] = time.time()
        try:
            status, v = STORE.call("GET", "/v1/jobs/version")
            if status == 404:
                _db_jobs.update(build=None, data=None, text=None)          # no jobs loaded: use the file
            elif status == 200 and v["build_id"] != _db_jobs["build"]:
                status, data = STORE.call("GET", "/v1/jobs", timeout=120)
                if status == 200 and data.get("jobs"):
                    normalize_dates(data)
                    _db_jobs.update(build=v["build_id"], data=data,
                                    text="window.BOARD_DATA = " + json.dumps(data, ensure_ascii=False) + ";")
        except (OSError, RuntimeError, ValueError, KeyError) as e:
            sys.stderr.write(f"jobs from the cohort database unavailable ({e})\n")
    if _db_jobs["data"]:
        return (_db_jobs["data"], _db_jobs["text"], "db:" + _db_jobs["build"],
                f"cohort database (build {_db_jobs['build']}, {len(_db_jobs['data']['jobs'])} roles)")
    f = SITE / "data.js"
    key = f"file:{f.stat().st_mtime}"
    if _file_jobs["key"] != key:
        text = f.read_text(encoding="utf-8")
        data = normalize_dates(json.loads(text[text.index("{"):text.rindex("}") + 1]))
        _file_jobs.update(key=key, data=data, text="window.BOARD_DATA = " + json.dumps(data, ensure_ascii=False) + ";")
    return _file_jobs["data"], _file_jobs["text"], key, f"site/data.js ({len(_file_jobs['data']['jobs'])} roles)"


_all_db = {"build": None, "data": None, "checked": 0}
_all_file = {"key": None, "data": None}


def all_jobs():
    """Every US posting, labelled by category and level (pipeline/expand.py): (data, version key, source label).
    From the cohort database (kind "all") when loaded there, else data/all_jobs.json, else None."""
    if isinstance(STORE, RemoteStore) and time.time() - _all_db["checked"] > 60:
        _all_db["checked"] = time.time()
        try:
            status, v = STORE.call("GET", "/v1/jobs/version?kind=all")
            if status == 404:
                _all_db.update(build=None, data=None)
            elif status == 200 and v["build_id"] != _all_db["build"]:
                data, offset, page = None, 0, 5000                 # in pages: the full set is large
                while True:
                    status, part = STORE.call("GET", f"/v1/jobs?kind=all&limit={page}&offset={offset}", timeout=120)
                    if status != 200 or part.get("build_id") != v["build_id"]:
                        data = None                                 # failed, or a new build arrived mid-way: retry later
                        break
                    if data is None:
                        data = part
                    else:
                        data["jobs"].extend(part["jobs"])
                    if len(part["jobs"]) < page:
                        break
                    offset += page
                if data and data.get("jobs"):
                    _all_db.update(build=v["build_id"], data=data)
                else:
                    _all_db["checked"] = 0
        except (OSError, RuntimeError, ValueError, KeyError) as e:
            sys.stderr.write(f"all jobs from the cohort database unavailable ({e})\n")
    if _all_db["data"]:
        return _all_db["data"], "db:" + _all_db["build"], f"cohort database ({len(_all_db['data']['jobs'])} roles)"
    f = REPO / "data" / "all_jobs.json"
    if not f.exists():
        return None, None, "not built yet (run pipeline/expand.py)"
    key = f"file:{f.stat().st_mtime}"
    if _all_file["key"] != key:
        _all_file.update(key=key, data=json.loads(f.read_text(encoding="utf-8")))
    return _all_file["data"], key, f"data/all_jobs.json ({len(_all_file['data']['jobs'])} roles)"


def board_companies():
    names = {j["company"] for j in board_data()[0].get("jobs", [])}
    everything = all_jobs()[0]
    if everything:
        names |= {j["company"] for j in everything["jobs"]}
    page = (SITE / "index.html").read_text(encoding="utf-8")
    names |= set(re.findall(r'\{ co: "([^"]+)"', page))          # careers-page cards (DIRECT)
    return names


class LocalStore:
    """cohort.db (read-only) plus a JSON file for hand-added connections."""
    label = "local files"

    def snapshot(self):
        snap = {"people": [], "parents": [], "aliases": [], "counts": [], "contact_buckets": [],
                "unique_by_company": [], "unique_by_root": [], "manual": read_manual(), "shared": [], "shared_links": []}
        if not COHORT_DB.exists():
            return snap
        con = sqlite3.connect(f"file:{COHORT_DB}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        rows = lambda sql: [dict(r) for r in con.execute(sql)]
        snap["people"] = [{"person_id": r["person_id"], "updated_at": r["updated_at"],
                           "display_name": f'{r["first_name"] or ""} {r["last_name"] or ""}'.strip() or r["person_id"],
                           "profile_url": r["profile_url"] if "profile_url" in r.keys() else None,
                           "has_self_key": int(bool(r["self_key"])) if "self_key" in r.keys() else 0}
                          for r in con.execute("SELECT * FROM people")]
        snap["parents"] = rows("SELECT company_norm, parent_norm FROM companies WHERE parent_norm IS NOT NULL")
        snap["aliases"] = rows("SELECT alias, company_norm FROM aliases")
        names = {r["name"] for r in con.execute("SELECT name FROM sqlite_master")}
        if "shared_contacts" not in names:           # database from before contact keys
            snap["counts"] = rows("SELECT connector_id, company_norm, count, top_title_bucket FROM derived_connections")
            con.close()
            return snap
        # Same queries as the cloud API (cohort-api/src/index.js).
        snap["counts"] = rows("SELECT connector_id, company_norm, count, top_title_bucket FROM derived_connections "
                              "WHERE connector_id NOT IN (SELECT connector_id FROM contacts)")
        snap["contact_buckets"] = rows("SELECT connector_id, company_norm, title_bucket, COUNT(*) AS n FROM contacts GROUP BY 1, 2, 3")
        snap["unique_by_company"] = rows("SELECT company_norm, COUNT(DISTINCT contact_key) AS n FROM contacts GROUP BY 1")
        snap["unique_by_root"] = rows(
            "SELECT COALESCE(c.parent_norm, k.company_norm) AS company_norm, COUNT(DISTINCT k.contact_key) AS n "
            "FROM contacts k LEFT JOIN companies c ON c.company_norm = k.company_norm GROUP BY 1")
        snap["shared"] = rows(
            "SELECT s.contact_key, s.company_norm, c.display_name, s.title_bucket, s.depth, s.first_connected_year "
            "FROM shared_contacts s LEFT JOIN companies c ON c.company_norm = s.company_norm "
            "ORDER BY s.depth DESC, s.first_connected_year")
        snap["shared_links"] = rows("SELECT k.contact_key, k.connector_id, k.connected_year "
                                    "FROM contacts k JOIN shared_contacts s ON s.contact_key = k.contact_key")
        snap["knows"] = rows("SELECT p.person_id AS classmate, k.connector_id AS knower FROM people p "
                             "JOIN contacts k ON k.contact_key = p.self_key WHERE p.self_key IS NOT NULL")
        snap["positions"] = rows("SELECT person_id, company_norm, title, title_bucket, started_on, finished_on, is_current "
                                 "FROM positions WHERE company_norm IS NOT NULL")
        con.close()
        return snap

    def add(self, entry):
        with LOCK:
            entries = read_manual()
            entries.append(entry)
            write_manual(entries)
        return entry

    def delete(self, entry_id):
        with LOCK:
            entries = read_manual()
            kept = [e for e in entries if e["id"] != entry_id]
            write_manual(kept)
        return len(kept) < len(entries)


class RemoteStore:
    """The cohort API on Cloudflare (cohort-api/). The token stays on this computer, never in the browser."""

    def __init__(self, url, token):
        self.url, self.token = url.rstrip("/"), token
        self.label = self.url

    def call(self, method, path, body=None, timeout=20):
        req = urllib.request.Request(self.url + path, method=method,
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json",
                                              "User-Agent": "cohort-board"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
                return r.status, json.loads(raw) if raw else None
        except urllib.error.HTTPError as e:
            return e.code, None

    def snapshot(self):
        status, data = self.call("GET", "/v1/snapshot")
        if status != 200:
            raise RuntimeError(f"cohort API returned {status}")
        return data

    def add(self, entry):
        status, data = self.call("POST", "/v1/manual", {k: entry[k] for k in ("company", "classmate", "contact", "title", "note")})
        if status != 201:
            raise RuntimeError(f"cohort API returned {status}")
        return data

    def delete(self, entry_id):
        status, _ = self.call("DELETE", f"/v1/manual/{entry_id}")
        if status not in (204, 404):
            raise RuntimeError(f"cohort API returned {status}")
        return status == 204


def make_store():
    cfg = dict(os.environ)
    if (HERE / ".api").exists():
        for line in (HERE / ".api").read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                cfg.setdefault(k.strip(), v.strip())
    if cfg.get("COHORT_API_URL") and cfg.get("COHORT_API_TOKEN"):
        return RemoteStore(cfg["COHORT_API_URL"], cfg["COHORT_API_TOKEN"])
    return LocalStore()


STORE = make_store()
_snap = {"at": 0, "value": None}


def get_snapshot(fresh=False):
    if fresh or not _snap["value"] or time.time() - _snap["at"] > 30:
        _snap.update(at=time.time(), value=STORE.snapshot())
    return _snap["value"]


def shared_item(row, links, people):
    """One deep connection, without the key: the browser never needs it."""
    who = sorted(links.get(row["contact_key"], []), key=lambda x: (x[1] or 9999, x[0]))
    return {"depth": row["depth"], "bucket": row["title_bucket"], "since": row["first_connected_year"],
            "connectors": [people.get(pid, pid) for pid, _ in who]}


def _year(s):
    m = re.search(r"\b(19|20)\d{2}\b", s or "")
    return int(m.group(0)) if m else None


def worked_here(rows, people):
    """Classmates' own jobs at one company, one entry per classmate: current first, then most recent."""
    by_person = {}
    for r in rows:
        by_person.setdefault(r["person_id"], []).append(r)
    out = []
    for pid, jobs in by_person.items():
        current = any(j["is_current"] for j in jobs)
        starts = [y for y in (_year(j["started_on"]) for j in jobs) if y]
        ends = [y for y in (_year(j["finished_on"]) for j in jobs) if y]
        first, last = (min(starts) if starts else None), (None if current else (max(ends) if ends else None))
        years = (f"{first}–present" if current and first else f"{first}–{last}" if first and last and first != last
                 else str(first or last or ""))
        latest = max(jobs, key=lambda j: (bool(j["is_current"]), _year(j["finished_on"]) or 0, _year(j["started_on"]) or 0))
        out.append({"name": people.get(pid, pid), "title": latest["title"] or "", "bucket": latest["title_bucket"],
                    "years": years, "current": current, "_sort": (not current, -(last or first or 0))})
    out.sort(key=lambda a: a.pop("_sort"))
    return out


def connections_by_board_company(snap, names):
    """Returns ({board company: {"total", "connectors", "shared"}}, bridges).

    total = unique contacts (deduplicated by contact key) + counts from older loads that have no keys.
    A classmate's "mostly X" is only given when X is at least half of their keyed contacts there.
    shared = contacts at that company known by 2+ classmates; bridges = all of them, board or not.
    """
    people = {p["person_id"]: p["display_name"] for p in snap["people"]}
    links, shared_by_norm, board_of = {}, {}, {}
    for r in snap.get("shared_links", []):
        links.setdefault(r["contact_key"], []).append((r["connector_id"], r["connected_year"]))
    for r in snap.get("shared", []):
        shared_by_norm.setdefault(r["company_norm"], []).append(r)
    aliases = {a["alias"]: a["company_norm"] for a in snap["aliases"]}
    children = {}
    for r in snap["parents"]:
        children.setdefault(r["parent_norm"], []).append(r["company_norm"])
    counts, buckets = {}, {}
    for r in snap["counts"]:
        counts.setdefault(r["company_norm"], []).append(r)
    for r in snap["contact_buckets"]:
        buckets.setdefault(r["company_norm"], []).append(r)
    uniq_co = {r["company_norm"]: r["n"] for r in snap["unique_by_company"]}
    uniq_root = {r["company_norm"]: r["n"] for r in snap["unique_by_root"]}
    jobs_at = {}
    for r in snap.get("positions", []):
        jobs_at.setdefault(r["company_norm"], []).append(r)

    out = {}
    for name in names:
        norm = rules.normalize_company(name)
        if not norm:
            continue
        resolved = aliases.get(norm) or aliases.get(rules.compress(norm)) or norm
        norms = [resolved] + children.get(resolved, [])          # a subsidiary's contacts count toward its parent
        for n in norms:
            board_of.setdefault(n, name)
        per = {}
        for n in norms:
            for r in counts.get(n, []):
                c = per.setdefault(r["connector_id"], {"count": 0, "legacy": Counter(), "keyed": Counter()})
                c["count"] += r["count"]
                c["legacy"][r["top_title_bucket"]] += r["count"]
            for r in buckets.get(n, []):
                c = per.setdefault(r["connector_id"], {"count": 0, "legacy": Counter(), "keyed": Counter()})
                c["count"] += r["n"]
                c["keyed"][r["title_bucket"]] += r["n"]
        alumni = worked_here([r for n in norms for r in jobs_at.get(n, [])], people)
        if not per and not alumni:
            continue
        connectors = []
        for pid, c in sorted(per.items(), key=lambda kv: -kv[1]["count"]):
            if c["keyed"]:
                top, n = c["keyed"].most_common(1)[0]
                bucket = top if n * 2 >= sum(c["keyed"].values()) else "other"
            else:
                bucket = c["legacy"].most_common(1)[0][0]
            connectors.append({"name": people.get(pid, pid), "count": c["count"], "bucket": bucket,
                               "buckets": dict(c["keyed"] + c["legacy"]), "exact": not c["legacy"]})
        keyed_unique = uniq_root.get(resolved, 0) if children.get(resolved) else uniq_co.get(resolved, 0)
        legacy = sum(sum(c["legacy"].values()) for c in per.values())
        shared = [shared_item(r, links, people) for n in norms for r in shared_by_norm.get(n, [])]
        shared.sort(key=lambda s: (-s["depth"], s["since"] or 9999))
        out[name] = {"total": keyed_unique + legacy, "connectors": connectors, "shared": shared, "alumni": alumni}

    bridges = []
    for r in snap.get("shared", []):
        item = shared_item(r, links, people)
        item["company"] = board_of.get(r["company_norm"]) or r.get("display_name") or r["company_norm"]
        item["on_board"] = r["company_norm"] in board_of
        bridges.append(item)
    bridges.sort(key=lambda s: (-s["depth"], s["since"] or 9999, s["company"]))
    return out, bridges[:1000]


def cohort_payload(fresh=False):
    key = (board_data()[2], all_jobs()[1], (SITE / "index.html").stat().st_mtime)
    if _cache["key"] != key:
        _cache.update(key=key, value={"names": board_companies()})
    snap = get_snapshot(fresh)
    manual = {}
    for e in snap["manual"]:
        manual.setdefault(e["company"], []).append(e)
    classmates = sorted({p["display_name"] for p in snap["people"]} | {e["classmate"] for e in snap["manual"]})
    companies, bridges = connections_by_board_company(snap, _cache["value"]["names"])
    return {"companies": companies, "bridges": bridges, "manual": manual,
            "classmates": classmates, "source": STORE.label, "people": people_summary(snap, settings().get("me")),
            "me": settings().get("me"), "ai_available": ai_available(), "can_upload": bool(contact_keys.load_secret())}


DESCRIPTIONS = REPO / "data" / "descriptions.db"


def job_description(url):
    """{company, title, text} for one posting link, from the store pipeline/descriptions.py builds; None if absent."""
    if not url or not DESCRIPTIONS.exists():
        return None
    import zlib
    con = sqlite3.connect(f"file:{DESCRIPTIONS}?mode=ro", uri=True)
    try:
        row = con.execute("SELECT company, title, text FROM descriptions WHERE url = ?", (url,)).fetchone()
    finally:
        con.close()
    return {"company": row[0], "title": row[1], "text": zlib.decompress(row[2]).decode("utf-8")} if row else None


def my_history_titles():
    """Job titles from the board user's own loaded LinkedIn export (the "I am" choice), for their categories."""
    me = settings().get("me")
    if not me:
        return []
    try:
        return [r["title"] for r in get_snapshot().get("positions", []) if r["person_id"] == me and r.get("title")]
    except (RuntimeError, OSError):
        return []


_cohort_map = {"key": None, "value": None}


def find_cohort_map():
    """Cached per cohort snapshot and job set, so the same dict comes back and search's ranking cache can hold."""
    snap = get_snapshot()
    key = (id(snap), _cache["key"], len(read_manual()))
    if _cohort_map["key"] != key:
        _cohort_map.update(key=key, value=_find_cohort_map())
    return _cohort_map["value"]


def _find_cohort_map():
    """Everyone in the cohort database tied to each company, for the job cards' dropdown on Find a job.

    {company: {"people": [...], "classmates": n, "contacts": n, "alumni": [names], "shared": n}}. Each person:
    {name, worked: {title, years, current} | None, count, bucket, added: [{contact, title, note}]}.
    Order: classmates who work or worked there first (current first), then by number of connections there."""
    payload = cohort_payload()
    out = {}
    for name in set(payload["companies"]) | set(payload["manual"]):
        c = payload["companies"].get(name) or {}
        tie = cohort_people(c, payload["manual"].get(name) or [])
        if tie:
            out[name] = tie
    return out


def cohort_people(c, manual):
    """Everyone tied to one company: {people, classmates, contacts, alumni, shared}, or None.

    c is one entry of connections_by_board_company(); manual is the hand-added connections there. Order: classmates
    who work or worked there first (current first), then by number of connections there."""
    people = {}

    def person(n):
        return people.setdefault(n, {"name": n, "worked": None, "count": 0, "bucket": None, "added": []})
    for a in c.get("alumni") or []:
        person(a["name"])["worked"] = {"title": a.get("title"), "years": a.get("years"), "current": a.get("current")}
    for k in c.get("connectors") or []:
        p = person(k["name"])
        p["count"], p["bucket"] = k["count"], k["bucket"]
        p["buckets"], p["exact"] = k.get("buckets") or {}, k.get("exact", True)
    for m in manual:
        person(m["classmate"])["added"].append({"contact": m.get("contact"), "title": m.get("title"), "note": m.get("note")})
    if not people:
        return None
    ranked = sorted(people.values(), key=lambda p: (p["worked"] is None, not (p["worked"] or {}).get("current"),
                                                    -(p["count"] + len(p["added"])), p["name"].lower()))
    return {"people": ranked, "classmates": len(ranked),
            "contacts": (c.get("total") or 0) + sum(len(p["added"]) for p in ranked),
            "alumni": [p["name"] for p in ranked if p["worked"]], "shared": len(c.get("shared") or [])}


_dir_jobs = {"key": None, "value": None}


def directory_payload():
    """The Companies tab: every company in data/companies.db with its cohort ties and job counts, ranked.

    Rank: a classmate works there, then a classmate worked there, then number of connections, then open roles.
    Jobs come from the full labelled set (Find a job) plus Ryan's board; links open Find a job filtered to the company."""
    d = directory.load()
    if not d:
        return {"ready": False, "companies": []}
    everything = all_jobs()
    board = board_data()
    key = (d["version"], everything[1], board[2])
    if _dir_jobs["key"] != key:
        jobs = list((everything[0] or {}).get("jobs") or [])
        seen = {j.get("url") for j in jobs}
        jobs += [j for j in board[0].get("jobs", []) if j.get("url") not in seen]
        _dir_jobs.update(key=key, value=directory.job_index(jobs, d["names"]))
    jobs_by_id = _dir_jobs["value"]
    warning = None
    try:
        snap = get_snapshot()
        ties, _ = connections_by_board_company(snap, [c["cohort_name"] for c in d["companies"]])
    except (RuntimeError, OSError) as e:                 # cloud down: use the local cohort.db copy, else no ties
        try:
            snap = LocalStore().snapshot()
            ties, _ = connections_by_board_company(snap, [c["cohort_name"] for c in d["companies"]])
            warning = f"Cloud cohort database unavailable ({e}); showing ties from this computer's copy."
        except (RuntimeError, OSError, sqlite3.Error) as e2:
            snap, ties, warning = {"manual": []}, {}, f"Cohort connections unavailable ({e}; {e2})."
    manual = {}
    for e in snap["manual"]:
        cid = directory.company_id(e["company"], d["names"])
        if cid:
            manual.setdefault(cid, []).append(e)
    out = []
    for c in d["companies"]:
        tie = cohort_people(ties.get(c["cohort_name"]) or {}, manual.get(c["id"], [])) or {}
        row = {k: v for k, v in c.items() if k != "cohort_name"}
        row.update(people=tie.get("people") or [], contacts=tie.get("contacts") or 0, shared=tie.get("shared") or 0,
                   jobs=jobs_by_id.get(c["id"]))
        out.append(row)
    out.sort(key=directory.rank_key)
    return {"ready": True, "companies": out, "verticals": list(directory_verticals()), "warning": warning}


_co_vert = {"key": None, "value": {}}


def job_company_verticals():
    """{job feed company name: vertical} for companies the company database knows (cached per database and job set)."""
    d = directory.load()
    data, version, _ = all_jobs()
    if not d or not data:
        return {}
    if _co_vert["key"] != (d["version"], version):
        vert = {c["id"]: c["vertical"] for c in d["companies"]}
        out = {}
        for co in {j["company"] for j in data["jobs"]}:
            cid = directory.company_id(co, d["names"])
            if cid in vert and vert[cid] != "Other":
                out[co] = vert[cid]
        _co_vert.update(key=(d["version"], version), value=out)
    return _co_vert["value"]


# ---------- one company: the relationship graph and the best ways in ----------

# A job's broad category -> the contact title buckets that work in that field (for "knows N people in your field").
FIELD_BUCKETS = {"Consulting": {"consulting"}, "Strategy & Operations": {"operations", "consulting"}, "Finance": {"finance"},
                 "Data & Analytics": {"data_ml"}, "Product": {"product", "design"}, "Marketing & Growth": {"marketing"},
                 "Sales & Business Development": {"sales_gtm"}, "Operations & Supply Chain": {"operations"},
                 "Technology & Engineering": {"engineering", "data_ml"}, "People & HR": {"recruiting"}, "Legal & Policy": {"legal"}}
BUCKET_LABEL = {"engineering": "engineering", "data_ml": "data / ML", "product": "product", "design": "design",
                "recruiting": "recruiting", "sales_gtm": "sales / GTM", "marketing": "marketing", "finance": "finance",
                "consulting": "consulting", "research": "research", "operations": "operations", "legal": "legal",
                "healthcare": "healthcare", "education": "education", "student_intern": "students / interns",
                "leadership": "leadership", "other": "other roles"}


def company_norms(snap, name):
    """The database's company keys for a company name: its own (through aliases) plus its units."""
    norm = rules.normalize_company(name)
    if not norm:
        return []
    aliases = {a["alias"]: a["company_norm"] for a in snap["aliases"]}
    resolved = aliases.get(norm) or aliases.get(rules.compress(norm)) or norm
    return [resolved] + [r["company_norm"] for r in snap["parents"] if r["parent_norm"] == resolved]


# ---------- who is who: a contact's function and seniority, from their title ----------

TIERS = ["Leadership", "Senior", "Mid", "Early career"]
_T_EARLY = re.compile(r"\b(intern|internship|summer|student|trainee|apprentice|fellow|graduate)\b", re.I)
_T_LEAD = re.compile(r"\b(chief|ceo|cfo|coo|cto|cmo|cio|cpo|president|founder|co-founder|partner|managing director|md|"
                     r"vice president|vp|svp|evp|avp|head of|director|general manager|gm)\b", re.I)
_T_SENIOR = re.compile(r"\b(senior|sr|lead|principal|manager|staff|expert|specialist lead)\b", re.I)
_T_JUNIOR = re.compile(r"\b(analyst|coordinator|assistant|junior|jr|associate consultant)\b", re.I)
# Titles that only say "where" by the company's line of work: an Associate at a consulting firm consults,
# a VP at a bank does finance.
_VERTICAL_FUNCTION = {"Consulting": "Consulting", "Financial Services": "Finance"}
_GENERIC_TITLE = re.compile(r"\b(associate|consultant|partner|principal|analyst|vice president|vp|managing director|md|"
                            r"director|manager|summer associate|engagement manager|fellow)\b", re.I)


def seniority(title):
    t = title or ""
    if _T_EARLY.search(t):
        return "Early career"
    if re.search(r"talent|recruit|\bhr\b|human resources|people|business partner", t, re.I):
        t = re.sub(r"\bpartner\b", "", t, flags=re.I)        # an HR or recruiting "partner" isn't a firm partner
    if _T_LEAD.search(t):
        return "Leadership"
    if _T_SENIOR.search(t):
        return "Senior"
    if _T_JUNIOR.search(t):
        return "Early career"
    return "Mid"


def function_of(title, vertical):
    """The board's broad categories (same title rules as Find a job); generic titles take the company's line of work."""
    f = find.cats.category(title or "") if title else "Other"
    if f == "Other" and vertical in _VERTICAL_FUNCTION and _GENERIC_TITLE.search(title or ""):
        return _VERTICAL_FUNCTION[vertical]
    return f


def named_contacts(norms, people_names, field=None):
    """People your cohort knows at a company, by name: [{name, position, url, bucket, known_by: [{name, since}]}].

    Read from this computer's cohort.db (every upload goes through it), so names work whatever the cloud holds.
    Classmates themselves are left out. Order: known by the most classmates, then the job's field, recruiting and
    leadership, then name."""
    if not norms or not COHORT_DB.exists():
        return []
    con = sqlite3.connect(f"file:{COHORT_DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        cols = {r[1] for r in con.execute("PRAGMA table_info(contacts)")}
        if "full_name" not in cols:
            return []
        selves = {r[0] for r in con.execute("SELECT self_key FROM people WHERE self_key IS NOT NULL")}
        rows = con.execute(f"""SELECT contact_key, connector_id, title_bucket, connected_year, full_name, position, profile_url
                               FROM contacts WHERE company_norm IN ({','.join('?' * len(norms))})""", norms).fetchall()
    finally:
        con.close()
    by = {}
    for r in rows:
        if r["contact_key"] in selves:
            continue
        c = by.setdefault(r["contact_key"], {"name": None, "position": None, "url": None, "bucket": r["title_bucket"], "known_by": []})
        c["name"] = c["name"] or r["full_name"]
        c["position"] = c["position"] or r["position"]
        c["url"] = c["url"] or r["profile_url"]
        c["known_by"].append({"name": people_names.get(r["connector_id"], r["connector_id"]), "since": r["connected_year"]})
    want = FIELD_BUCKETS.get(field or "", set())
    out = [c for c in by.values() if c["name"]]
    for c in out:
        c["known_by"].sort(key=lambda k: (k["since"] or 9999, k["name"]))
    out.sort(key=lambda c: (-len(c["known_by"]), c["bucket"] not in want, c["bucket"] != "recruiting",
                            c["bucket"] != "leadership", c["name"].lower()))
    return out


_SENIOR = re.compile(r"\b(chief|c[efotmi]o|president|vp|vice president|svp|evp|head of|director|partner|principal|"
                     r"managing director|\bmd\b|founder|general manager|gm)\b", re.I)
_RECRUIT = re.compile(r"recruit|talent acquisition|campus|university relations|sourcer", re.I)


def meaningful_shared(shared, people, me, field=None):
    """Contacts known by 2+ classmates, most meaningful first, each with plain reasons. No learning, just points:

    known by more classmates · known by a classmate who worked at the company (likely a colleague) · senior title ·
    recruiter · in the job's field · a long-standing connection (earliest year)."""
    want = FIELD_BUCKETS.get(field or "", set())
    alumni = {p["name"]: p["worked"] for p in people if p.get("worked")}
    this_year = datetime.now().year
    out = []
    for x in shared:
        title = x.get("position") or ""
        who = x.get("connectors") or []
        pts, why = 20.0 * len(who), [f"Known by {len(who)} classmates"]
        colleagues = [n for n in who if n in alumni]
        if colleagues:
            pts += 25
            now = len(colleagues) == 1 and alumni[colleagues[0]].get("current")
            why.append("Known by " + " and ".join(colleagues[:2]) + (", who works here" if now else ", who worked here"))
        tier = seniority(title) if title else ("Leadership" if x.get("bucket") == "leadership" else "Mid")
        if tier == "Leadership":
            pts += 15
            why.append("Leadership")
        elif tier == "Senior":
            pts += 7
            why.append("Senior")
        if _RECRUIT.search(title) or x.get("bucket") == "recruiting":
            pts += 12
            why.append("Recruiting")
        if x.get("bucket") in want:
            pts += 10
            why.append("In " + field)
        since = x.get("since")
        if since:
            years = max(0, this_year - since)
            pts += min(10, years)
            if years >= 5:
                why.append(f"Connected since {since}")
        if me and me in who:
            why.append("You know them too")
        out.append({**x, "score": round(pts), "why": why})
    out.sort(key=lambda x: (-x["score"], (x.get("name") or "~").lower()))
    return out


def best_ways_in(people, shared, knows, me, field=None, named=None):
    """Rank the ways into a company, strongest first. No learning: points for clear signals, each one explained.

    A classmate who works there now beats one who worked there, who beats one who only knows people there. Knowing
    people in the job's field, recruiters, or leaders adds points; so does sharing contacts with other classmates and
    already being connected to you."""
    want = FIELD_BUCKETS.get(field or "", set())
    ways = []
    for p in people:
        if p["name"] == me:
            continue
        pts, why = 0.0, []
        w = p.get("worked")
        if w:
            pts += 100 if w.get("current") else 70
            why.append(("works here now" if w.get("current") else "worked here") +
                        (f" as {w['title']}" if w.get("title") else "") + (f" ({w['years']})" if w.get("years") else ""))
        n = p.get("count") or 0
        if n:
            import math
            pts += min(40.0, 8 * math.log2(1 + n))
            why.append(f"knows {n} {'person' if n == 1 else 'people'} here")
        b = p.get("buckets") or {}
        in_field = sum(v for k, v in b.items() if k in want)
        if in_field:
            pts += 15
            why.append(f"{in_field} in {field}")
        if b.get("recruiting"):
            pts += 10
            why.append(f"{b['recruiting']} in recruiting")
        if b.get("leadership"):
            pts += 8
            why.append(f"{b['leadership']} in leadership")
        mine = [s for s in shared if p["name"] in s["connectors"]]
        if mine:
            pts += min(36, 12 * len(mine))
            why.append(f"shares {len(mine)} contact{'s' if len(mine) != 1 else ''} here with other classmates")
        for a in p.get("added") or []:
            pts += 25
            why.append("knows " + ", ".join(x for x in (a.get("contact"), a.get("title")) if x))
        if me and (p["name"], me) in knows or (me, p["name"]) in knows:
            pts += 10
            why.append("you're connected")
        if pts:
            ways.append({"kind": "classmate", "name": p["name"], "score": round(pts), "why": why[:4]})
    if named:
        intros = 0
        for c in named:
            others = [k for k in c["known_by"] if k["name"] != me]
            if not others:
                continue
            relevant = c["bucket"] in want or c["bucket"] in ("recruiting", "leadership")
            if len(c["known_by"]) < 2 and not relevant:
                continue
            pts = (30 + 10 * len(c["known_by"]) if len(c["known_by"]) >= 2 else 22) + (8 if c["bucket"] in want else 0) + \
                  (6 if c["bucket"] == "recruiting" else 0)
            who = " and ".join(k["name"] for k in others[:2]) + (f" (+{len(others) - 2})" if len(others) > 2 else "")
            since = min((k["since"] for k in others if k["since"]), default=None)
            ways.append({"kind": "contact", "name": f"Ask {who} to introduce you to {c['name']}", "score": pts, "url": c["url"],
                         "why": [x for x in (c["position"], f"known by {len(c['known_by'])} classmates" if len(c["known_by"]) > 1 else None,
                                             f"connected since {since}" if since else None) if x]})
            intros += 1
            if intros >= 4:
                break
    else:
        for s in shared:
            pts = 30 + 10 * s["depth"] + (5 if s.get("bucket") in want else 0)
            role = BUCKET_LABEL.get(s.get("bucket"), "someone")
            ways.append({"kind": "shared", "name": f"A {role} contact known by {s['depth']} classmates", "score": pts,
                         "why": [("known by " + ", ".join(s["connectors"])) + (f", since {s['since']}" if s.get("since") else "")]})
    ways.sort(key=lambda w: -w["score"])
    return ways[:8]


def company_detail(cid=None, name=None, field=None):
    """Everything the company page shows: the directory entry, its jobs, the relationship graph and the best ways in."""
    d = directory.load()
    if not d:
        return None
    if not cid and name:
        cid = directory.company_id(name, d["names"])
    c = next((x for x in d["companies"] if x["id"] == cid), None)
    if not c:
        return None
    try:
        snap = get_snapshot()
    except (RuntimeError, OSError):
        snap = LocalStore().snapshot()
    ties, _ = connections_by_board_company(snap, [c["cohort_name"]])
    raw = ties.get(c["cohort_name"]) or {}
    manual = [e for e in snap["manual"] if directory.company_id(e["company"], d["names"]) == cid]
    tie = cohort_people(raw, manual) or {"people": [], "contacts": 0}
    names = {p["person_id"]: p["display_name"] for p in snap["people"]}
    knows = {(names.get(r["knower"], r["knower"]), names.get(r["classmate"], r["classmate"])) for r in snap.get("knows", [])}
    in_graph = {p["name"] for p in tie["people"]}
    me = names.get(settings().get("me") or "")
    jobs = (_dir_jobs["value"] or {}).get(cid) if _dir_jobs["value"] is not None else None
    if _dir_jobs["value"] is None:
        directory_payload()
        jobs = (_dir_jobs["value"] or {}).get(cid)
    named = named_contacts(company_norms(snap, c["cohort_name"]), names, field)
    for x in named:
        x["function"], x["tier"] = function_of(x["position"], c["vertical"]), seniority(x["position"])
    shared = ([{"depth": len(x["known_by"]), "bucket": x["bucket"], "since": min((k["since"] for k in x["known_by"] if k["since"]), default=None),
                "connectors": [k["name"] for k in x["known_by"]], "name": x["name"], "position": x["position"], "url": x["url"],
                "known_by": x["known_by"]}
               for x in named if len(x["known_by"]) > 1] if named else raw.get("shared") or [])
    shared = meaningful_shared(shared, tie["people"], me, field)
    row = {k: v for k, v in c.items() if k != "cohort_name"}
    row.update(people=tie["people"], contacts=tie.get("contacts", 0), shared=shared, jobs=jobs,
               knows=[[a, b] for a, b in knows if a in in_graph and b in in_graph], me=me, field=field,
               ways=best_ways_in(tie["people"], shared, knows, me, field, named),
               named=named[:800], named_total=len(named), bucket_labels=BUCKET_LABEL, tiers=TIERS)
    return row


# ---------- the map: who's there in a region ----------

_named_rows = {"key": None, "rows": []}


def all_named_rows():
    """Every named contact in this computer's cohort.db (cached until the file changes)."""
    if not COHORT_DB.exists():
        return []
    key = COHORT_DB.stat().st_mtime
    if _named_rows["key"] != key:
        con = sqlite3.connect(f"file:{COHORT_DB}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        try:
            if "full_name" not in {r[1] for r in con.execute("PRAGMA table_info(contacts)")}:
                rows = []
            else:
                selves = {r[0] for r in con.execute("SELECT self_key FROM people WHERE self_key IS NOT NULL")}
                rows = [dict(r) for r in con.execute("""SELECT contact_key, connector_id, company_norm, title_bucket, connected_year,
                                                         full_name, position, profile_url FROM contacts WHERE full_name IS NOT NULL""")
                        if r["contact_key"] not in selves]
        finally:
            con.close()
        _named_rows.update(key=key, rows=rows)
    return _named_rows["rows"]


_pos_rows = {"key": None, "rows": None}


def local_positions():
    """Classmates' own jobs from this computer's cohort.db, with where each was (cached until the file changes)."""
    if not COHORT_DB.exists():
        return None
    key = COHORT_DB.stat().st_mtime
    if _pos_rows["key"] != key:
        con = sqlite3.connect(f"file:{COHORT_DB}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        try:
            has_loc = "location" in {r[1] for r in con.execute("PRAGMA table_info(positions)")}
            rows = [dict(r) for r in con.execute(
                "SELECT person_id, company_norm, title, started_on, finished_on, is_current" + (", location" if has_loc else ", NULL AS location") +
                " FROM positions WHERE company_norm IS NOT NULL")]
            geo = dict(con.execute("SELECT person_id, geo_location FROM people").fetchall())
        finally:
            con.close()
        _pos_rows.update(key=key, rows={"positions": rows, "geo": geo})
    return _pos_rows["rows"]


def _years(r):
    a, b = _year(r.get("started_on")), _year(r.get("finished_on"))
    return f"{a}–present" if r.get("is_current") and a else f"{a}–{b}" if a and b and a != b else str(a or b or "")


def region_people(picked, field=None):
    """Who's there in some map regions: companies with an office, HQ or open roles there that your cohort is tied to,
    the people your cohort knows at them (ranked like the shared connections), and classmates based there.

    Contacts' own locations aren't in LinkedIn exports, so "there" means "at a company that's there"."""
    picked = set(picked)
    d = directory.load()
    if not d or not picked:
        return {"regions": sorted(picked), "people": [], "companies": [], "classmates": [], "jobs": 0}
    names_ix = d["names"]
    in_region = {c["id"] for c in d["companies"] if picked.intersection(c["regions"])}
    jobs_here, jobs_total, memo = Counter(), 0, {}
    data = all_jobs()[0]
    if data:
        regs = find.job_regions(data)
        for j in data["jobs"]:
            if picked.intersection(regs[j["id"]]):
                jobs_total += 1
                co = j["company"]
                if co not in memo:
                    memo[co] = directory.company_id(co, names_ix)
                if memo[co]:
                    jobs_here[memo[co]] += 1
    by_co = {c["id"]: c for c in d["companies"]}
    in_region = (in_region | set(jobs_here)) & set(by_co)       # employers only (recruiters, schools stay out)
    try:
        snap = get_snapshot()
    except (RuntimeError, OSError):
        snap = LocalStore().snapshot()
    people_names = {p["person_id"]: p["display_name"] for p in snap["people"]}
    me = people_names.get(settings().get("me") or "")
    # classmates' own jobs: at each company here (a contact known by one of them is likely a colleague), and the
    # jobs that were in this region (where each job was comes from their Positions.csv)
    local = local_positions()
    positions = local["positions"] if local else snap.get("positions", [])
    alumni, alumni_here, worked_in_region, based = defaultdict(dict), defaultdict(set), [], set()
    for r in positions:
        name = people_names.get(r["person_id"], r["person_id"])
        cid = directory.company_id(r["company_norm"], names_ix)
        here = bool(r.get("location")) and bool(picked.intersection(regions.regions_for([r["location"]])))
        if here:
            worked_in_region.append({"name": name, "title": r.get("title") or "", "company": (by_co.get(cid) or {}).get("name") or r["company_norm"].title(),
                                     "company_id": cid if cid in by_co else None, "years": _years(r), "current": bool(r.get("is_current")),
                                     "location": r["location"]})
            if r.get("is_current"):
                based.add(name)
        if cid in in_region:
            alumni[cid][name] = alumni[cid].get(name) or bool(r["is_current"])
            if here:
                alumni_here[cid].add(name)
    norm_cid = {}
    people = {}
    for r in all_named_rows():
        n = r["company_norm"]
        if n not in norm_cid:
            norm_cid[n] = directory.company_id(n, names_ix)
        cid = norm_cid[n]
        if cid not in in_region:
            continue
        x = people.setdefault(r["contact_key"], {"name": r["full_name"], "position": r["position"], "url": r["profile_url"],
                                                 "bucket": r["title_bucket"], "company": by_co[cid]["name"], "company_id": cid,
                                                 "known_by": []})
        x["known_by"].append({"name": people_names.get(r["connector_id"], r["connector_id"]), "since": r["connected_year"]})
    want = FIELD_BUCKETS.get(field or "", set())
    this_year = datetime.now().year
    ranked = []
    for x in people.values():
        who = [k["name"] for k in x["known_by"]]
        title = x["position"] or ""
        pts, why = 20.0 * len(who), [f"Known by {len(who)} classmates"] if len(who) > 1 else []
        colleagues = [n for n in who if n in alumni.get(x["company_id"], {})]
        if colleagues:
            pts += 25
            why.append("Known by " + " and ".join(colleagues[:2]) + (", who works there" if alumni[x["company_id"]][colleagues[0]] else ", who worked there"))
        tier = seniority(title) if title else ("Leadership" if x["bucket"] == "leadership" else "Mid")
        if tier == "Leadership":
            pts += 15
            why.append("Leadership")
        elif tier == "Senior":
            pts += 7
            why.append("Senior")
        if _RECRUIT.search(title) or x["bucket"] == "recruiting":
            pts += 12
            why.append("Recruiting")
        if x["bucket"] in want:
            pts += 10
            why.append("In " + field)
        since = min((k["since"] for k in x["known_by"] if k["since"]), default=None)
        if since:
            pts += min(10, max(0, this_year - since))
            if this_year - since >= 5:
                why.append(f"Connected since {since}")
        x["known_by"].sort(key=lambda k: (k["since"] or 9999, k["name"]))
        ranked.append({**x, "score": round(pts), "why": why})
    ranked.sort(key=lambda x: (-x["score"], x["name"].lower()))
    # companies with ties here
    contacts_at = Counter(x["company_id"] for x in ranked)
    knowers = defaultdict(set)
    for x in ranked:
        knowers[x["company_id"]].update(k["name"] for k in x["known_by"])
    companies = []
    for cid in in_region:
        if not contacts_at.get(cid) and not alumni.get(cid):
            continue
        al = alumni.get(cid, {})
        companies.append({"id": cid, "name": by_co[cid]["name"], "vertical": by_co[cid]["vertical"], "contacts": contacts_at.get(cid, 0),
                          "classmates": sorted(knowers[cid] | set(al)),
                          "alumni": [{"name": n, "current": cur, "here": n in alumni_here[cid]} for n, cur in al.items()],
                          "jobs": jobs_here.get(cid, 0), "office": bool(picked.intersection(by_co[cid]["regions"]))})
    # an employer where a classmate's job was in this very region first
    companies.sort(key=lambda c: (not any(a["here"] for a in c["alumni"]), not any(a["current"] for a in c["alumni"]),
                                  not c["alumni"], -c["contacts"], -c["jobs"], c["name"].lower()))
    for pid, geo in (local["geo"].items() if local else []):
        if geo and picked.intersection(regions.regions_for([geo])):
            based.add(people_names.get(pid, pid))
    worked_in_region.sort(key=lambda w: (not w["current"], -(_year(w["years"].split("–")[-1]) or 9999 if w["current"] else _year(w["years"].split("–")[-1]) or 0), w["name"]))
    return {"regions": sorted(picked), "people": ranked[:300], "people_total": len(ranked), "companies": companies[:150],
            "companies_total": len(companies), "classmates": sorted(based), "worked_here": worked_in_region, "jobs": jobs_total,
            "me": me, "bucket_labels": BUCKET_LABEL}


def directory_verticals():
    sys.path.insert(0, str(REPO / "company-db"))
    from companies import VERTICALS
    return VERTICALS.keys()


def ai_available():
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


SETTINGS = DATA / "settings.json"     # which loaded classmate is the person using this board


def settings():
    """{"me": the classmate the signed-in person is}. Kept per login, so several people can share the hosted board;
    a single-user board's older choice (data/settings.json) still applies to logins that haven't picked."""
    rec = SESSIONS.get(getattr(_current, "key", None) or "") or {}
    if "me" in rec:
        return {"me": rec["me"]}
    try:
        return json.loads(SETTINGS.read_text(encoding="utf-8")) if not HOSTED else {}
    except (FileNotFoundError, ValueError):
        return {}


def save_settings(s):
    key = getattr(_current, "key", None)
    with LOCK:
        if key in SESSIONS:
            SESSIONS[key]["me"] = s.get("me")
            _save_sessions()


def people_summary(snap, me=None):
    """Loaded classmates, with whether each is already a LinkedIn connection of `me`.

    connected:     one of the two has the other in their export
    not_connected: we would have seen it (my export is fingerprinted and they have a key, or the reverse)
    unknown:       not enough to tell (a profile link or a fingerprinted export is missing)
    """
    keyed, legacy = Counter(), Counter()
    for r in snap["contact_buckets"]:
        keyed[r["connector_id"]] += r["n"]
    for r in snap["counts"]:
        legacy[r["connector_id"]] += r["count"]
    knows = {(r["knower"], r["classmate"]) for r in snap.get("knows", [])}
    has_key = {p["person_id"]: bool(p.get("has_self_key")) for p in snap["people"]}
    out = []
    for p in snap["people"]:
        pid = p["person_id"]
        status = None
        if me and pid != me and me in has_key:
            if (me, pid) in knows or (pid, me) in knows:
                status = "connected"
            elif (has_key[pid] and keyed[me]) or (has_key[me] and keyed[pid]):
                status = "not_connected"
            else:
                status = "unknown"
        out.append({"id": pid, "name": p["display_name"], "updated": (p.get("updated_at") or "")[:10],
                    "contacts": keyed[pid] or legacy[pid], "fingerprinted": bool(keyed[pid]),
                    "profile_url": p.get("profile_url"), "status": status})
    return sorted(out, key=lambda p: p["name"].lower())


def read_manual():
    try:
        return json.loads(MANUAL.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []


def write_manual(entries):
    MANUAL.parent.mkdir(exist_ok=True)
    tmp = MANUAL.with_suffix(".tmp")
    tmp.write_text(json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(MANUAL)
    state.push_later("manual_connections.json")


def clean(v, limit):
    return re.sub(r"\s+", " ", str(v or "")).strip()[:limit]


# ---------- HTTP ----------

LOGIN_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Cohort Job Board</title>
<style>
:root{--bg:#f6f8fa;--card:#fff;--text:#1f2933;--muted:#66727f;--border:rgba(31,41,51,.14);--brand:#0a66c2;--bad:#b42318}
body{margin:0;min-height:100vh;display:grid;place-items:center;background:var(--bg);color:var(--text);
 font:15px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;padding:16px;box-sizing:border-box}
form{background:var(--card);border:1px solid var(--border);border-radius:14px;padding:24px;width:100%;max-width:340px}
h1{font-size:20px;margin:0 0 4px}p{margin:0 0 16px;color:var(--muted);font-size:13.5px}
input{width:100%;box-sizing:border-box;font:inherit;padding:9px 11px;border:1px solid var(--border);border-radius:8px;margin-bottom:12px}
button{width:100%;font:inherit;font-weight:600;padding:9px;border:0;border-radius:8px;background:var(--brand);color:#fff;cursor:pointer}
.err{color:var(--bad);margin:0 0 12px}
</style></head><body><form method="post" action="/login">
<h1>Cohort Job Board</h1><p>Private test version. Runs on this computer only.</p>
%ERR%<input type="password" name="password" placeholder="Password" autofocus aria-label="Password" required>
<button type="submit">Open</button></form></body></html>"""

STATIC_FILES = {
    "/match_index.js": (SITE / "match_index.js", "application/javascript"),
    "/cohort.js": (STATIC / "cohort.js", "application/javascript"),
    "/cohort-upload.js": (STATIC / "cohort-upload.js", "application/javascript"),
    "/cohort-connect.js": (STATIC / "cohort-connect.js", "application/javascript"),
    "/cohort-timeline.js": (STATIC / "cohort-timeline.js", "application/javascript"),
    "/find.js": (STATIC / "find.js", "application/javascript"),
    "/find.css": (STATIC / "find.css", "text/css"),
    "/nav.css": (STATIC / "nav.css", "text/css"),
    "/describe.js": (STATIC / "describe.js", "application/javascript"),
    "/map.js": (STATIC / "map.js", "application/javascript"),
    "/map.css": (STATIC / "map.css", "text/css"),
    "/globalbar.js": (STATIC / "globalbar.js", "application/javascript"),
    "/cohort.css": (STATIC / "cohort.css", "text/css"),
    "/companies.js": (STATIC / "companies.js", "application/javascript"),
    "/companygraph.js": (STATIC / "companygraph.js", "application/javascript"),
    "/companies.css": (STATIC / "companies.css", "text/css"),
}


class Handler(BaseHTTPRequestHandler):
    server_version = "CohortBoard"

    def log_message(self, fmt, *args):
        sys.stderr.write("%s %s\n" % (datetime.now().strftime("%H:%M:%S"), fmt % args))

    def send(self, code, body=b"", ctype="text/plain; charset=utf-8", headers=None):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def token(self):
        c = SimpleCookie(self.headers.get("Cookie", ""))
        return c["cb_session"].value if "cb_session" in c else None

    def authed(self):
        return session_ok(self.token())

    def same_origin(self):
        """Writes must come from this board's own pages: the local addresses, or the hosted site's own address."""
        origin = self.headers.get("Origin")
        return origin in ORIGINS or (HOSTED and origin == f"https://{self.headers.get('Host', '')}")

    def body(self, limit=20000):
        n = int(self.headers.get("Content-Length") or 0)
        if n > limit:
            raise ValueError("too large")
        return self.rfile.read(n)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/login":
            return self.send(200, LOGIN_PAGE.replace("%ERR%", ""), "text/html; charset=utf-8")
        if path == "/favicon.ico":
            return self.send(204)
        if not self.authed():
            return self.send(303, headers={"Location": "/login"})
        try:
            if path in ("/", "/find"):                          # Find a job (the home page)
                return self.send(200, (STATIC / "find.html").read_bytes(), "text/html; charset=utf-8")
            if path == "/map":                                  # jobs by region on a US map
                return self.send(200, (STATIC / "map.html").read_bytes(), "text/html; charset=utf-8")
            if path == "/api/regions":
                return self.send(200, json.dumps(regions.REGIONS), "application/json")
            if path == "/companies" and "view=" not in self.path:  # the company directory (data/companies.db)
                return self.send(200, (STATIC / "companies.html").read_bytes(), "text/html; charset=utf-8")
            if path == "/api/companies":
                return self.send(200, json.dumps(directory_payload(), ensure_ascii=False), "application/json")
            if path == "/api/region-people":                    # the map: who's there in the picked regions
                qs = parse_qs(urlsplit(self.path).query)
                return self.send(200, json.dumps(region_people(qs.get("region") or [], (qs.get("field") or [None])[0]),
                                                 ensure_ascii=False), "application/json")
            if path == "/api/company":                          # one company: relationship graph and best ways in
                qs = parse_qs(urlsplit(self.path).query)
                one = company_detail(cid=(qs.get("id") or [None])[0], name=(qs.get("company") or [None])[0],
                                     field=(qs.get("field") or [None])[0])
                if not one:
                    return self.send(404, json.dumps({"error": "Company not found in the directory."}), "application/json")
                return self.send(200, json.dumps(one, ensure_ascii=False), "application/json")
            if path in ("/companies", "/index.html"):            # Cohort views: Ryan's page plus the cohort layer
                return self.send(200, build_page(), "text/html; charset=utf-8")
            if path == "/api/description":                       # full job text, read from data/descriptions.db
                url = parse_qs(urlsplit(self.path).query).get("url", [""])[0]
                found = job_description(url)
                if not found:
                    return self.send(404, json.dumps({"error": "No description saved for this posting."}), "application/json")
                return self.send(200, json.dumps(found, ensure_ascii=False), "application/json")
            if path == "/api/find/meta":
                data, _, source = all_jobs()
                return self.send(200, json.dumps({
                    "ready": bool(data), "source": source, "generated": (data or {}).get("generated"),
                    "total": len((data or {}).get("jobs", [])), "categories": find.cats.CATEGORIES, "levels": find.cats.LEVELS,
                    "skills": (data or {}).get("vocab", {}).get("skills", []), "verticals": list(directory_verticals()),
                    "me": settings().get("me")}), "application/json")
            if path == "/data.js":                               # the roles: from the cohort database, else site/data.js
                return self.send(200, board_data()[1], "application/javascript; charset=utf-8")
            if path == "/cohort-data.js":
                try:
                    js = "window.COHORT_DATA = " + json.dumps(cohort_payload(), ensure_ascii=False) + ";"
                except (RuntimeError, OSError) as e:          # API down: the board still loads, with a warning
                    js = "window.COHORT_ERROR = " + json.dumps(f"Cohort connections unavailable ({e}).") + ";"
                return self.send(200, js, "application/javascript; charset=utf-8")
            if path in STATIC_FILES:
                f, ctype = STATIC_FILES[path]
                return self.send(200, f.read_bytes(), ctype + "; charset=utf-8")
        except RuntimeError as e:
            return self.send(500, str(e))
        self.send(404, "Not found")

    def do_POST(self):
        path = self.path.split("?")[0]
        if path == "/login":
            pw = parse_qs(self.body().decode("utf-8", "replace")).get("password", [""])[0]
            if hmac.compare_digest(pw.encode(), PASSWORD.encode()):
                return self.send(303, headers={"Location": "/", "Set-Cookie":
                                 f"cb_session={new_session()}; HttpOnly; SameSite=Strict; Path=/; {'Secure; ' if HOSTED else ''}"
                                 f"Max-Age={SESSION_DAYS * 86400}"})
            time.sleep(1)
            page = LOGIN_PAGE.replace("%ERR%", '<p class="err">Wrong password.</p>')
            return self.send(401, page, "text/html; charset=utf-8")
        if not (self.authed() and self.same_origin()):
            return self.send(403, "Forbidden")
        if path == "/logout":
            end_session(self.token())
            return self.send(204, headers={"Set-Cookie": "cb_session=; Max-Age=0; Path=/"})
        if path == "/api/upload":
            return self.upload()
        if path == "/api/resume":                     # resume text -> profile; the text is not kept
            try:
                text = json.loads(self.body(2_000_000)).get("text") or ""
            except ValueError:
                return self.send(400, "Bad request")
            if len(text.strip()) < 40:
                return self.send(400, "Couldn't read much text from that file. Try a PDF or Word file with selectable text.")
            return self.send(200, json.dumps(find.resume_profile(text, my_history_titles())), "application/json")
        if path == "/api/find":
            try:
                d = json.loads(self.body(200_000))
            except ValueError:
                return self.send(400, "Bad request")
            data = all_jobs()[0]
            if not data:
                return self.send(503, "The full job list isn't built yet.")
            try:
                cohort = find_cohort_map()
            except (RuntimeError, OSError):
                cohort = {}
            limit = d.get("limit", 40)                 # 0: counts only (the map)
            res = find.search(data, d.get("profile") or {}, d.get("filters") or {}, cohort,
                              offset=max(0, int(d.get("offset") or 0)), limit=max(0, min(100, int(limit if limit is not None else 40))),
                              want=d.get("want") or {}, co_vertical=job_company_verticals(), with_path=bool(d.get("path")))
            return self.send(200, json.dumps(res, ensure_ascii=False), "application/json")
        if path == "/api/me":
            try:
                me = json.loads(self.body()).get("id") or None
            except ValueError:
                return self.send(400, "Bad JSON")
            if me is not None and not re.fullmatch(r"[a-z0-9-]{1,60}", str(me)):
                return self.send(400, "Bad id")
            save_settings({**settings(), "me": me})
            return self.send(204)
        m = re.fullmatch(r"/api/people/([a-z0-9-]{1,60})/link", path)
        if m:
            try:
                url = uploads.set_profile_link(m.group(1), json.loads(self.body()).get("profile_url"),
                                               push_remote=isinstance(STORE, RemoteStore))
            except (uploads.UploadError, ValueError) as e:
                return self.send(400, str(e))
            except SyncError as e:
                return self.send(502, f"Saved on this computer, but not in the cloud database: {e}")
            _snap["value"] = None
            state.push_later("cohort.db")
            return self.send(200, json.dumps({"profile_url": url}), "application/json")
        if path == "/api/connections":
            try:
                d = json.loads(self.body())
            except ValueError:
                return self.send(400, "Bad JSON")
            entry = {"id": uuid.uuid4().hex[:12], "company": clean(d.get("company"), 200),
                     "classmate": clean(d.get("classmate"), 80), "contact": clean(d.get("contact"), 80),
                     "title": clean(d.get("title"), 120), "note": clean(d.get("note"), 300),
                     "added_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
            if entry["company"] not in cohort_payload_names():
                return self.send(400, "Unknown company")
            if not entry["classmate"] or not (entry["contact"] or entry["title"]):
                return self.send(400, "Who knows them, plus a name or a role, are required")
            try:
                saved = STORE.add(entry)
            except (RuntimeError, OSError) as e:
                return self.send(502, f"Could not save: {e}")
            _snap["value"] = None
            return self.send(201, json.dumps(saved), "application/json")
        self.send(404, "Not found")

    def upload(self):
        """One export per request: a zip (application/zip), or the CSVs of an unzipped folder as JSON."""
        q = {k: v[0] for k, v in parse_qs(urlsplit(self.path).query).items()}
        try:
            raw = self.body(uploads.MAX_BYTES)
        except ValueError:
            return self.send(413, "File too large.")
        try:
            if (self.headers.get("Content-Type") or "").startswith("application/json"):
                data = uploads.zip_from_csvs(json.loads(raw).get("files"))
            else:
                data = raw
            result = uploads.ingest_upload(data, q.get("filename"), q.get("name"), q.get("profile_url"),
                                           use_ai=q.get("ai") == "1" and ai_available(),
                                           push_remote=isinstance(STORE, RemoteStore))
        except (uploads.UploadError, ValueError) as e:
            return self.send(400, str(e))
        except SyncError as e:
            return self.send(502, f"Loaded on this computer, but the upload to the cloud database failed: {e}")
        _snap["value"] = None
        state.push_later("cohort.db")
        return self.send(200, json.dumps(result), "application/json")

    def do_DELETE(self):
        if not (self.authed() and self.same_origin()):
            return self.send(403, "Forbidden")
        m = re.fullmatch(r"/api/people/([a-z0-9-]{1,60})", self.path)
        if m:
            try:
                uploads.remove_person(m.group(1), push_remote=isinstance(STORE, RemoteStore))
            except SyncError as e:
                return self.send(502, f"Removed on this computer, but not from the cloud database: {e}")
            _snap["value"] = None
            state.push_later("cohort.db")
            return self.send(204)
        m = re.fullmatch(r"/api/connections/([0-9a-f]{12})", self.path)
        if not m:
            return self.send(404, "Not found")
        try:
            found = STORE.delete(m.group(1))
        except (RuntimeError, OSError) as e:
            return self.send(502, f"Could not remove: {e}")
        _snap["value"] = None
        self.send(204 if found else 404)


def cohort_payload_names():
    if _cache["value"] is None:
        _cache.update(key=None, value={"names": board_companies()})
    return _cache["value"]["names"]


def main():
    build_page()                       # fail fast if Ryan's page no longer fits the hooks
    p = cohort_payload(fresh=True)
    print(f"Connections from {p['source']}: {len(p['companies'])} board companies matched; "
          f"{len(p['bridges'])} shared contacts; "
          f"{sum(len(v) for v in p['manual'].values())} added by hand.", flush=True)
    print(f"Jobs from {board_data()[3]}.", flush=True)
    print(f"Find a job uses {all_jobs()[2]}.", flush=True)
    if all_jobs()[0]:
        find.job_regions(all_jobs()[0])          # work out every job's map regions now, not on the first search
    state.start_refresher()
    print(f"Private board: http://{HOST}:{PORT}" + ("  (hosted)" if HOSTED else "  (this computer only; Ctrl+C to stop)"), flush=True)
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
