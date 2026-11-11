"""Move cohort data between the local ingest database and the cloud database (Cloudflare D1).

    python cohort-api/sync.py push                 # upload everyone in linkedin-ingest/data/cohort.db
    python cohort-api/sync.py push connector-a     # upload one person (replaces their rows)
    python cohort-api/sync.py remove connector-a   # delete one person and all their rows ("remove me")
    python cohort-api/sync.py backup [file.sql]    # download the whole cloud database as plain SQL
    python cohort-api/sync.py verify               # check the cloud copy is identical to the local one

    --db PATH   read another ingest database (default linkedin-ingest/data/cohort.db)
    --local     write to the local development copy of D1 (`wrangler dev`) instead of the cloud

Bulk loads go through `wrangler d1 execute --file`, which writes SQL straight to the database.
The generated SQL is standard (INSERT ... ON CONFLICT), so the same files load into SQLite or Postgres.
The temporary SQL file holds classmates' data and is deleted after each run.
"""
import argparse
import json
import re
import os
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
LOCAL_DB = HERE.parent / "linkedin-ingest" / "data" / "cohort.db"
D1_NAME = "cohort"


def q(v):
    """SQL literal. Strings are single-quoted with quotes doubled; NUL bytes dropped."""
    if v is None:
        return "NULL"
    if isinstance(v, (int, float)):
        return str(v)
    return "'" + str(v).replace("\x00", "").replace("'", "''") + "'"


def inserts(table, cols, rows, conflict="", chunk=200):
    out = []
    for i in range(0, len(rows), chunk):
        values = ",\n".join("(" + ",".join(q(v) for v in r) + ")" for r in rows[i:i + chunk])
        out.append(f"INSERT INTO {table} ({','.join(cols)}) VALUES\n{values}\n{conflict};")
    return out


class SyncError(Exception):
    pass


