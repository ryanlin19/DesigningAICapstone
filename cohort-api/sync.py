"""Move cohort data between the local ingest database and the cloud database (Cloudflare D1).

    python cohort-api/sync.py push                 # upload everyone in linkedin-ingest/data/cohort.db
    python cohort-api/sync.py push connector-a     # upload one person (replaces their rows)
    python cohort-api/sync.py remove connector-a   # delete one person and all their rows ("remove me")
    python cohort-api/sync.py backup [file.sql]    # download the whole cloud database as plain SQL

    --db PATH   read another ingest database (default linkedin-ingest/data/cohort.db)
    --local     write to the local development copy of D1 (`wrangler dev`) instead of the cloud

Bulk loads go through `wrangler d1 execute --file`, which writes SQL straight to the database.
The generated SQL is standard (INSERT ... ON CONFLICT), so the same files load into SQLite or Postgres.
The temporary SQL file holds classmates' data and is deleted after each run.
"""
import argparse
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


def delete_person(pid):
    return [f"DELETE FROM {t} WHERE {c} = {q(pid)};" for t, c in
            (("contacts", "connector_id"), ("company_counts", "connector_id"), ("positions", "person_id"),
             ("people", "person_id"))]


def remove(pid, target="--remote"):
    run_sql(delete_person(pid), f"remove {pid}", target)


def push(person_ids, db=LOCAL_DB, target="--remote"):
    """Upload people from the local ingest database, replacing their rows in D1. Raises SyncError."""
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
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    sql = [s for pid in ids for s in delete_person(pid)]
    col = lambda p, c: p[c] if c in p.keys() else None
    sql += inserts("people", ["person_id", "display_name", "consent_scopes", "consent_at", "updated_at", "self_key", "profile_url"],
                   [(p["person_id"], f'{p["first_name"] or ""} {p["last_name"] or ""}'.strip() or p["person_id"],
                     p["consent_scopes"], p["consent_at"], now, col(p, "self_key"), col(p, "profile_url"))
                    for p in people])
    # The registry is shared by everyone, so it is merged rather than replaced.
    sql += inserts("companies", ["company_norm", "display_name", "parent_norm"],
                   [tuple(r) for r in con.execute("SELECT company_norm, display_name, parent_norm FROM companies")],
                   "ON CONFLICT (company_norm) DO UPDATE SET display_name = excluded.display_name, "
                   "parent_norm = COALESCE(excluded.parent_norm, companies.parent_norm)")
    sql += inserts("aliases", ["alias", "company_norm"],
                   [tuple(r) for r in con.execute("SELECT alias, company_norm FROM aliases")],
                   "ON CONFLICT (alias) DO NOTHING")
    marks = ",".join("?" * len(ids))
    has_contacts = con.execute("SELECT 1 FROM sqlite_master WHERE name = 'contacts'").fetchone()
    contacts = con.execute(f"SELECT contact_key, connector_id, company_norm, title_bucket, connected_year, snapshot_date "
                           f"FROM contacts WHERE connector_id IN ({marks})", ids).fetchall() if has_contacts else []
    with_keys = {r["connector_id"] for r in contacts}
    sql += inserts("contacts", ["contact_key", "connector_id", "company_norm", "title_bucket", "connected_year", "snapshot_date"],
                   [tuple(r) for r in contacts], "ON CONFLICT (contact_key, connector_id) DO NOTHING")
    # Older loads without contact keys keep their per-company counts.
    sql += inserts("company_counts", ["connector_id", "company_norm", "count", "top_title_bucket", "snapshot_date"],
                   [tuple(r) for r in con.execute(
                       f"SELECT connector_id, company_norm, count, top_title_bucket, snapshot_date FROM derived_connections "
                       f"WHERE connector_id IN ({marks})", ids) if r["connector_id"] not in with_keys])
    # Classmates' own work history, for "Classmate worked here".
    sql += inserts("positions", ["person_id", "company_norm", "title", "title_bucket", "started_on", "finished_on", "is_current"],
                   [tuple(r) for r in con.execute(
                       f"SELECT person_id, company_norm, title, title_bucket, started_on, finished_on, is_current FROM positions "
                       f"WHERE person_id IN ({marks}) AND company_norm IS NOT NULL", ids)])
    con.close()
    run_sql(sql, f"push {', '.join(ids)}", target)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, default=LOCAL_DB)
    ap.add_argument("--local", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("push"); p.add_argument("person_id", nargs="*")
    r = sub.add_parser("remove"); r.add_argument("person_id")
    b = sub.add_parser("backup"); b.add_argument("output", nargs="?")
    a = ap.parse_args()
    target = "--local" if a.local else "--remote"
    try:
        if a.cmd == "push":
            push(a.person_id, a.db.resolve(), target)
        elif a.cmd == "remove":
            remove(a.person_id, target)
    except SyncError as e:
        sys.exit(str(e))
    if a.cmd == "backup":
        out = a.output or f"cohort-backup-{datetime.now():%Y-%m-%d}.sql"
        subprocess.run(["wrangler", "d1", "export", D1_NAME, "--remote", "--output", str(Path(out).resolve())],
                       cwd=HERE, check=True)
        print(f"Backup written to {out}. It holds classmates' data: keep it out of git and shared folders.")


if __name__ == "__main__":
    main()
