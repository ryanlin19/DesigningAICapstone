"""Muse's findings into the cohort data, and the activity log behind the Log tab.

Muse (Meta's browser agent) checks classmates' LinkedIn connections and reports what's new by adding rows to the
cloud's `manual_connections` table with a note starting "Muse". check():

  1. reads those rows (and any `activity_log` rows Muse wrote) from the cloud database,
  2. merges each new connection as a real contact of that classmate in the local ingest database, matched to the same
     person other classmates already know (same fingerprint and LinkedIn link), else keyed by name and company,
  3. pushes that classmate's data back to the cloud so local and cloud stay identical (cohort-api/sync.py),
  4. records what happened in `activity_log` (local and cloud), and clears the merged rows from `manual_connections`.

record() adds one log entry (used for uploads and removals too). Every function is safe to call repeatedly.
"""
import json
import re
import sqlite3
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "linkedin-ingest"))
sys.path.insert(0, str(HERE.parent / "cohort-api"))
from ingest import contact_keys, db as ingest_db, rules  # noqa: E402
import sync  # noqa: E402

_lock = threading.Lock()
last_check = {"at": None, "result": None, "error": None}


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _entry(source, action, summary, person=None, details=None, at=None):
    return {"id": uuid.uuid4().hex[:16], "at": at or _now(), "source": source, "action": action, "person": person,
            "summary": summary, "details": json.dumps(details, ensure_ascii=False) if details else None}


def _save_local(con, rows):
    for r in rows:
        con.execute("INSERT OR IGNORE INTO activity_log (id, at, source, action, person, summary, details) VALUES (?,?,?,?,?,?,?)",
                    tuple(r.get(c) for c in sync.LOG_COLS))


def record(db_path, source, action, summary, person=None, details=None, remote=False):
    """Add one entry to the activity log (local, and the cloud when remote)."""
    row = _entry(source, action, summary, person, details)
    with _lock:
        con = ingest_db.connect(str(db_path))
        try:
            _save_local(con, [row])
            con.commit()
        finally:
            con.close()
    if remote:
        try:
            sync.push_log([row])
        except sync.SyncError as e:
            print(f"log: couldn't save to the cloud: {e}", flush=True)
    return row


def entries(db_path, limit=300):
    if not Path(db_path).exists():
        return []
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        if not con.execute("SELECT 1 FROM sqlite_master WHERE name = 'activity_log'").fetchone():
            return []
        return [dict(r) for r in con.execute("SELECT * FROM activity_log ORDER BY at DESC, id LIMIT ?", (limit,))]
    finally:
        con.close()


def _company_norm(con, name):
    n = rules.normalize_company(name or "")
    if not n:
        return None
    hit = con.execute("SELECT company_norm FROM aliases WHERE alias IN (?, ?)", (n, rules.compress(n))).fetchone()
    return hit[0] if hit else n


def _connected_year(note, added_at):
    m = re.search(r"connected\D{0,12}((?:19|20)\d\d)", note or "", re.I)
    if m:
        return int(m.group(1))
    return int((added_at or _now())[:4])


