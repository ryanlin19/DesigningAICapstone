"""Cloud persistence for the board's files, for the hosted version (deploy/): the files the board keeps on disk
are stored in a Cloudflare R2 bucket through the deploy Worker, pulled when the server starts and pushed back
after every change. Off (a no-op) unless COHORT_STATE_URL and COHORT_STATE_TOKEN are set, so running locally is
unchanged.

Classmates, contacts and hand-added connections are not files: they live in the cloud database (cohort-api + D1), which
the hosted board reaches with COHORT_API_URL and COHORT_API_TOKEN like the local one.

    pull_all()        at startup: download every stored file that exists
    push(name)        after a change: upload one file (big files go up in parts)
    refresh()         every few minutes: re-download files someone pushed from elsewhere (new job lists)

Files (name -> local path) are listed in FILES. The Worker side is deploy/src/index.js (/__state/<name>).
"""
import json
import os
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
URL = (os.environ.get("COHORT_STATE_URL") or "").rstrip("/")
TOKEN = os.environ.get("COHORT_STATE_TOKEN") or ""
PART = 64 * 1024 * 1024                  # under the Worker's 100 MB request limit
DATA = Path(os.environ.get("COHORT_BOARD_DATA") or HERE / "data")


def files():
    """Every file the hosted board keeps: name in the bucket -> path on disk."""
    return {
        "companies.db": Path(os.environ.get("COHORT_COMPANIES_DB") or REPO / "data" / "companies.db"),
        "all_jobs.json": REPO / "data" / "all_jobs.json",
        "descriptions.db": REPO / "data" / "descriptions.db",
        "data.js": REPO / "site" / "data.js",
        "sessions.json": DATA / "sessions.json",
        "settings.json": DATA / "settings.json",
        # the daily job refresh's own memory (what's new since yesterday, feeds already found)
        "history.json": REPO / "data" / "history.json",
        "boards.json": REPO / "data" / "boards.json",
        # the company directory's build files (Wikidata/Wikipedia caches, research results), one archive of data/company-db
        "company-db.tar.gz": DATA / "company-db.tar.gz",
    }


FOLDERS = {"company-db.tar.gz": REPO / "data" / "company-db"}       # archive name -> the folder it holds


def _pack(name):
    import tarfile
    folder = FOLDERS[name]
    if not folder.exists():
        return
    path = files()[name]
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tarfile.open(tmp, "w:gz") as t:
        for f in sorted(folder.rglob("*")):
            if f.is_file() and "batches" not in f.relative_to(folder).parts:
                t.add(f, arcname=str(f.relative_to(folder)))
    tmp.replace(path)


def _unpack(name):
    import tarfile
    folder = FOLDERS[name]
    folder.mkdir(parents=True, exist_ok=True)
    with tarfile.open(files()[name], "r:gz") as t:
        t.extractall(folder, filter="data")


ETAGS = DATA / ".state-etags.json"      # which stored version each local file is, so a code reload re-downloads nothing
try:
    _etags = json.loads(ETAGS.read_text(encoding="utf-8"))
except (OSError, ValueError):
    _etags = {}
_lock = threading.Lock()
_pending = [0]                           # uploads still running (a code reload waits for them)
_pending_lock = threading.Lock()


def _save_etags():
    try:
        DATA.mkdir(parents=True, exist_ok=True)
        ETAGS.write_text(json.dumps(_etags), encoding="utf-8")
    except OSError:
        pass


def uploads_pending():
    return _pending[0]


def enabled():
    return bool(URL and TOKEN)


def _req(method, name, data=None, headers=None):
    req = urllib.request.Request(f"{URL}/__state/{name}", data=data, method=method,
                                 headers={"Authorization": f"Bearer {TOKEN}", "User-Agent": "cohort-board", **(headers or {})})
    return urllib.request.urlopen(req, timeout=300)


def _remote(name):
    """(etag, parts) of the stored file, or None when it isn't stored."""
    try:
        with _req("GET", name + ".manifest") as r:
            m = json.loads(r.read())
            return m["etag"], m["parts"]
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def pull(name, force=False):
    """Download one file if it changed since the last pull. Returns True when the local copy was replaced."""
    path = files()[name]
    meta = _remote(name)
    if not meta or (not force and _etags.get(name) == meta[0]):
        return False
    tmp = path.with_name(path.name + ".download")
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(tmp, "wb") as out:
        for i in range(meta[1]):
            with _req("GET", f"{name}.{i:03d}") as r:
                while True:
                    chunk = r.read(1 << 20)
                    if not chunk:
                        break
                    out.write(chunk)
    tmp.replace(path)
    _etags[name] = meta[0]
    _save_etags()
    if name in FOLDERS:
        _unpack(name)
    return True


def push(name):
    """Upload one file (in parts when big), then its manifest. Quietly skipped when the file doesn't exist."""
    if not enabled():
        return
    if name in FOLDERS:
        _pack(name)
    path = files()[name]
    if not path.exists():
        return
    with _lock:
        etag = f"{path.stat().st_size}-{time.time_ns()}"
        parts = 0
        with open(path, "rb") as f:
            while True:
                chunk = f.read(PART)
                if not chunk and parts:
                    break
                with _req("PUT", f"{name}.{parts:03d}", chunk, {"Content-Type": "application/octet-stream"}):
                    pass
                parts += 1
                if len(chunk) < PART:
                    break
        with _req("PUT", name + ".manifest", json.dumps({"etag": etag, "parts": parts}).encode(),
                  {"Content-Type": "application/json"}):
            pass
        _etags[name] = etag
        _save_etags()


def push_later(*names):
    """push() in the background, so a request isn't held up by the upload."""
    if enabled():
        def run():
            try:
                for n in names:
                    push(n)
            finally:
                with _pending_lock:
                    _pending[0] -= 1
        with _pending_lock:
            _pending[0] += 1
        threading.Thread(target=run, daemon=True).start()


def pull_all():
    if not enabled():
        return []
    got = []
    for name in files():
        try:
            if pull(name, force=not files()[name].exists()):     # on disk already (a code reload): only if it changed
                got.append(name)
        except (urllib.error.URLError, OSError, ValueError) as e:
            print(f"state: couldn't pull {name}: {e}", flush=True)
    return got


def refresh():
    """Files someone pushed from another computer (new job lists, a new company directory). Returns their names."""
    got = []
    for name in ("all_jobs.json", "data.js", "companies.db", "descriptions.db"):
        try:
            if pull(name):
                got.append(name)
        except (urllib.error.URLError, OSError, ValueError) as e:
            print(f"state: couldn't refresh {name}: {e}", flush=True)
    return got


def start_refresher(every=600):
    if not enabled():
        return
    def loop():
        while True:
            time.sleep(every)
            changed = refresh()
            if changed:
                print("state: refreshed " + ", ".join(changed), flush=True)
    threading.Thread(target=loop, daemon=True).start()