def run_sql(statements, label, target="--remote"):
    fd, path = tempfile.mkstemp(suffix=".sql", prefix="cohort-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("\n".join(statements) + "\n")
        print(f"{label}: {len(statements)} statements -> D1 '{D1_NAME}' ({target.strip('-')})", flush=True)
        r = subprocess.run(["wrangler", "d1", "execute", D1_NAME, target, "--yes", "--file", path],
                           cwd=HERE, capture_output=True, text=True)
        if r.returncode:
            raise SyncError((r.stdout[-1500:] + r.stderr[-1500:]).strip() or "wrangler failed")
        print("done.", flush=True)
    finally:
        os.remove(path)


def delete_person(pid, full=True):
    tables = [("contacts", "connector_id"), ("company_counts", "connector_id"), ("positions", "person_id")]
    if full:                                            # tables the mirror adds (migration 0010)
        tables += [("education", "person_id"), ("skills", "person_id")]
    return [f"DELETE FROM {t} WHERE {c} = {q(pid)};" for t, c in tables + [("people", "person_id")]]


def remove(pid, target="--remote"):
    try:
        run_sql(delete_person(pid), f"remove {pid}", target)
    except SyncError as e:
        if "no such table" not in str(e):
            raise
        run_sql(delete_person(pid, full=False), f"remove {pid}", target)


MIRRORED = ("people", "contacts", "positions", "education", "skills")


def push(person_ids, db=LOCAL_DB, target="--remote", names=True):
    """Upload people from the local ingest database, replacing their rows in D1. Raises SyncError.

    The cloud copy mirrors the local one: every column of people, contacts (names, titles, links), positions (with
    locations), education and skills (migrations 0008-0010). If the cloud database doesn't have those columns yet,
    the push is retried with the older, smaller set, and the board keeps reading the rest from this computer."""
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    people = con.execute("SELECT * FROM people").fetchall()
    if person_ids:
        people = [p for p in people if p["person_id"] in person_ids]
        missing = set(person_ids) - {p["person_id"] for p in people}
        if missing:
            raise SyncError(f"Not in the local database: {', '.join(sorted(missing))}")
    if not people:
        raise SyncError("Nobody to upload.")
    ids = [p["person_id"] for p in people]
    marks = ",".join("?" * len(ids))
    cols_of = lambda t: [r[1] for r in con.execute(f"PRAGMA table_info({t})")]
    has = lambda t: bool(con.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (t,)).fetchone())
    display = lambda p: f'{p["first_name"] or ""} {p["last_name"] or ""}'.strip() or p["person_id"]

    cloud_cols = {}                                     # what the cloud database has, so nothing is dropped silently
    try:
        for r in query("SELECT m.name AS t, p.name AS c FROM sqlite_master m JOIN pragma_table_info(m.name) p "
                       "WHERE m.type = 'table' AND m.name IN ('people','contacts','positions','education','skills')", target):
            cloud_cols.setdefault(r["t"], set()).add(r["c"])
    except SyncError:
        cloud_cols = {}
    left_out = {}
    if cloud_cols:
        local_cols = cols_of

        def cols_of(t):                                   # noqa: F811  (local columns the cloud also has)
            mine = local_cols(t)
            keep = [c for c in mine if c in cloud_cols.get(t, set())]
            if len(keep) < len(mine):
                left_out[t] = [c for c in mine if c not in keep]
            return keep
        names = names and bool(cloud_cols.get("education"))
    sql = [s for pid in ids for s in delete_person(pid, full=names)]
    if names:                                           # the mirror: every local column, plus the board's display name
        pcols = cols_of("people")
        sql += inserts("people", pcols + ["display_name"], [tuple(p[c] for c in pcols) + (display(p),) for p in people])
    else:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        col = lambda p, c: p[c] if c in p.keys() else None
        sql += inserts("people", ["person_id", "display_name", "consent_scopes", "consent_at", "updated_at", "self_key", "profile_url"],
                       [(p["person_id"], display(p), p["consent_scopes"], p["consent_at"], now, col(p, "self_key"), col(p, "profile_url"))
                        for p in people])
    # The registry is shared by everyone, so it is merged rather than replaced.
    sql += inserts("companies", ["company_norm", "display_name", "parent_norm"],
                   [tuple(r) for r in con.execute("SELECT company_norm, display_name, parent_norm FROM companies")],
                   "ON CONFLICT (company_norm) DO UPDATE SET display_name = excluded.display_name, "
                   "parent_norm = COALESCE(excluded.parent_norm, companies.parent_norm)")
    sql += inserts("aliases", ["alias", "company_norm"],
                   [tuple(r) for r in con.execute("SELECT alias, company_norm FROM aliases")],
                   "ON CONFLICT (alias) DO NOTHING")
    old = {"contacts": ["contact_key", "connector_id", "company_norm", "title_bucket", "connected_year", "snapshot_date"],
           "positions": ["person_id", "company_norm", "title", "title_bucket", "started_on", "finished_on", "is_current"]}
    with_keys = set()
    for t, who in (("contacts", "connector_id"), ("positions", "person_id"), ("education", "person_id"), ("skills", "person_id")):
        if not has(t) or (not names and t not in old):
            continue
        cols = cols_of(t) if names else old[t]
        rows = con.execute(f"SELECT {', '.join(cols)} FROM {t} WHERE {who} IN ({marks})", ids).fetchall()
        if t == "contacts":
            with_keys = {r["connector_id"] for r in rows}
            sql += inserts(t, cols, [tuple(r) for r in rows], "ON CONFLICT (contact_key, connector_id) DO NOTHING")
        else:
            sql += inserts(t, cols, [tuple(r) for r in rows])
    # Older loads without contact keys keep their per-company counts.
    sql += inserts("company_counts", ["connector_id", "company_norm", "count", "top_title_bucket", "snapshot_date"],
                   [tuple(r) for r in con.execute(
                       f"SELECT connector_id, company_norm, count, top_title_bucket, snapshot_date FROM derived_connections "
                       f"WHERE connector_id IN ({marks})", ids) if r["connector_id"] not in with_keys])
    con.close()
    if left_out:
        print("The cloud database is missing columns " + "; ".join(f"{t}: {', '.join(c)}" for t, c in left_out.items()) +
              " (apply the latest cohort-api migrations); they'll be pushed once it has them.", flush=True)
    _pending(ids, add=bool(left_out))
    try:
        run_sql(sql, f"push {', '.join(ids)}", target)
    except SyncError as e:
        if names and re.search(r"no such table|has no column|no column named", str(e)):
            print("The cloud database lacks the mirror columns (apply migrations 0008-0010); pushing the older set.", flush=True)
            return push(person_ids, db, target, names=False)
        raise


