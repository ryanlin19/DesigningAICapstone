"""Put a new version of the board live while people are using it.

    deploy/ship.sh            the usual way: the board's code goes to R2 and the running board reloads it in about
                              a second (cohort-board/launch.py). Nobody is signed out; requests in that second wait.
    deploy/ship.sh --image    when deploy/Dockerfile, deploy/src/index.js or wrangler.jsonc changed: a new container
                              image and Worker (wrangler deploy), then the same code ship. Takes minutes, a short gap.

Shipped: cohort-board/, pipeline/, site/ (not its job data), linkedin-ingest/ingest/, the cohort-api and company-db
scripts the board runs. Not shipped: data/ (the pipeline's inputs live in the image; use --image if they changed).
Settings come from deploy/.deploy.env (PUBLIC_URL, STATE_TOKEN). Waits while the daily refresh or a merge runs.
"""
import io
import json
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.request
from pathlib import Path

DEPLOY = Path(__file__).resolve().parent
REPO = DEPLOY.parent
CODE = "code.tar.gz"
PART = 64 * 1024 * 1024
SHIP = ["cohort-board", "pipeline", "site", "linkedin-ingest/ingest", "linkedin-ingest/data/seed_companies.csv",
        "cohort-api/push_jobs.py", "cohort-api/sync.py", "company-db/companies.py", "company-db/overrides.json"]
SKIP = {"cohort-board/data", "cohort-board/.password", "cohort-board/.api", "site/data.js", "site/match_index.js"}


def env():
    out = {}
    for line in (DEPLOY / ".deploy.env").read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


CFG = env()
URL, TOKEN = CFG["PUBLIC_URL"].rstrip("/"), CFG["STATE_TOKEN"]


def call(method, path, data=None, headers=None, timeout=120):
    req = urllib.request.Request(URL + path, data=data, method=method,
                                 headers={"User-Agent": "cohort-board-ship", **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read()


def op(name):
    """POST an operator route (/__ship/<name>, /__restart) -> (status, parsed body)."""
    path = "/__restart" if name == "restart" else "/__ship/" + name
    try:
        status, body = call("POST", path, b"", {"X-Task-Token": TOKEN})
    except urllib.error.HTTPError as e:
        status, body = e.code, e.read()
    try:
        return status, json.loads(body)
    except ValueError:
        return status, body.decode("utf-8", "replace")


def label():
    head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO, capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "status", "--porcelain", "--", *SHIP], cwd=REPO, capture_output=True, text=True).stdout.strip()
    return head + ("+uncommitted" if dirty else "")


def skipped(rel):
    parts = rel.split("/")
    return ("__pycache__" in parts or rel.endswith((".pyc", ".DS_Store")) or
            any(rel == s or rel.startswith(s + "/") for s in SKIP))


def pack():
    buf = io.BytesIO()
    n = 0
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        for item in SHIP:
            path = REPO / item
            for f in ([path] if path.is_file() else sorted(path.rglob("*"))):
                rel = f.relative_to(REPO).as_posix()
                if f.is_file() and not skipped(rel):
                    t.add(f, arcname=rel)
                    n += 1
    return buf.getvalue(), n


def upload(data, version):
    parts = 0
    for i in range(0, max(len(data), 1), PART):
        call("PUT", f"/__state/{CODE}.{parts:03d}", data[i:i + PART],
             {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/octet-stream"}, timeout=300)
        parts += 1
    manifest = {"etag": f"{len(data)}-{time.time_ns()}", "parts": parts, **version}
    call("PUT", f"/__state/{CODE}.manifest", json.dumps(manifest).encode(),
         {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"})


def running():
    status, body = op("version")
    return body if status == 200 and isinstance(body, dict) else None


def wait_live(version, limit):
    end = time.time() + limit
    while time.time() < end:
        try:
            v = running()
        except (urllib.error.URLError, OSError):
            v = None
        if v and v.get("built") == version["built"]:
            return True
        time.sleep(1)
    return False


def main():
    image = "--image" in sys.argv[1:]
    version = {"label": label(), "built": time.time()}
    (REPO / "cohort-board" / "VERSION").write_text(json.dumps(version), encoding="utf-8")   # git-ignored
    data, n = pack()
    print(f"ship: {version['label']}, {n} files, {len(data) // 1024} KB")

    if image:
        print("ship: building and deploying the container image and Worker (a few minutes)…")
        subprocess.run(["npx", "wrangler", "deploy", "--containers-rollout", "immediate"], cwd=DEPLOY, check=True)

    upload(data, version)
    print("ship: code uploaded")
    start = time.time()
    while True:
        status, body = op("reload")
        if status == 200:
            break
        if status == 409 and isinstance(body, dict) and body.get("busy"):
            if time.time() - start > 1800:
                sys.exit("ship: the board has been busy for 30 minutes; the code is uploaded, run ship.sh again later.")
            print(f"ship: the board is running {body.get('task')}; waiting…")
            time.sleep(30)
            continue
        # an older board that can't reload in place (first run after --image): restart it onto the new image
        print(f"ship: this board can't reload in place ({status}); restarting it")
        if image or status in (403, 404, 409):
            print("ship: restart:", op("restart")[1])
            if wait_live(version, 1200):
                break
            sys.exit("ship: not live after 20 minutes. Check `npx wrangler containers info` in deploy/ (rollout).")
        sys.exit(f"ship: reload failed: {status} {body}")
    if wait_live(version, 120):
        print(f"ship: live in {time.time() - start:.0f}s: {version['label']}")
    else:
        sys.exit("ship: the board didn't come back with the new code within 2 minutes; check the Worker logs.")


if __name__ == "__main__":
    main()
