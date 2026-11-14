"""Scheduled work, the same jobs whether run by the board's own timers (on a computer) or by Cloudflare's schedule
(the hosted board: deploy/src/index.js calls POST /__task/<name> on the container).

    merge()     Muse's weekly findings (inbox.py) and Muse's company research (company-db/companies.py pull_research),
                every 15 minutes. The hosted board is woken for it only when something is waiting (GET /v1/pending).
    refresh()   the daily job refresh that used to run on Ryan's PC: download every job feed and rebuild
                (pipeline/build.py), check nothing collapsed, build the full job set and descriptions (expand.py,
                descriptions.py), load both builds into the cohort database (cohort-api/push_jobs.py --api), keep the
                pipeline's files (state.py), and log the result. Ryan's public site is never touched.

busy() says whether a long task is running, so the hosted container isn't put to sleep in the middle of one.
"""
import json
import subprocess
import sys
import threading
import time
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))
import inbox  # noqa: E402
import state  # noqa: E402

_lock = threading.Lock()                 # one task at a time
status = {"task": None, "started": None, "last": {}}


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _log(store, action, summary, details=None, source="board"):
    try:
        store.add_log([{"id": uuid.uuid4().hex[:16], "at": _now(), "source": source, "action": action, "person": None,
                        "summary": summary, "details": json.dumps(details, ensure_ascii=False) if details else None}])
    except Exception as e:                                   # the log is a record, not the job
        print(f"tasks: couldn't log: {e}", flush=True)


def busy():
    return status["task"] is not None


def _run(name, fn, store):
    if not _lock.acquire(blocking=False):
        return {"skipped": f"{status['task']} is running"}
    status.update(task=name, started=_now())
    try:
        out = fn(store)
        status["last"][name] = {"at": _now(), "result": out, "error": None}
        return out
    except Exception as e:
        status["last"][name] = {"at": _now(), "result": None, "error": str(e)}
        print(f"tasks: {name} failed: {e}", flush=True)
        raise
    finally:
        status.update(task=None, started=None)
        _lock.release()


# ---------- every 15 minutes ----------

def _merge(store):
    out = {"inbox": inbox.check(store)}
    if (REPO / "data" / "companies.db").exists():
        sys.path.insert(0, str(REPO / "company-db"))
        import companies
        out["research"] = companies.pull_research(store)
        if out["research"]["merged"]:
            state.push("companies.db")               # the rebuilt directory and Muse's results survive a restart
            state.push("company-db.tar.gz")
    return out


def merge(store):
    return _run("merge", _merge, store)


def start_timer(store, every=900, on_change=None):
    """On a computer: merge now and every 15 minutes (the hosted board uses Cloudflare's schedule instead)."""
    def loop():
        while True:
            try:
                res = merge(store)
                if on_change and (res.get("inbox", {}).get("found") or res.get("research", {}).get("merged")):
                    on_change()
            except Exception:
                pass                                   # recorded in status; tried again next time
            time.sleep(every)
    threading.Thread(target=loop, daemon=True).start()


# ---------- daily ----------

class RefreshFailed(RuntimeError):
    """A refresh failure that carries what's needed to see why (logged as the activity entry's details)."""
    def __init__(self, msg, details):
        super().__init__(msg)
        self.details = details


