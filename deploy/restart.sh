#!/bin/sh
# Restart the hosted board now, so it runs the image you just deployed (otherwise it waits for 10 idle minutes).
# Refuses while the daily refresh or a merge is running ("busy"); try again in a few minutes.
#   deploy/restart.sh
set -e
cd "$(dirname "$0")"
URL=$(sed -n 's/^PUBLIC_URL=//p' .deploy.env)
TOKEN=$(sed -n 's/^STATE_TOKEN=//p' .deploy.env)
curl -sS -A "cohort-board-restart" -X POST -H "X-Task-Token: $TOKEN" "$URL/__restart"
echo
