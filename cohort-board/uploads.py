"""Load LinkedIn exports dropped on the board.

Each export is written to a private temporary folder, run through the ingest (linkedin-ingest/) into
the local cohort.db, uploaded to the cloud database (cohort-api/sync.py) when the board uses it, and
then deleted. The ingest opens only five files, plus one column of Invitations.csv for the classmate's
own profile link when none is typed in; the raw export is never kept.
"""
import io
import os
import re
import shutil
import sys
import tempfile
import threading
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO / "linkedin-ingest"))
sys.path.insert(0, str(REPO / "cohort-api"))
from ingest import contact_keys, registry  # noqa: E402
from ingest.db import connect  # noqa: E402
from ingest.pipeline import ALLOWED_FILES, Ingestor, parse_csv, read_export  # noqa: E402
import sync  # noqa: E402

COHORT_DB = Path(os.environ.get("COHORT_INGEST_DB") or REPO / "linkedin-ingest" / "data" / "cohort.db")
D1_TARGET = "--local" if os.environ.get("COHORT_D1_LOCAL") else "--remote"   # --local: the `wrangler dev` copy, for tests
MAX_BYTES = 300 * 1024 * 1024          # LinkedIn's full archive can be large; only five small files are read
LOCK = threading.Lock()                 # one ingest at a time: they share the company registry


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


def _existing_person(con, display):
    row = con.execute("SELECT person_id FROM people WHERE lower(trim(coalesce(first_name,'') || ' ' || coalesce(last_name,''))) = ?",
                      (display.lower(),)).fetchone()
    return row["person_id"] if row else None


def ingest_upload(data, filename, name=None, profile_url=None, use_ai=False, push_remote=True):
    """Ingest one export (zip bytes). Returns a short summary. Raises UploadError or sync.SyncError."""
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

        with LOCK:
            con = connect(COHORT_DB)
            registry.seed(con)
            pid = _existing_person(con, display) or re.sub(r"[^a-z0-9]+", "-", display.lower()).strip("-")[:60]
            replaced = con.execute("SELECT 1 FROM people WHERE person_id=?", (pid,)).fetchone() is not None
            summary = Ingestor(con, ai_model="haiku" if use_ai else None, contact_secret=secret).ingest(
                path, pid, "profile,connections", profile_url=profile_url)
            if not prof or _clean(name, 80):
                first, _, last = display.partition(" ")
                con.execute("UPDATE people SET first_name=?, last_name=? WHERE person_id=?", (first, last, pid))
                con.commit()
            con.close()
            if push_remote:
                sync.push([pid], COHORT_DB, D1_TARGET)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)                    # the raw export is gone either way
    return {"person_id": pid, "name": display, "replaced": replaced, "connections": summary.get("connections"),
            "contacts_keyed": summary.get("contacts_keyed"), "companies": summary.get("companies"),
            "files_left_unopened": skipped, "profile_url": summary.get("profile_url"),
            "profile_url_source": summary.get("profile_url_source")}


def set_profile_link(pid, profile_url, push_remote=True):
    """Add or change a loaded classmate's own LinkedIn link without re-uploading their export."""
    secret = contact_keys.load_secret()
    url = contact_keys.canonical_profile_url(profile_url)
    if not secret:
        raise UploadError("No contact key is set up.")
    if not url:
        raise UploadError("That doesn't look like a LinkedIn profile link (linkedin.com/in/...).")
    with LOCK:
        con = connect(COHORT_DB)
        cur = con.execute("UPDATE people SET profile_url=?, self_key=? WHERE person_id=?",
                          (url, contact_keys.contact_key(secret, url), pid))
        con.commit()
        con.close()
        if not cur.rowcount:
            raise UploadError("That classmate isn't loaded on this computer.")
        if push_remote:
            sync.push([pid], COHORT_DB, D1_TARGET)
    return url


def remove_person(pid, push_remote=True):
    """Delete a classmate and everything loaded from their export, locally and in the cloud."""
    with LOCK:
        if COHORT_DB.exists():
            con = connect(COHORT_DB)
            for table, col in (("contacts", "connector_id"), ("derived_connections", "connector_id"), ("positions", "person_id"),
                               ("education", "person_id"), ("skills", "person_id"), ("people", "person_id")):
                con.execute(f"DELETE FROM {table} WHERE {col}=?", (pid,))
            con.commit()
            con.close()
        if push_remote:
            sync.remove(pid, D1_TARGET)
