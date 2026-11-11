"""Where the board's cohort data lives: the cloud database (Cloudflare D1, through the cohort-api Worker).

    RemoteStore   the Worker (cohort-api/src/index.js). Used whenever cohort-board/.api (or COHORT_API_URL and
                  COHORT_API_TOKEN) is set: the normal case, here and on the hosted board.
    LocalStore    a SQLite file with the same tables, built from cohort-api/migrations. For offline tests only
                  (COHORT_LOCAL_DB, default cohort-board/data/local-cohort.db).

Both have the same methods. Reads are cached for 30 seconds and the cache is dropped after every write this board
makes, so pages don't reach the database on every request. Errors raise StoreError (a RuntimeError).
"""
import json
import os
import sqlite3
import threading
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
MIGRATIONS = HERE.parent / "cohort-api" / "migrations"
TTL = 30

PEOPLE_COLS = ["person_id", "display_name", "consent_scopes", "consent_at", "updated_at", "self_key", "profile_url",
               "first_name", "last_name", "headline", "industry", "geo_location", "export_date"]
CONTACT_COLS = ["contact_key", "connector_id", "company_norm", "title_bucket", "snapshot_date", "connected_year",
                "full_name", "position", "profile_url", "location"]
TABLE_COLS = {
    "contacts": CONTACT_COLS,
    "positions": ["person_id", "company_raw", "company_norm", "title", "title_bucket", "started_on", "finished_on", "is_current", "location"],
    "education": ["person_id", "school_raw", "school_norm", "degree", "start_date", "end_date"],
    "skills": ["person_id", "skill"],
    "company_counts": ["connector_id", "company_norm", "count", "top_title_bucket", "snapshot_date"],
}
OWNER = {"contacts": "connector_id", "positions": "person_id", "education": "person_id", "skills": "person_id",
         "company_counts": "connector_id"}
LOG_COLS = ["id", "at", "source", "action", "person", "summary", "details"]
WRITE_LOCK = threading.Lock()          # one upload or Muse merge at a time: both read, work out changes, then write


class StoreError(RuntimeError):
    pass


class NotFound(StoreError):
    pass


class _Cached:
    """The 30-second read cache both stores share."""

    def __init__(self):
        self._cache, self._lock = {}, threading.Lock()

    def _get(self, key, load, fresh=False):
        hit = self._cache.get(key)
        if not fresh and hit and time.time() - hit[0] < TTL:
            return hit[1]
        value = load()
        with self._lock:
            self._cache[key] = (time.time(), value)
        return value

    def invalidate(self):
        """Forget every cached read (after a write)."""
        with self._lock:
            self._cache.clear()

    # cached reads, the same for both stores
    def snapshot(self, fresh=False):
        return self._get("snapshot", self._snapshot, fresh)

    def people(self, fresh=False):
        return self._get("people", self._people, fresh)

    def positions(self, fresh=False):
        return self._get("positions", self._positions, fresh)

    def contacts(self, fresh=False):
        """Every contact row (every column)."""
        return self._get("contacts", self._contacts, fresh)

    def contacts_at(self, norms):
        """Contact rows at these companies (company_norm values)."""
        norms = sorted(set(n for n in norms if n))[:30]
        return self._get(("at",) + tuple(norms), lambda: self._contacts_at(norms)) if norms else []

    def registry(self, fresh=False):
        """{"companies": [{company_norm, display_name, parent_norm}], "aliases": [{alias, company_norm}]}."""
        return self._get("registry", self._registry, fresh)

    def log(self, limit=300, fresh=False):
        """Activity log entries, newest first."""
        return self._get(("log", limit), lambda: self._log(limit), fresh)

    # writes drop the cache
    def add_log(self, rows):
        if rows:
            self._add_log(rows)
            self.invalidate()

    def import_person(self, bundle):
        out = self._import(bundle)
        self.invalidate()
        return out

    def delete_person(self, pid):
        out = self._delete_person(pid)
        self.invalidate()
        return out

    def set_link(self, pid, profile_url, self_key):
        self._set_link(pid, profile_url, self_key)
        self.invalidate()

    def apply_inbox(self, upsert=(), delete=(), log=(), clear_inbox=(), clear_manual=()):
        out = self._apply_inbox(list(upsert), list(delete), list(log), list(clear_inbox), list(clear_manual))
        self.invalidate()
        return out

    def research_done(self):
        """Company research Muse finished and nobody merged yet, uncached: [{id, name, result}]."""
        return self._research_done()

    def research_mark(self, merged, needs_fix, log=()):
        """merged: ids now in the directory; needs_fix: [{id, error}] sent back to Muse; log: activity_log rows."""
        out = self._research_mark(list(merged), list(needs_fix), list(log))
        self.invalidate()
        return out

    def add(self, entry):
        out = self._add_manual(entry)
        self.invalidate()
        return out

    def delete(self, entry_id):
        out = self._delete_manual(entry_id)
        self.invalidate()
        return out


