"""Muse's findings into the cohort data, and the activity log behind the Log tab.

Muse (Meta's browser agent) checks classmates' LinkedIn connections and delivers what changed into the cloud database:
rows in `muse_inbox` (new_connection, job_change, location, removed_connection; muse/WEEKLY.md), or the older
way, rows in `manual_connections` with a note starting "Muse" (new connections only). check():

  1. reads those rows from the cloud (GET /v1/inbox); stops there when there are none,
  2. loads the cloud's classmates, contacts, company aliases and Muse's run entries into an in-memory SQLite copy and
     applies the rules below to it: a contact is matched by the fingerprint of their LinkedIn link (the cohort secret
     stays on this computer), else by name; a job change or a city updates every classmate's copy of that contact,
  3. sends the contact rows that changed, the rows removed, the log entries and the ids of the processed rows to the
     cloud in one transaction (POST /v1/inbox/apply), which also clears them from Muse's tables.

record() adds one log entry (used for uploads and removals too). Every function is safe to call repeatedly.
"""
import json
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "linkedin-ingest"))
sys.path.insert(0, str(HERE))
from ingest import contact_keys, db as ingest_db, rules  # noqa: E402
from store import CONTACT_COLS, LOG_COLS, WRITE_LOCK, StoreError  # noqa: E402

last_check = {"at": None, "result": None, "error": None}


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _entry(source, action, summary, person=None, details=None, at=None):
    return {"id": uuid.uuid4().hex[:16], "at": at or _now(), "source": source, "action": action, "person": person,
            "summary": summary, "details": json.dumps(details, ensure_ascii=False) if details else None}


def record(store, source, action, summary, person=None, details=None):
    """Add one entry to the activity log. A failure is printed, not raised: the action itself already happened."""
    row = _entry(source, action, summary, person, details)
    try:
        store.add_log([row])
    except (StoreError, OSError) as e:
        print(f"log: couldn't save: {e}", flush=True)
    return row


def entries(store, limit=300):
    return store.log(limit)


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


def _working_copy(people, contacts, reg, log):
    """The cloud's data in an in-memory SQLite database with the ingest's tables, so the rules run as plain SQL."""
    con = ingest_db.connect(":memory:")
    con.executemany("INSERT INTO people (person_id, first_name, last_name, consent_scopes, consent_at, updated_at, self_key, profile_url) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    [(p["person_id"], p.get("first_name") or (p.get("display_name") or "").partition(" ")[0],
                      p.get("last_name") if p.get("first_name") else (p.get("display_name") or "").partition(" ")[2],
                      p.get("consent_scopes") or "", p.get("consent_at") or "", p.get("updated_at") or "",
                      p.get("self_key"), p.get("profile_url")) for p in people])
    con.executemany(f"INSERT OR IGNORE INTO contacts ({', '.join(CONTACT_COLS)}) VALUES ({','.join('?' * len(CONTACT_COLS))})",
                    [[r.get(c) for c in CONTACT_COLS] for r in contacts])
    con.executemany("INSERT OR IGNORE INTO aliases (alias, company_norm, source) VALUES (?,?,'cloud')",
                    [(a["alias"], a["company_norm"]) for a in reg["aliases"]])
    con.executemany(f"INSERT OR IGNORE INTO activity_log ({', '.join(LOG_COLS)}) VALUES ({','.join('?' * len(LOG_COLS))})",
                    [[r.get(c) for c in LOG_COLS] for r in log])
    return con


def _contact_rows(con):
    return {(r["contact_key"], r["connector_id"]): dict(r)
            for r in con.execute(f"SELECT {', '.join(CONTACT_COLS)} FROM contacts")}


def check(store):
    """Merge Muse's findings from the cloud. Returns a short summary dict. Raises StoreError."""
    with WRITE_LOCK:
        delivered = store.inbox()
        found, inbox_rows = delivered["manual"], delivered["inbox"]
        if not found and not inbox_rows:
            result = {"found": 0, "merged": 0, "skipped": 0, "classmates": [], "log_entries": 0}
            last_check.update(at=_now(), result=result, error=None)
            return result
        cloud_log = [r for r in store.log(2000, fresh=True) if r["source"] == "muse"]
        con = _working_copy(store.people(fresh=True), store.contacts(fresh=True), store.registry(), cloud_log)
        try:
            before = _contact_rows(con)
            people = {}
            for pid, first, last in con.execute("SELECT person_id, first_name, last_name FROM people"):
                people[f"{first or ''} {last or ''}".strip().lower()] = pid
            secret = contact_keys.load_secret()
            new_log, touched, merged_ids, skipped = [], set(), [], []
            # one "Muse ran" entry per run (rows added at the same time), unless Muse logged the run itself
            runs = {}
            for r in found:
                runs.setdefault(r["added_at"], []).append(r)
            for at, rows in runs.items():
                if not con.execute("SELECT 1 FROM activity_log WHERE source='muse' AND action='run' AND at=?", (at,)).fetchone():
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
                # a classmate: their own fingerprint and link (these notes carry no link, so a name key wouldn't match them)
                mate = con.execute("SELECT self_key, profile_url FROM people WHERE self_key IS NOT NULL AND "
                                   "LOWER(TRIM(COALESCE(first_name,'') || ' ' || COALESCE(last_name,''))) = LOWER(TRIM(?))",
                                   (r["contact"] or "",)).fetchone()
                # the same person other classmates already know: by name, preferring the same company
                cands = con.execute("SELECT contact_key, company_norm, title_bucket, profile_url, position FROM contacts "
                                    "WHERE LOWER(full_name) = LOWER(?)", (r["contact"],)).fetchall()
                best = next((c for c in cands if c[1] == norm), cands[0] if cands else None)
                if mate:
                    key, url, bucket = mate[0], mate[1], rules.title_bucket(r["title"])
                    norm = norm or (best[1] if best else None)
                elif best:
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
            done_inbox = _apply_structured(con, inbox_rows, people, secret, new_log, touched)
            after = _contact_rows(con)
        finally:
            con.close()
        upsert = [row for k, row in after.items() if before.get(k) != row]
        delete = [{"contact_key": k[0], "connector_id": k[1]} for k in before if k not in after]
        store.apply_inbox(upsert, delete, new_log, done_inbox, merged_ids)
        result = {"found": len(found) + len(inbox_rows),
                  "merged": len([e for e in new_log if e["source"] == "board" and e["action"] in ("merge", "job_change", "location", "removed")]),
                  "skipped": len(skipped), "classmates": sorted(touched), "log_entries": len(new_log),
                  "rows_changed": len(upsert), "rows_removed": len(delete)}
        last_check.update(at=_now(), result=result, error=None)
        return result


def _apply_structured(con, rows, people, secret, new_log, touched):
    """Apply Muse's structured findings (muse_inbox) to the working copy. Returns the ids handled (cleared afterwards)."""
    ids = {r[0] for r in con.execute("SELECT person_id FROM people")}
    runs = {}
    for r in rows:
        runs.setdefault(r.get("run_id") or r["found_at"], []).append(r)
    for run, rs in runs.items():                       # a run entry when Muse didn't write one itself
        if not con.execute("SELECT 1 FROM activity_log WHERE id=?", (str(run)[:64],)).fetchone():
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
