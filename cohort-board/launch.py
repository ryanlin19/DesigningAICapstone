"""The hosted board's entry point (deploy/Dockerfile): runs serve.py, and swaps in new code without a new container
image and without closing the port, so updates go out while people are using the board.

deploy/ship.sh puts the board's code in code.tar.gz in the state bucket (R2) and asks the board to reload
(POST /__task/reload). serve.py passes that on here (SIGUSR1). This launcher unpacks the new code over the app and
starts a second serve.py next to the running one (both listen on the port: SO_REUSEPORT). When the new one is
listening it says so (COHORT_READY_FILE) and the old one gets SIGTERM: it stops taking requests, finishes the ones in
progress and any running task, and exits. If the new one fails to start, the old one keeps serving.

Files already on disk aren't downloaded again (state.py remembers their versions). Logins live in sessions.json (both
copies read and merge it) and everyone's filters in their own browser, so nobody is signed out.

At container start the stored code is unpacked too, but only when it's newer than the code in the image
(cohort-board/VERSION, written by ship.sh), so an image deploy never runs older code.
"""
import json
import os
import signal
import subprocess
import sys
import tarfile
import time
import urllib.error
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
CODE = "code.tar.gz"
sys.path.insert(0, str(HERE))
import state  # noqa: E402


def built(version_file=HERE / "VERSION"):
    try:
        return float(json.loads(version_file.read_text(encoding="utf-8")).get("built") or 0)
    except (OSError, ValueError):
        return 0.0


def update_code():
    """Unpack the shipped code when it's newer than what's here. -> its version label, or None."""
    if not state.enabled():
        return None
    try:
        with state._req("GET", CODE + ".manifest") as r:
            m = json.loads(r.read())
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise
    if float(m.get("built") or 0) <= built():
        return None
    tmp = Path("/tmp") / CODE
    with open(tmp, "wb") as out:
        for i in range(m["parts"]):
            with state._req("GET", f"{CODE}.{i:03d}") as r:
                out.write(r.read())
    with tarfile.open(tmp) as t:
        t.extractall(REPO, filter="data")
    tmp.unlink(missing_ok=True)
    return m.get("label")


def fetch_code():
    try:
        label = update_code()
        if label:
            print(f"launch: unpacked shipped code {label}", flush=True)
    except Exception as e:                       # never keep the board down over this: run what's on disk
        print(f"launch: couldn't fetch shipped code: {e}", flush=True)


def start(ready=None):
    env = dict(os.environ, COHORT_LAUNCHER="1")
    if ready:
        env["COHORT_READY_FILE"] = str(ready)
    return subprocess.Popen([sys.executable, str(HERE / "serve.py")], env=env)


def main():
    wanted = [False]
    signal.signal(signal.SIGUSR1, lambda *_: wanted.__setitem__(0, True))
    signal.signal(signal.SIGTERM, lambda *_: (current.send_signal(signal.SIGTERM), current.wait(), sys.exit(0)))
    fetch_code()
    current, old = start(), []
    while True:
        time.sleep(0.2)
        old = [p for p in old if p.poll() is None]           # old copies still finishing their requests
        rc = current.poll()
        if rc is not None:
            sys.exit(rc)                                     # the board stopped on its own: let the container restart
        if not wanted[0]:
            continue
        wanted[0] = False
        fetch_code()
        ready = Path("/tmp") / f"cohort-ready-{time.time_ns()}"
        new, began = start(ready), time.time()
        while not ready.exists() and new.poll() is None and time.time() - began < 300:
            time.sleep(0.1)
        if not ready.exists():
            print("launch: the new code didn't start; keeping the old one", flush=True)
            if new.poll() is None:
                new.kill()
            continue
        ready.unlink(missing_ok=True)
        print(f"launch: new code listening after {time.time() - began:.1f}s; retiring the old copy", flush=True)
        current.send_signal(signal.SIGTERM)
        old.append(current)
        current = new


if __name__ == "__main__":
    main()