def _problems():
    try:
        return json.loads((REPO / "data" / "fetch_problems.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _step(cmd, log_lines, timeout=7200):
    t = time.time()
    r = subprocess.run([sys.executable, "-u"] + cmd, cwd=REPO, capture_output=True, text=True, timeout=timeout)
    log_lines.append(f"{' '.join(cmd)}: exit {r.returncode} in {time.time() - t:.0f}s")
    if r.returncode:
        raise RuntimeError(f"{cmd[0]} failed: {(r.stdout[-800:] + r.stderr[-800:]).strip()}")
    return r.stdout


def _roles(path):
    if not path.exists():
        return Counter()
    text = path.read_text(encoding="utf-8")
    return Counter(j["company"] for j in json.loads(text[text.index("{"):text.rindex("}") + 1])["jobs"])


def _refresh(store):
    sys.path.insert(0, str(REPO / "cohort-api"))
    import push_jobs
    lines, t0 = [], time.time()
    site = REPO / "site" / "data.js"
    before = _roles(site)
    (REPO / "data" / "fetch_problems.json").unlink(missing_ok=True)      # so an old run's reasons are never shown
    keep = {n: (REPO / "data" / n).read_bytes() for n in ("history.json", "boards.json") if (REPO / "data" / n).exists()}
    old_site = site.read_bytes() if site.exists() else None
    try:
        _step(["pipeline/build.py"], lines)
        after = _roles(site)
        total_b, total_a = sum(before.values()), sum(after.values())
        problems = _problems()
        if total_b and total_a < 0.75 * total_b:
            lost = sorted(before, key=lambda c: after.get(c, 0) - before[c])[:8]
            raise RuntimeError(f"role count fell from {total_b} to {total_a}; biggest losses: " + "; ".join(
                f"{c} {before[c]} -> {after.get(c, 0)}" + (f" ({problems[c]})" if c in problems else "") for c in lost if after.get(c, 0) < before[c]))
        collapsed = [f"{c} {n} -> {after.get(c, 0)}" + (f" ({problems[c]})" if c in problems else "")
                     for c, n in before.items() if n >= 15 and after.get(c, 0) < 0.4 * n]
        if collapsed:
            raise RuntimeError("these firms lost most of their roles (a feed reader may have broken): " + "; ".join(collapsed[:8]))
    except Exception as e:
        for n, b in keep.items():                    # a failed download isn't trusted: the previous files stay
            (REPO / "data" / n).write_bytes(b)
        if old_site is not None:
            site.write_bytes(old_site)
        raise RefreshFailed(str(e), {"error": str(e), "steps": lines, "failed_after_min": round((time.time() - t0) / 60, 1),
                                     "firms_with_no_jobs": _problems()}) from e
    stage = "expand"
    try:
        _step(["pipeline/expand.py"], lines)
        stage = "descriptions"
        _step(["pipeline/descriptions.py"], lines)
        stage = "push to the cohort database"
        board_id, n_board = push_jobs.push_api(store, site, "board")
        all_id, n_all = push_jobs.push_api(store, REPO / "data" / "all_jobs.json", "all")
        stage = "upload of the job files"
        for name in ("data.js", "all_jobs.json", "descriptions.db", "history.json", "boards.json"):
            state.push(name)
    except Exception as e:
        raise RefreshFailed(f"{stage}: {e}", {"error": str(e), "stage": stage, "steps": lines,
                                               "failed_after_min": round((time.time() - t0) / 60, 1)}) from e
    moves = sorted(((after.get(c, 0) - before.get(c, 0), c) for c in set(before) | set(after)), key=lambda x: -abs(x[0]))
    return {"board_roles": n_board, "board_before": total_b, "all_roles": n_all, "board_build": board_id, "all_build": all_id,
            "minutes": round((time.time() - t0) / 60, 1), "biggest_changes": [f"{c} {d:+d}" for d, c in moves[:8] if d], "steps": lines,
            "firms_with_no_jobs": _problems()}


def refresh(store):
    try:
        out = _run("refresh", _refresh, store)
    except Exception as e:
        _log(store, "job_refresh", f"Daily job refresh failed, the board keeps yesterday's jobs: {str(e)[:400]}",
             getattr(e, "details", None) or {"error": str(e)})
        raise
    if "skipped" not in out:
        _log(store, "job_refresh", f"Daily job refresh: {out['board_roles']:,} roles on the board (was {out['board_before']:,}), "
                                   f"{out['all_roles']:,} in Find a job, in {out['minutes']} min", out)
    return out


def refresh_later(store):
    """Start the refresh in the background (the scheduler's request returns at once)."""
    if busy():
        return {"skipped": f"{status['task']} is running"}
    threading.Thread(target=lambda: _safe(refresh, store), daemon=True).start()
    return {"started": True}


def _safe(fn, store):
    try:
        fn(store)
    except Exception:
        pass
