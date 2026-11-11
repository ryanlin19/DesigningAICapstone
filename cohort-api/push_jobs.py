"""Load the job board's roles from a build into the cloud database (Cloudflare D1).

    python pipeline/build.py                     # build as usual (writes site/data.js)
    python cohort-api/push_jobs.py               # load that build into D1; the board switches to it
    python cohort-api/push_jobs.py --local       # into the `wrangler dev` copy instead (testing)
    python cohort-api/push_jobs.py --file X.js   # load another data.js
    python cohort-api/push_jobs.py --api         # through the cohort API (cohort-board/.api) instead of wrangler: no login
                                                 # needed; the hosted board's daily refresh uses this

Each push is a new version: rows go in next to the current build, the build is marked complete last,
and only then are older builds deleted. Reads always use the newest complete build.
Uses the private build (site/data.js), so the database holds the full visa reasons: it is private
(the API needs the token), unlike Ryan's public site.
"""
import argparse
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from sync import SyncError, q, run_sql  # noqa: E402

DEFAULT_FILE = HERE.parent / "site" / "data.js"
MAX_STATEMENT = 90_000          # D1 limits one SQL statement to 100 KB
META_PART = 60_000              # chunk size for large meta values (quoting can grow them)


def read_board(path):
    text = Path(path).read_text(encoding="utf-8")
    return json.loads(text[text.index("{"): text.rindex("}") + 1])


def job_inserts(build_id, jobs):
    """INSERT statements for the jobs, each kept under the statement size limit."""
    cols = "(build_id,id,seq,company,grp,title,category,seniority,mba,review,visa,posted,url,data)"
    out, batch, size = [], [], 0
    for seq, j in enumerate(jobs):
        row = "(" + ",".join([q(build_id), q(int(j["id"])), q(seq), q(j.get("company") or ""), q(j.get("group")), q(j.get("title") or ""),
                              q(j.get("category")), q(j.get("seniority")), q(j.get("mba")), q(1 if j.get("review") else 0),
                              q(j.get("visa")), q(j.get("posted")), q(j.get("url")),
                              q(json.dumps(j, ensure_ascii=False, separators=(",", ":")))]) + ")"
        if len(row) > MAX_STATEMENT - 200:
            raise SyncError(f"Role {j.get('id')} at {j.get('company')} is too large for one statement ({len(row)} bytes).")
        if batch and size + len(row) > MAX_STATEMENT - 200:
            out.append(f"INSERT INTO jobs {cols} VALUES\n" + ",\n".join(batch) + ";")
            batch, size = [], 0
        batch.append(row)
        size += len(row) + 2
    if batch:
        out.append(f"INSERT INTO jobs {cols} VALUES\n" + ",\n".join(batch) + ";")
    return out


def meta_inserts(build_id, board):
    out = []
    for key, value in board.items():
        if key == "jobs":
            continue
        text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        for part, i in enumerate(range(0, max(len(text), 1), META_PART)):
            out.append("INSERT INTO job_build_meta (build_id,key,part,value) VALUES "
                       f"({q(build_id)},{q(key)},{part},{q(text[i:i + META_PART])});")
    return out


def push(path=DEFAULT_FILE, target="--remote", kind="board"):
    """kind: "board" (Ryan's build) or "all" (every US posting, pipeline/expand.py). Each kind keeps its own versions."""
    board = read_board(path)
    jobs = board.get("jobs") or []
    if not jobs:
        raise SyncError(f"No jobs in {path}.")
    now = datetime.now(timezone.utc)
    build_id = f"{kind}-{now:%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:6]}"
    old = f"SELECT build_id FROM job_builds WHERE kind = {q(kind)} AND build_id <> {q(build_id)}"
    sql = ["DELETE FROM jobs WHERE build_id IN (SELECT build_id FROM job_builds WHERE complete = 0);",
           "DELETE FROM job_build_meta WHERE build_id IN (SELECT build_id FROM job_builds WHERE complete = 0);",
           "DELETE FROM job_builds WHERE complete = 0;",
           f"INSERT INTO job_builds (build_id,generated,pushed_at,jobs,complete,kind) VALUES "
           f"({q(build_id)},{q(board.get('generated'))},{q(now.isoformat(timespec='seconds'))},{len(jobs)},0,{q(kind)});"]
    sql += job_inserts(build_id, jobs)
    sql += meta_inserts(build_id, board)
    sql += [f"UPDATE job_builds SET complete = 1 WHERE build_id = {q(build_id)};",       # the switch
            f"DELETE FROM jobs WHERE build_id IN ({old});",
            f"DELETE FROM job_build_meta WHERE build_id IN ({old});",
            f"DELETE FROM job_builds WHERE kind = {q(kind)} AND build_id <> {q(build_id)};"]
    run_sql(sql, f"jobs build {build_id} ({len(jobs)} roles, generated {board.get('generated')})", target)
    return build_id, len(jobs)


def push_api(store, path=DEFAULT_FILE, kind="board", chunk=500):
    """The same build, loaded through the cohort API (POST /v1/jobs/builds...) with a cohort-board store. Returns
    (build_id, roles). The board keeps the current build until the last step switches it."""
    board = read_board(path)
    jobs = board.get("jobs") or []
    if not jobs:
        raise SyncError(f"No jobs in {path}.")
    call = lambda p, b, want=(200,): store._ok("POST", p, b, want=want, timeout=120)       # noqa: E731
    build_id = call("/v1/jobs/builds", {"kind": kind, "generated": board.get("generated"), "jobs": len(jobs)}, (201,))["build_id"]
    rows = [{"id": int(j["id"]), "seq": seq, "company": j.get("company") or "", "grp": j.get("group"), "title": j.get("title") or "",
             "category": j.get("category"), "seniority": j.get("seniority"), "mba": j.get("mba"), "review": 1 if j.get("review") else 0,
             "visa": j.get("visa"), "posted": j.get("posted"), "url": j.get("url"),
             "data": json.dumps(j, ensure_ascii=False, separators=(",", ":"))} for seq, j in enumerate(jobs)]
    for i in range(0, len(rows), chunk):
        call(f"/v1/jobs/builds/{build_id}/rows", {"rows": rows[i:i + chunk]})
    for key, value in board.items():
        if key == "jobs":
            continue
        text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        for part, i in enumerate(range(0, max(len(text), 1), META_PART)):
            call(f"/v1/jobs/builds/{build_id}/meta", {"key": key, "part": part, "value": text[i:i + META_PART]})
    call(f"/v1/jobs/builds/{build_id}/finish", {})
    return build_id, len(jobs)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--file", type=Path, default=DEFAULT_FILE)
    ap.add_argument("--local", action="store_true")
    ap.add_argument("--kind", choices=["board", "all"], default="board")
    ap.add_argument("--api", action="store_true")
    a = ap.parse_args()
    try:
        if a.api:
            sys.path.insert(0, str(HERE.parent / "cohort-board"))
            import store
            build_id, n = push_api(store.make_store(), a.file, a.kind)
        else:
            build_id, n = push(a.file, "--local" if a.local else "--remote", a.kind)
    except SyncError as e:
        sys.exit(str(e))
    print(f"Loaded {n} roles as build {build_id}.")


if __name__ == "__main__":
    main()
