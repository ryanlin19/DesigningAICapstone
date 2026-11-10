"""Refresh the board: download every job feed, rebuild, check, then deploy to Cloudflare.

Usage:
    python pipeline/refresh.py              full refresh and deploy
    python pipeline/refresh.py --no-deploy  rebuild and check only (public/ is restored afterwards)

The live site is only touched when every check passes:
  1. build.py finishes and check_public.py prints OK (no firm-database wording in the public build);
  2. the role count did not collapse (at least 75% of yesterday's), and no firm that had 15+ roles lost more than 60%
     of them (that usually means a firm changed its careers site and the reader broke).
If a check fails, the previous public/ is put back and nothing is deployed. Everything is written to logs/refresh-DATE.txt.
"""
import datetime
import json
import re
import shutil
import subprocess
import tempfile
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOGS = ROOT / "logs"
KEEP_LOGS = 30
LOG_LINES = []


def log(msg=""):
    print(msg, flush=True)
    LOG_LINES.append(str(msg))


def write_log(status):
    LOGS.mkdir(exist_ok=True)
    stamp = datetime.date.today().isoformat()
    (LOGS / f"refresh-{stamp}.txt").write_text(f"STATUS: {status}\n" + "\n".join(LOG_LINES) + "\n", encoding="utf-8")
    for old in sorted(LOGS.glob("refresh-*.txt"))[:-KEEP_LOGS]:
        old.unlink()


def counts_from(data_js):
    """company -> number of roles in a public/data.js file (empty if the file is missing)."""
    if not data_js.exists():
        return Counter()
    text = data_js.read_text(encoding="utf-8")
    data = json.loads(text[len("window.BOARD_DATA = "):].rstrip().rstrip(";"))
    return Counter(j["company"] for j in data["jobs"])


def run(cmd, **kw):
    log("$ " + " ".join(cmd))
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", **kw)


def restore(backup, raw_too=True):
    for name in ("data.js", "index.html", "match_index.js"):
        if (backup / name).exists():
            shutil.copy2(backup / name, ROOT / "public" / name)
    raw = backup / "raw_fetch.json"
    if raw_too and raw.exists():
        shutil.copy2(raw, ROOT / "data" / "raw_fetch.json")     # a failed run's download is not trusted
    hist = backup / "history.json"
    if raw_too and hist.exists():
        shutil.copy2(hist, ROOT / "data" / "history.json")
    log("Previous public/ restored.")


def main():
    deploy = "--no-deploy" not in sys.argv
    log(f"Refresh started {datetime.datetime.now():%Y-%m-%d %H:%M} (deploy={'yes' if deploy else 'no'})")
    backup = Path(tempfile.mkdtemp(prefix="jcc_refresh_"))      # outside OneDrive, which can lock files
    for name in ("data.js", "index.html", "match_index.js"):
        if (ROOT / "public" / name).exists():
            shutil.copy2(ROOT / "public" / name, backup / name)
    if (ROOT / "data" / "raw_fetch.json").exists():
        shutil.copy2(ROOT / "data" / "raw_fetch.json", backup / "raw_fetch.json")
    if (ROOT / "data" / "history.json").exists():
        shutil.copy2(ROOT / "data" / "history.json", backup / "history.json")
    before = counts_from(backup / "data.js")

    def fail(reason):
        log(f"FAILED: {reason}")
        restore(backup)
        write_log("FAILED - nothing deployed")
        shutil.rmtree(backup, ignore_errors=True)
        sys.exit(1)

    r = run([sys.executable, "-u", "pipeline/build.py"])
    if r.returncode != 0:
        log(r.stdout[-1500:] + r.stderr[-1500:])
        fail("build.py failed")
    log(r.stdout.strip().splitlines()[1] if len(r.stdout.strip().splitlines()) > 1 else r.stdout.strip())

    r = run([sys.executable, "pipeline/check_public.py"])
    log(r.stdout.strip().splitlines()[-1] if r.stdout.strip() else "(no output)")
    if r.returncode != 0 or "OK" not in r.stdout:
        fail("the leak check did not pass")

    after = counts_from(ROOT / "public" / "data.js")
    total_before, total_after = sum(before.values()), sum(after.values())
    log(f"Roles: {total_before} before, {total_after} now")
    if total_before and total_after < 0.75 * total_before:
        fail(f"role count fell from {total_before} to {total_after}")
    collapsed = [f"{c} {n} -> {after.get(c, 0)}" for c, n in before.items() if n >= 15 and after.get(c, 0) < 0.4 * n]
    if collapsed:
        fail("these firms lost most of their roles (a reader may have broken): " + "; ".join(collapsed))

    moves = sorted(((after.get(c, 0) - before.get(c, 0), c) for c in set(before) | set(after)), key=lambda x: -abs(x[0]))
    log("Biggest changes: " + ", ".join(f"{c} {d:+d}" for d, c in moves[:10] if d))

    if not deploy:
        restore(backup, raw_too=False)          # keep the fresh download so `build.py --cached` can reuse it
        write_log("OK (dry run, nothing deployed)")
        shutil.rmtree(backup, ignore_errors=True)
        return
    npx = shutil.which("npx") or shutil.which("npx.cmd") or "npx"
    r = run([npx, "wrangler", "deploy"])
    log((r.stdout + r.stderr).strip()[-600:])
    shutil.rmtree(ROOT / ".wrangler", ignore_errors=True)
    if r.returncode != 0:
        fail("wrangler deploy failed")
    for d in ROOT.rglob("__pycache__"):
        shutil.rmtree(d, ignore_errors=True)
    write_log("OK - deployed")
    shutil.rmtree(backup, ignore_errors=True)
    log("Done.")


if __name__ == "__main__":
    main()
