"""Load LinkedIn exports dropped on the board into the cloud database.

Each export is written to a private temporary folder and run through the ingest (linkedin-ingest/) into a temporary
SQLite file seeded from the cloud: the company registry (so company names resolve the same way for every upload),
the classmate's current row (a profile link given earlier is kept) and contacts' known cities (kept across
re-uploads). That classmate's rows then go to the cloud in one request (POST /v1/import, replacing their previous
upload, plus any companies and aliases the cloud doesn't have yet), and the folder, export and temporary database are
deleted. The ingest opens only five files, plus one column of Invitations.csv for the classmate's own profile link
when none is typed in; the raw export is never kept.

Contact fingerprints use the cohort's secret on this computer (linkedin-ingest/.contact_key or COHORT_CONTACT_KEY);
it never goes to the cloud.
"""
import io
import re
import shutil
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO / "linkedin-ingest"))
sys.path.insert(0, str(HERE))
from ingest import contact_keys, registry  # noqa: E402
from ingest.db import connect  # noqa: E402
from ingest.pipeline import ALLOWED_FILES, Ingestor, parse_csv, read_export  # noqa: E402
from store import CONTACT_COLS, OWNER, PEOPLE_COLS, TABLE_COLS, WRITE_LOCK, NotFound  # noqa: E402

MAX_BYTES = 300 * 1024 * 1024          # LinkedIn's full archive can be large; only five small files are read


class UploadError(Exception):
    pass


def _clean(s, limit):
    return re.sub(r"\s+", " ", str(s or "")).strip()[:limit]


def zip_from_csvs(files):
    """{filename: text} from an unzipped export folder -> zip bytes with only the allowed files."""
    kept = {Path(n).name: t for n, t in (files or {}).items() if Path(n).name in ALLOWED_FILES and isinstance(t, str)}
    if not kept:
        raise UploadError("None of the five export files (Connections, Profile, Positions, Education, Skills) were found.")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, text in kept.items():
            z.writestr(name, text)
    return buf.getvalue()


def _existing_person(people, display):
    want = display.lower()
    for p in people:
        full = f'{p.get("first_name") or ""} {p.get("last_name") or ""}'.strip().lower()
        if full == want or (p.get("display_name") or "").strip().lower() == want:
            return p["person_id"]
    return None


def _seed(con, reg, person, located):
    """The temporary database starts as the cloud has things: registry, this classmate's row, known cities."""
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    con.executemany("INSERT OR IGNORE INTO companies (company_norm, display_name, parent_norm, source, created_at) VALUES (?,?,?,'cloud',?)",
                    [(c["company_norm"], c.get("display_name"), c.get("parent_norm"), now) for c in reg["companies"]])
    con.executemany("INSERT OR IGNORE INTO aliases (alias, company_norm, source) VALUES (?,?,'cloud')",
                    [(a["alias"], a["company_norm"]) for a in reg["aliases"]])
    if person:
        cols = [c for c in PEOPLE_COLS if c != "display_name"]
        con.execute(f"INSERT INTO people ({', '.join(cols)}) VALUES ({','.join('?' * len(cols))})", [person.get(c) for c in cols])
    con.executemany(f"INSERT OR IGNORE INTO contacts ({', '.join(CONTACT_COLS)}) VALUES ({','.join('?' * len(CONTACT_COLS))})",
                    [[r.get(c) for c in CONTACT_COLS] for r in located])
    con.commit()


def _bundle(con, pid, reg):
    """Everything from this classmate's upload, shaped for POST /v1/import."""
    p = dict(con.execute("SELECT * FROM people WHERE person_id = ?", (pid,)).fetchone())
    p["display_name"] = f'{p.get("first_name") or ""} {p.get("last_name") or ""}'.strip() or pid
    b = {"person_id": pid, "people": [{c: p.get(c) for c in PEOPLE_COLS}]}
    for t, cols in TABLE_COLS.items():
        if t != "company_counts":
            b[t] = [dict(r) for r in con.execute(f"SELECT {', '.join(cols)} FROM {t} WHERE {OWNER[t]} = ?", (pid,))]
    # per-company totals only for an export with no fingerprinted contacts (the board counts those itself)
    b["company_counts"] = [] if b["contacts"] else [dict(r) for r in con.execute(
        "SELECT connector_id, company_norm, count, top_title_bucket, snapshot_date FROM derived_connections WHERE connector_id = ?", (pid,))]
    cloud = {c["company_norm"]: c.get("parent_norm") for c in reg["companies"]}
    b["companies"] = [dict(r) for r in con.execute("SELECT company_norm, display_name, parent_norm FROM companies")
                      if r["company_norm"] not in cloud or (r["parent_norm"] and r["parent_norm"] != cloud[r["company_norm"]])]
    have = {a["alias"] for a in reg["aliases"]}
    b["aliases"] = [dict(r) for r in con.execute("SELECT alias, company_norm FROM aliases") if r["alias"] not in have]
    return b


