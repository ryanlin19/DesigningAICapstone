"""Load files into the hosted board, or back them up. Reads the site address and token from deploy/.deploy.env.

    python3 deploy/push_state.py                       # push every file this computer has (the first move)
    python3 deploy/push_state.py all_jobs.json data.js descriptions.db companies.db    # after a new job download
    python3 deploy/push_state.py --pull                # back up everything the site holds into this repo's paths

Files: cohort.db (classmates and their contacts), companies.db (the company directory), all_jobs.json and data.js
(the job lists), descriptions.db (full job descriptions), sessions.json, settings.json, manual_connections.json.
The site picks up new job files and company directories within 10 minutes. cohort.db is the site's own once it
runs (uploads happen there): push it only for the first move, before anyone uploads on the site.
"""
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load_env():
    env = HERE / ".deploy.env"
    if not env.exists():
        sys.exit("No deploy/.deploy.env: run deploy/setup.sh first, or create it with PUBLIC_URL='...' and STATE_TOKEN='...'.")
    import shlex
    for line in env.read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            parts = shlex.split(v)
            os.environ.setdefault(k.strip(), parts[0] if parts else "")
    os.environ["COHORT_STATE_URL"] = os.environ["PUBLIC_URL"]
    os.environ["COHORT_STATE_TOKEN"] = os.environ["STATE_TOKEN"]


def main():
    load_env()
    sys.path.insert(0, str(HERE.parent / "cohort-board"))
    import state
    args = sys.argv[1:]
    if args and args[0] == "--pull":
        for name in args[1:] or state.files():
            print(f"{name}: {'pulled' if state.pull(name, force=True) else 'not stored'}", flush=True)
        return
    names = args or list(state.files())
    for name in names:
        if name not in state.files():
            sys.exit(f"Unknown file {name}. Files: {', '.join(state.files())}")
        path = state.files()[name]
        if not path.exists():
            print(f"{name}: not on this computer, skipped")
            continue
        size = path.stat().st_size
        print(f"{name}: pushing {size / 1048576:.1f} MB…", flush=True)
        state.push(name)
    print(f"Done. Open {os.environ['PUBLIC_URL']} (new job files show up within 10 minutes; a restart is immediate).")


if __name__ == "__main__":
    main()