def check(db_path, target="--remote"):
    """Pull Muse's findings from the cloud and merge them. Returns a short summary dict. Raises sync.SyncError."""
    with _lock:
        found = sync.query("SELECT * FROM manual_connections WHERE note LIKE 'Muse%' ORDER BY added_at, id", target)
        cloud_log = sync.query("SELECT * FROM activity_log ORDER BY at", target)
        try:                                                    # Muse's structured deliveries (migration 0012)
            inbox_rows = sync.query("SELECT * FROM muse_inbox ORDER BY found_at, id", target)
        except sync.SyncError as e:
            if "no such table" not in str(e):
                raise
            inbox_rows = []
        con = ingest_db.connect(str(db_path))
        try:
            have = {r[0] for r in con.execute("SELECT id FROM activity_log")}
            _save_local(con, [r for r in cloud_log if r["id"] not in have])        # Muse's own entries come down
            people = {r[1].strip().lower(): r[0] for r in con.execute(
                "SELECT person_id, TRIM(COALESCE(first_name,'') || ' ' || COALESCE(last_name,'')) FROM people")}
            secret = contact_keys.load_secret()
            new_log, touched, merged_ids, skipped = [], set(), [], []
            # one "Muse ran" entry per run (rows added at the same time), unless Muse logged the run itself
            runs = {}
            for r in found:
                runs.setdefault(r["added_at"], []).append(r)
            logged_runs = {r["at"] for r in cloud_log if r["source"] == "muse" and r["action"] == "run"}
            for at, rows in runs.items():
                if at not in logged_runs and not con.execute(
                        "SELECT 1 FROM activity_log WHERE source='muse' AND action='run' AND at=?", (at,)).fetchone():
                    who = sorted({r["classmate"] for r in rows})
                    new_log.append(_entry("muse", "run", f"Muse ran and found {len(rows)} new connection{'s' if len(rows) != 1 else ''} "
                                          f"for {', '.join(who)}", details={"rows": [r["id"] for r in rows]}, at=at))
            for r in found:
                pid = people.get((r["classmate"] or "").strip().lower())
                if not pid:
                    skipped.append(r)
                    new_log.append(_entry("board", "skip", f"Couldn't merge {r['contact']}: no classmate named {r['classmate']} has uploaded",
                                          details={"manual_id": r["id"]}))
                    merged_ids.append(r["id"])
                    continue
                norm = _company_norm(con, r["company"])
                # the same person other classmates already know: by name, preferring the same company
                cands = con.execute("SELECT contact_key, company_norm, title_bucket, profile_url, position FROM contacts "
                                    "WHERE LOWER(full_name) = LOWER(?)", (r["contact"],)).fetchall()
                best = next((c for c in cands if c[1] == norm), cands[0] if cands else None)
                if best:
                    key, norm, bucket, url = best[0], best[1], best[2], best[3]
                else:
                    parts = (r["contact"] or "").split()
                    key = contact_keys.contact_key(secret, None, parts[0] if parts else "", " ".join(parts[1:]), norm) if secret else None
                    bucket, url = rules.title_bucket(r["title"]), None
                if not key or not norm:
                    skipped.append(r)
                    continue
                cur = con.execute(
                    "INSERT OR IGNORE INTO contacts (contact_key, connector_id, company_norm, title_bucket, connected_year, snapshot_date, "
                    "full_name, position, profile_url) VALUES (?,?,?,?,?,?,?,?,?)",
                    (key, pid, norm, bucket, _connected_year(r["note"], r["added_at"]), (r["added_at"] or _now())[:10],
                     r["contact"], r["title"], url))
                company = r["company"] or norm
                if cur.rowcount:
                    touched.add(pid)
                    new_log.append(_entry("board", "merge", f"Added {r['contact']} ({r['title'] or 'role not given'}, {company}) to "
                                          f"{r['classmate']}'s contacts, from Muse", person=pid,
                                          details={"manual_id": r["id"], "matched_existing": bool(best), "note": r["note"]}))
                else:
                    new_log.append(_entry("board", "merge", f"{r['contact']} was already one of {r['classmate']}'s contacts", person=pid,
                                          details={"manual_id": r["id"]}))
                merged_ids.append(r["id"])
            done_inbox = _apply_inbox(con, inbox_rows, people, secret, new_log, touched, cloud_log)
            _save_local(con, new_log)
            con.commit()
        finally:
            con.close()
        # the cloud: the merged classmates' data (so both copies stay identical), the log, then clear Muse's rows
        if touched:
            sync.push(sorted(touched), Path(db_path), target)
        if new_log:
            sync.push_log(new_log, target)
        if merged_ids:
            sync.execute([f"DELETE FROM manual_connections WHERE id IN ({','.join(sync.q(i) for i in merged_ids)});"],
                         "clear merged Muse rows", target)
        if done_inbox:
            sync.execute([f"DELETE FROM muse_inbox WHERE id IN ({','.join(sync.q(i) for i in done_inbox)});"],
                         "clear processed Muse inbox", target)
        result = {"found": len(found) + len(inbox_rows),
                  "merged": len([e for e in new_log if e["source"] == "board" and e["action"] in ("merge", "job_change", "location", "removed")]),
                  "skipped": len(skipped), "classmates": sorted(touched), "log_entries": len(new_log)}
        last_check.update(at=_now(), result=result, error=None)
        return result


