"""Back up the cohort's cloud database (Cloudflare D1), and the SQL helpers push_jobs.py uses.

    python cohort-api/sync.py backup [file.sql]    # download the whole cloud database as plain SQL

The cloud database is the only copy of the cohort's data: the board reads and writes it through the cohort API
(cohort-api/src/index.js), and uploads go straight there (cohort-board/uploads.py). Back it up now and then; the file
holds classmates' data, so keep it out of git (cohort-backup-*.sql is ignored) and shared folders.
"""
import argparse
import os
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
D1_NAME = "cohort"


def q(v):
    """SQL literal. Strings are single-quoted with quotes doubled; NUL bytes dropped."""
    if v is None:
        return "NULL"
    if isinstance(v, (int, float)):
        return str(v)
    return "'" + str(v).replace("\x00", "").replace("'", "''") + "'"


class SyncError(Exception):
    pass


def run_sql(statements, label, target="--remote"):
    """Run SQL statements on D1 with `wrangler d1 execute --file` (used by push_jobs.py). Raises SyncError."""
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


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("backup")
    b.add_argument("output", nargs="?")
    a = ap.parse_args()
    if a.cmd == "backup":
        out = a.output or f"cohort-backup-{datetime.now():%Y-%m-%d}.sql"
        r = subprocess.run(["wrangler", "d1", "export", D1_NAME, "--remote", "--output", str(Path(out).resolve())], cwd=HERE)
        if r.returncode:
            sys.exit(r.returncode)
        print(f"Backup written to {out}. It holds classmates' data: keep it out of git and shared folders.")


if __name__ == "__main__":
    main()