def query(sql, target="--remote"):
    """Read from D1: a list of row dicts. Raises SyncError."""
    r = subprocess.run(["wrangler", "d1", "execute", D1_NAME, target, "--json", "--command", sql], cwd=HERE,
                       capture_output=True, text=True)
    out = r.stdout
    try:
        return json.loads(out[out.find("["):out.rfind("]") + 1])[0]["results"]
    except (ValueError, IndexError, KeyError):
        raise SyncError((r.stderr or out)[-800:].strip() or "wrangler failed")


def execute(statements, label, target="--remote"):
    """Write to D1 (a list of SQL statements). Raises SyncError."""
    if statements:
        run_sql(statements, label, target)


LOG_COLS = ["id", "at", "source", "action", "person", "summary", "details"]
PENDING = HERE.parent / "cohort-board" / "data" / "sync_pending.json"


def _pending(ids, add):
    """Remember classmates pushed without every column; push_pending() retries them once the cloud catches up."""
    try:
        cur = set(json.loads(PENDING.read_text()))
    except (FileNotFoundError, ValueError):
        cur = set()
    new = (cur | set(ids)) if add else (cur - set(ids))
    if new != cur:
        PENDING.parent.mkdir(parents=True, exist_ok=True)
        PENDING.write_text(json.dumps(sorted(new)))


def push_pending(db=LOCAL_DB, target="--remote"):
    """Push again anyone left incomplete earlier. Returns their ids (empty when nothing was pending)."""
    try:
        ids = json.loads(PENDING.read_text())
    except (FileNotFoundError, ValueError):
        return []
    if ids:
        push(ids, db, target)
    return ids


def push_log(rows, target="--remote"):
    """Add activity-log rows (dicts) to D1; rows already there are left alone."""
    execute(inserts("activity_log", LOG_COLS, [tuple(r.get(c) for c in LOG_COLS) for r in rows], "ON CONFLICT (id) DO NOTHING"),
            f"log {len(rows)} entr{'y' if len(rows) == 1 else 'ies'}", target)


def verify(db=LOCAL_DB, target="--remote"):
    """Compare the local ingest database with D1, table by table, on the exact SQL value of every column.
    Returns True when every mirrored table is identical; prints one line per table."""
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    ok = True
    for t in MIRRORED + ("activity_log",):
        cols = [r[1] for r in con.execute(f"PRAGMA table_info({t})")]
        if not cols:
            continue
        sel = ", ".join(f"quote({c}) AS {c}" for c in cols)
        local = sorted(json.dumps(list(r)) for r in con.execute(f"SELECT {sel} FROM {t}"))
        r = subprocess.run(["wrangler", "d1", "execute", D1_NAME, target, "--json", "--command", f"SELECT {sel} FROM {t}"],
                           cwd=HERE, capture_output=True, text=True)
        try:
            out = r.stdout
            cloud = sorted(json.dumps([row[c] for c in cols]) for row in json.loads(out[out.find("["):out.rfind("]") + 1])[0]["results"])
        except (ValueError, IndexError, KeyError):
            print(f"{t:10} couldn't read the cloud copy: {(r.stderr or r.stdout)[-300:]}")
            ok = False
            continue
        same = local == cloud
        ok &= same
        print(f"{t:10} local {len(local):6} rows | cloud {len(cloud):6} rows | {'identical' if same else 'DIFFERENT'}")
    con.close()
    print("Local and cloud are identical." if ok else "Local and cloud differ: run `python3 cohort-api/sync.py push` to bring the cloud up to date.")
    return ok


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, default=LOCAL_DB)
    ap.add_argument("--local", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("push"); p.add_argument("person_id", nargs="*")
    r = sub.add_parser("remove"); r.add_argument("person_id")
    b = sub.add_parser("backup"); b.add_argument("output", nargs="?")
    sub.add_parser("verify")
    a = ap.parse_args()
    target = "--local" if a.local else "--remote"
    try:
        if a.cmd == "push":
            push(a.person_id, a.db.resolve(), target)
        elif a.cmd == "remove":
            remove(a.person_id, target)
        elif a.cmd == "verify":
            sys.exit(0 if verify(a.db.resolve(), target) else 1)
    except SyncError as e:
        sys.exit(str(e))
    if a.cmd == "backup":
        out = a.output or f"cohort-backup-{datetime.now():%Y-%m-%d}.sql"
        subprocess.run(["wrangler", "d1", "export", D1_NAME, "--remote", "--output", str(Path(out).resolve())],
                       cwd=HERE, check=True)
        print(f"Backup written to {out}. It holds classmates' data: keep it out of git and shared folders.")


if __name__ == "__main__":
    main()