class RemoteStore(_Cached):
    """The cohort API on Cloudflare (cohort-api/). The token stays on this computer (or the hosted board's server),
    never in a browser."""

    def __init__(self, url, token):
        super().__init__()
        self.url, self.token = url.rstrip("/"), token
        self.label = self.url

    def call(self, method, path, body=None, timeout=30):
        """(status, parsed JSON or None). Network failures raise OSError."""
        req = urllib.request.Request(self.url + path, method=method,
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json",
                                              "User-Agent": "cohort-board"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
                return r.status, json.loads(raw) if raw else None
        except urllib.error.HTTPError as e:
            try:
                return e.code, json.loads(e.read() or b"null")
            except ValueError:
                return e.code, None

    def _ok(self, method, path, body=None, want=(200,), timeout=30):
        try:
            status, data = self.call(method, path, body, timeout)
        except OSError as e:
            raise StoreError(f"cohort API unreachable ({e})") from e
        if status == 404 and 404 not in want:
            raise NotFound((data or {}).get("error") or "not found")
        if status not in want:
            raise StoreError(f"cohort API returned {status}" + (f": {data['error']}" if isinstance(data, dict) and data.get("error") else ""))
        return data

    def _snapshot(self):
        return self._ok("GET", "/v1/snapshot")

    def _people(self):
        return self._ok("GET", "/v1/people")["people"]

    def _positions(self):
        return self._ok("GET", "/v1/positions")["positions"]

    def _contacts(self):
        rows, offset = [], 0
        while offset is not None:
            page = self._ok("GET", f"/v1/contacts/all?limit=5000&offset={offset}", timeout=60)
            rows += page["contacts"]
            offset = page["next"]
        return rows

    def _contacts_at(self, norms):
        from urllib.parse import urlencode
        return self._ok("GET", "/v1/contacts?" + urlencode([("company", n) for n in norms]))["contacts"]

    def _registry(self):
        return self._ok("GET", "/v1/companies", timeout=60)

    def _log(self, limit):
        return self._ok("GET", f"/v1/log?limit={int(limit)}")["entries"]

    def _add_log(self, rows):
        self._ok("POST", "/v1/log", {"rows": rows})

    def _import(self, bundle):
        return self._ok("POST", "/v1/import", bundle, timeout=120)

    def _delete_person(self, pid):
        return self._ok("DELETE", f"/v1/people/{pid}", want=(200, 404))

    def _set_link(self, pid, profile_url, self_key):
        self._ok("POST", f"/v1/people/{pid}/link", {"profile_url": profile_url, "self_key": self_key})

    def inbox(self):
        """Muse's deliveries, uncached: {"inbox": [...], "manual": [...]}."""
        return self._ok("GET", "/v1/inbox")

    def _apply_inbox(self, upsert, delete, log, clear_inbox, clear_manual):
        return self._ok("POST", "/v1/inbox/apply", {"upsert": upsert, "delete": delete, "log": log,
                                                    "clear_inbox": clear_inbox, "clear_manual": clear_manual}, timeout=120)

    def _research_done(self):
        return self._ok("GET", "/v1/research/done", timeout=60)["rows"]

    def _research_mark(self, merged, needs_fix, log):
        return self._ok("POST", "/v1/research/mark", {"merged": merged, "needs_fix": needs_fix, "log": log}, timeout=60)

    def _add_manual(self, entry):
        return self._ok("POST", "/v1/manual", {k: entry[k] for k in ("company", "classmate", "contact", "title", "note")}, want=(201,))

    def _delete_manual(self, entry_id):
        return self._ok("DELETE", f"/v1/manual/{entry_id}", want=(204, 404)) is None     # 404 carries an error body


class LocalStore(_Cached):
    """A SQLite file with the cloud database's tables (cohort-api/migrations), for testing the board offline.
    Same queries as the Worker."""

    def __init__(self, path):
        super().__init__()
        self.path = Path(path)
        self.label = f"local test database ({self.path.name})"
        self._wlock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        con = self._con()
        try:
            con.execute("CREATE TABLE IF NOT EXISTS _migrations (name TEXT PRIMARY KEY)")
            done = {r[0] for r in con.execute("SELECT name FROM _migrations")}
            for f in sorted(MIGRATIONS.glob("*.sql")):
                if f.name not in done:
                    con.executescript(f.read_text(encoding="utf-8"))
                    con.execute("INSERT INTO _migrations VALUES (?)", (f.name,))
            con.commit()
        finally:
            con.close()

    def _con(self):
        con = sqlite3.connect(self.path, timeout=30)
        con.row_factory = sqlite3.Row
        return con

    def _rows(self, sql, args=()):
        con = self._con()
        try:
            return [dict(r) for r in con.execute(sql, args)]
        finally:
            con.close()

    def _write(self, fn):
        with self._wlock:
            con = self._con()
            try:
                out = fn(con)
                con.commit()
                return out
            except Exception:
                con.rollback()
                raise
            finally:
                con.close()

    def _snapshot(self):
        q = self._rows
        return {
            "people": q("SELECT person_id, display_name, updated_at, profile_url, CASE WHEN self_key IS NULL THEN 0 ELSE 1 END AS has_self_key FROM people"),
            "parents": q("SELECT company_norm, parent_norm FROM companies WHERE parent_norm IS NOT NULL"),
            "aliases": q("SELECT alias, company_norm FROM aliases"),
            "counts": q("SELECT connector_id, company_norm, count, top_title_bucket FROM company_counts"),
            "contact_buckets": q("SELECT connector_id, company_norm, title_bucket, COUNT(*) AS n FROM contacts GROUP BY 1, 2, 3"),
            "unique_by_company": q("SELECT company_norm, COUNT(DISTINCT contact_key) AS n FROM contacts GROUP BY 1"),
            "unique_by_root": q("SELECT COALESCE(c.parent_norm, k.company_norm) AS company_norm, COUNT(DISTINCT k.contact_key) AS n "
                                "FROM contacts k LEFT JOIN companies c ON c.company_norm = k.company_norm GROUP BY 1"),
            "manual": q("SELECT id, company, classmate, contact, title, note, added_at FROM manual_connections ORDER BY added_at"),
            "shared": q("SELECT s.contact_key, s.company_norm, c.display_name, s.title_bucket, s.depth, s.first_connected_year "
                        "FROM shared_contacts s LEFT JOIN companies c ON c.company_norm = s.company_norm "
                        "ORDER BY s.depth DESC, s.first_connected_year"),
            "shared_links": q("SELECT k.contact_key, k.connector_id, k.connected_year FROM contacts k "
                              "JOIN shared_contacts s ON s.contact_key = k.contact_key"),
            "knows": q("SELECT p.person_id AS classmate, k.connector_id AS knower FROM people p "
                       "JOIN contacts k ON k.contact_key = p.self_key WHERE p.self_key IS NOT NULL"),
            "positions": q("SELECT person_id, company_norm, title, title_bucket, started_on, finished_on, is_current FROM positions"),
        }

    def _people(self):
        return self._rows("SELECT * FROM people ORDER BY person_id")

    def _positions(self):
        return self._rows("SELECT * FROM positions")

    def _contacts(self):
        return self._rows(f"SELECT {', '.join(CONTACT_COLS)} FROM contacts ORDER BY connector_id, contact_key")

    def _contacts_at(self, norms):
        return self._rows(f"SELECT {', '.join(CONTACT_COLS)} FROM contacts WHERE company_norm IN ({','.join('?' * len(norms))})", norms)

    def _registry(self):
        return {"companies": self._rows("SELECT company_norm, display_name, parent_norm FROM companies"),
                "aliases": self._rows("SELECT alias, company_norm FROM aliases")}

    def _log(self, limit):
        return self._rows("SELECT * FROM activity_log ORDER BY at DESC, id LIMIT ?", (int(limit),))

    @staticmethod
    def _insert(con, table, cols, rows, verb="INSERT"):
        con.executemany(f"{verb} INTO {table} ({', '.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                        [tuple(r.get(c) for c in cols) for r in rows])

    def _add_log(self, rows):
        self._write(lambda con: self._insert(con, "activity_log", LOG_COLS, rows, "INSERT OR IGNORE"))

    def _delete_rows(self, con, pid):
        out = {}
        for t, c in (("contacts", "connector_id"), ("company_counts", "connector_id"), ("positions", "person_id"),
                     ("education", "person_id"), ("skills", "person_id"), ("people", "person_id")):
            out[t] = con.execute(f"DELETE FROM {t} WHERE {c} = ?", (pid,)).rowcount
        return out

    def _import(self, b):
        pid = b["person_id"]
        for t, who in OWNER.items():
            if any(r.get(who) != pid for r in b.get(t) or []):
                raise StoreError(f"every {t} row must belong to {pid}")

        def run(con):
            self._delete_rows(con, pid)
            self._insert(con, "people", PEOPLE_COLS, b["people"])
            for t, cols in TABLE_COLS.items():
                self._insert(con, t, cols, b.get(t) or [], "INSERT OR IGNORE" if t in ("contacts", "company_counts") else "INSERT")
            con.executemany("INSERT INTO companies (company_norm, display_name, parent_norm) VALUES (?,?,?) ON CONFLICT (company_norm) "
                            "DO UPDATE SET display_name = COALESCE(excluded.display_name, companies.display_name), "
                            "parent_norm = COALESCE(excluded.parent_norm, companies.parent_norm)",
                            [(r["company_norm"], r.get("display_name"), r.get("parent_norm")) for r in b.get("companies") or []])
            self._insert(con, "aliases", ["alias", "company_norm"], b.get("aliases") or [], "INSERT OR IGNORE")
            return {"person_id": pid, "rows": {t: len(b.get(t) or []) for t in list(TABLE_COLS) + ["companies", "aliases"]}}
        return self._write(run)

    def _delete_person(self, pid):
        removed = self._write(lambda con: self._delete_rows(con, pid))
        return {"removed": removed}

    def _set_link(self, pid, profile_url, self_key):
        n = self._write(lambda con: con.execute("UPDATE people SET profile_url = ?, self_key = ? WHERE person_id = ?",
                                                (profile_url, self_key, pid)).rowcount)
        if not n:
            raise NotFound("not found")

    def inbox(self):
        return {"inbox": self._rows("SELECT * FROM muse_inbox ORDER BY found_at, id"),
                "manual": self._rows("SELECT * FROM manual_connections WHERE note LIKE 'Muse%' ORDER BY added_at, id")}

    def _apply_inbox(self, upsert, delete, log, clear_inbox, clear_manual):
        set_ = ", ".join(f"{c} = excluded.{c}" for c in CONTACT_COLS[2:])

        def run(con):
            con.executemany(f"INSERT INTO contacts ({', '.join(CONTACT_COLS)}) VALUES ({','.join('?' * len(CONTACT_COLS))}) "
                            f"ON CONFLICT (contact_key, connector_id) DO UPDATE SET {set_}",
                            [tuple(r.get(c) for c in CONTACT_COLS) for r in upsert])
            con.executemany("DELETE FROM contacts WHERE contact_key = ? AND connector_id = ?",
                            [(r["contact_key"], r["connector_id"]) for r in delete])
            self._insert(con, "activity_log", LOG_COLS, log, "INSERT OR IGNORE")
            con.executemany("DELETE FROM muse_inbox WHERE id = ?", [(i,) for i in clear_inbox])
            con.executemany("DELETE FROM manual_connections WHERE note LIKE 'Muse%' AND id = ?", [(i,) for i in clear_manual])
        self._write(run)
        return {"upserted": len(upsert), "deleted": len(delete), "logged": len(log), "cleared": len(clear_inbox) + len(clear_manual)}

    def _research_done(self):
        return self._rows("SELECT id, name, result FROM company_research WHERE status = 'done' ORDER BY researched_at, id LIMIT 2000")

    def _research_mark(self, merged, needs_fix, log):
        at = datetime.now(timezone.utc).isoformat(timespec="seconds")

        def run(con):
            con.executemany("UPDATE company_research SET status = 'merged', error = NULL WHERE status = 'done' AND id = ?", [(i,) for i in merged])
            con.executemany("UPDATE company_research SET status = 'needs_fix', error = ?, researched_at = COALESCE(researched_at, ?) WHERE id = ?",
                            [(r["error"][:500], at, r["id"]) for r in needs_fix])
            self._insert(con, "activity_log", LOG_COLS, log, "INSERT OR IGNORE")
        self._write(run)
        return {"merged": len(merged), "needs_fix": len(needs_fix)}

    def _add_manual(self, entry):
        e = {**entry, "id": entry.get("id") or uuid.uuid4().hex[:12],
             "added_at": entry.get("added_at") or datetime.now(timezone.utc).isoformat(timespec="seconds")}
        self._write(lambda con: self._insert(con, "manual_connections", ["id", "company", "classmate", "contact", "title", "note", "added_at"], [e]))
        return e

    def _delete_manual(self, entry_id):
        return bool(self._write(lambda con: con.execute("DELETE FROM manual_connections WHERE id = ?", (entry_id,)).rowcount))


def make_store():
    """RemoteStore when an API address and token are set (cohort-board/.api or the environment), else LocalStore."""
    cfg = dict(os.environ)
    api = HERE / ".api"
    if api.exists():
        for line in api.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                cfg.setdefault(k.strip(), v.strip())
    if cfg.get("COHORT_API_URL") and cfg.get("COHORT_API_TOKEN"):
        return RemoteStore(cfg["COHORT_API_URL"], cfg["COHORT_API_TOKEN"])
    data = Path(os.environ.get("COHORT_BOARD_DATA") or HERE / "data")
    return LocalStore(os.environ.get("COHORT_LOCAL_DB") or data / "local-cohort.db")