def _apply_inbox(con, rows, people, secret, new_log, touched, cloud_log):
    """Apply Muse's structured findings. Returns the ids handled (cleared from the cloud afterwards)."""
    ids = {r[0] for r in con.execute("SELECT person_id FROM people")}
    logged_runs = {r["id"] for r in cloud_log if r["source"] == "muse" and r["action"] == "run"}
    runs = {}
    for r in rows:
        runs.setdefault(r.get("run_id") or r["found_at"], []).append(r)
    for run, rs in runs.items():                       # a run entry when Muse didn't write one itself
        if run not in logged_runs and not con.execute("SELECT 1 FROM activity_log WHERE id=?", (str(run)[:64],)).fetchone():
            kinds = {}
            for r in rs:
                kinds[r["change"]] = kinds.get(r["change"], 0) + 1
            new_log.append({**_entry("muse", "run", "Muse ran and found " + ", ".join(f"{n} {k.replace('_', ' ')}{'s' if n != 1 else ''}"
                            for k, n in kinds.items()), at=min(r["found_at"] for r in rs)), "id": str(run)[:64]})
    handled = []
    display = {pid: n for n, pid in people.items()}
    for r in rows:
        who = (r["classmate"] or "").strip()
        pid = who if who in ids else people.get(who.lower())
        if pid:
            who = " ".join(w.capitalize() for w in display.get(pid, who).split())
        url = contact_keys.canonical_profile_url(r.get("profile_url"))
        key = contact_keys.contact_key(secret, url) if (url and secret) else None
        if not key and r.get("full_name"):              # no link: the person other classmates know by that name
            hit = con.execute("SELECT contact_key FROM contacts WHERE LOWER(full_name)=LOWER(?) LIMIT 1", (r["full_name"],)).fetchone()
            key = hit[0] if hit else None
        name = r.get("full_name") or "someone"
        change = r["change"]
        handled.append(r["id"])
        if not key:
            new_log.append(_entry("board", "skip", f"Couldn't match {name} from Muse ({change.replace('_', ' ')}): no profile link"))
            continue
        everyone = [x[0] for x in con.execute("SELECT DISTINCT connector_id FROM contacts WHERE contact_key=?", (key,))]
        if change == "new_connection":
            if not pid:
                new_log.append(_entry("board", "skip", f"Couldn't add {name}: no classmate {who} has uploaded"))
                continue
            known = con.execute("SELECT company_norm, title_bucket, full_name, position, profile_url, location FROM contacts "
                                "WHERE contact_key=? LIMIT 1", (key,)).fetchone()
            norm = _company_norm(con, r.get("company")) or (known[0] if known else None)
            if not norm:
                new_log.append(_entry("board", "skip", f"Couldn't add {name}: no company given"))
                continue
            cur = con.execute("INSERT OR IGNORE INTO contacts (contact_key, connector_id, company_norm, title_bucket, connected_year, "
                              "snapshot_date, full_name, position, profile_url, location) VALUES (?,?,?,?,?,?,?,?,?,?)",
                              (key, pid, norm, rules.title_bucket(r.get("title")) if r.get("title") else (known[1] if known else "other"),
                               _connected_year(r.get("connected_on"), r["found_at"]), r["found_at"][:10],
                               r.get("full_name") or (known[2] if known else None), r.get("title") or (known[3] if known else None),
                               url or (known[4] if known else None), r.get("location") or (known[5] if known else None)))
            if r.get("location"):                           # a city is about the person: every classmate's copy
                con.execute("UPDATE contacts SET location=? WHERE contact_key=?", (r["location"], key))
                touched.update(everyone)
            if cur.rowcount:
                touched.add(pid)
                new_log.append(_entry("board", "merge", f"Added {name} ({r.get('title') or 'role not given'}, {r.get('company') or norm}) "
                                      f"to {who}'s contacts, from Muse", person=pid, details={"inbox_id": r["id"]}))
        elif change == "job_change":
            norm = _company_norm(con, r.get("company"))
            if not norm or not everyone:
                new_log.append(_entry("board", "skip", f"Couldn't record {name}'s job change: " + ("no company given" if not norm else "not a cohort contact")))
                continue
            con.execute("UPDATE contacts SET company_norm=?, position=?, title_bucket=? WHERE contact_key=?",
                        (norm, r.get("title"), rules.title_bucket(r.get("title")), key))
            touched.update(everyone)
            was = " at ".join(x for x in (r.get("previous_title"), r.get("previous_company")) if x)
            new_log.append(_entry("board", "job_change", f"{name} moved{(' from ' + was) if was else ''} to {r.get('title') or 'a new role'} "
                                  f"at {r.get('company')}", details={"inbox_id": r["id"]}))
        elif change == "location":
            if not everyone or not r.get("location"):
                continue
            con.execute("UPDATE contacts SET location=? WHERE contact_key=?", (r["location"], key))
            touched.update(everyone)
            new_log.append(_entry("board", "location", f"{name} is now in {r['location']}", details={"inbox_id": r["id"]}))
        elif change == "removed_connection":
            if pid and con.execute("DELETE FROM contacts WHERE contact_key=? AND connector_id=?", (key, pid)).rowcount:
                touched.add(pid)
                new_log.append(_entry("board", "removed", f"{name} is no longer one of {who}'s connections", person=pid,
                                      details={"inbox_id": r["id"]}))
        else:
            new_log.append(_entry("board", "skip", f"Unknown Muse change '{change}' for {name}"))
    return handled


def start(db_path, every=900, on_change=None):
    """Check now (in the background) and every 15 minutes."""
    def loop():
        while True:
            try:
                res = check(db_path)
                if res["found"] and on_change:
                    on_change()
                if res["found"]:
                    print(f"inbox: merged {res['merged']} of {res['found']} Muse finding(s)", flush=True)
            except (sync.SyncError, OSError, sqlite3.Error) as e:
                last_check.update(at=_now(), error=str(e))
                print(f"inbox: couldn't check the cloud: {e}", flush=True)
            time.sleep(every)
    threading.Thread(target=loop, daemon=True).start()
