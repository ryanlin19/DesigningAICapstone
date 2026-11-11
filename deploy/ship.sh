#!/bin/sh
# Put the board's current code live, while people use it (deploy/ship.py). Add --image after Dockerfile/Worker changes.
cd "$(dirname "$0")"
export PATH="$HOME/.local/bin:$PATH"
case " $* " in *" --image "*) (docker info >/dev/null 2>&1 || colima start --vm-type vz --vz-rosetta) || exit 1 ;; esac
exec python3 ship.py "$@"