def ingest_upload(store, data, filename, name=None, profile_url=None, use_ai=False):
    """Ingest one export (zip bytes) into the cloud database. Returns a short summary. Raises UploadError or StoreError."""
    secret = contact_keys.load_secret()
    if not secret:
        raise UploadError("No contact key is set up. Run `python -m ingest.contact_keys new` in linkedin-ingest first.")
    profile_url = _clean(profile_url, 300) or None
    if profile_url and not contact_keys.profile_handle(profile_url):
        raise UploadError("That doesn't look like a LinkedIn profile link (linkedin.com/in/...).")
    if len(data) > MAX_BYTES:
        raise UploadError("File too large.")

    tmpdir = tempfile.mkdtemp(prefix="cohort-upload-")           # readable by this user only
    try:
        base = re.sub(r"[^\w.-]", "_", Path(filename or "export.zip").name)[:100]
        path = Path(tmpdir) / (base if base.lower().endswith(".zip") else base + ".zip")
        path.write_bytes(data)
        if not zipfile.is_zipfile(path):
            raise UploadError("Not a zip file. Drop the .zip LinkedIn emailed, or the unzipped folder.")
        files, skipped = read_export(path)
        if "Connections.csv" not in files:
            raise UploadError("No Connections.csv in this export. The classmate needs to include Connections when exporting.")
        prof_rows = parse_csv(files["Profile.csv"]) if "Profile.csv" in files else []
        prof = prof_rows[0] if prof_rows else {}
        display = _clean(name, 80) or _clean(f'{prof.get("First Name") or ""} {prof.get("Last Name") or ""}', 80)
        if not display:
            raise UploadError("No Profile.csv in this export, so type the classmate's name.")

        with WRITE_LOCK:                                              # one upload or merge at a time
            people = store.people(fresh=True)
            pid = _existing_person(people, display) or re.sub(r"[^a-z0-9]+", "-", display.lower()).strip("-")[:60]
            current = next((p for p in people if p["person_id"] == pid), None)
            reg = store.registry(fresh=True)
            located = [r for r in store.contacts(fresh=True) if r.get("location")]
            con = connect(str(Path(tmpdir) / "ingest.db"))
            try:
                _seed(con, reg, current, located)
                registry.seed(con)
                summary = Ingestor(con, ai_model="haiku" if use_ai else None, contact_secret=secret).ingest(
                    path, pid, "profile,connections", profile_url=profile_url)
                if not prof or _clean(name, 80):
                    first, _, last = display.partition(" ")
                    con.execute("UPDATE people SET first_name=?, last_name=? WHERE person_id=?", (first, last, pid))
                    con.commit()
                bundle = _bundle(con, pid, reg)
            finally:
                con.close()
            store.import_person(bundle)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)                    # the export and the temporary database, either way
    return {"person_id": pid, "name": display, "replaced": current is not None, "connections": summary.get("connections"),
            "contacts_keyed": summary.get("contacts_keyed"), "companies": summary.get("companies"),
            "files_left_unopened": skipped, "profile_url": summary.get("profile_url"),
            "profile_url_source": summary.get("profile_url_source"),
            "new_companies": len(bundle["companies"]), "new_aliases": len(bundle["aliases"])}


def set_profile_link(store, pid, profile_url):
    """Add or change a loaded classmate's own LinkedIn link without re-uploading their export."""
    secret = contact_keys.load_secret()
    url = contact_keys.canonical_profile_url(profile_url)
    if not secret:
        raise UploadError("No contact key is set up.")
    if not url:
        raise UploadError("That doesn't look like a LinkedIn profile link (linkedin.com/in/...).")
    try:
        store.set_link(pid, url, contact_keys.contact_key(secret, url))
    except NotFound:
        raise UploadError("That classmate isn't loaded.")
    return url


def remove_person(store, pid):
    """Delete a classmate and every row from their upload. Returns rows removed per table."""
    with WRITE_LOCK:
        return (store.delete_person(pid) or {}).get("removed") or {}
