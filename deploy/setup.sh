#!/usr/bin/env bash
# One-time setup of the hosted cohort board on the Cloudflare account you're logged into. Safe to run again
# (it redeploys and keeps the stored data). See DEPLOY.md.
set -euo pipefail
cd "$(dirname "$0")"

say() { printf '\n\033[1m%s\033[0m\n' "$*"; }
gen() { python3 -c 'import secrets; print(secrets.token_urlsafe(32))'; }

command -v python3 >/dev/null || { echo "Python 3 is needed."; exit 1; }
command -v npm >/dev/null || { echo "Node.js (npm) is needed: https://nodejs.org"; exit 1; }
command -v docker >/dev/null || { echo "Docker Desktop is needed to build the board's container: https://www.docker.com/products/docker-desktop/"; exit 1; }
docker info >/dev/null 2>&1 || { echo "Start Docker Desktop, then run this again."; exit 1; }

say "1/5 Installing the deploy tools"
npm install --silent

say "2/5 Cloudflare login"
npx wrangler whoami 2>/dev/null | grep -qi "associated with" || npx wrangler login
npx wrangler whoami 2>/dev/null | grep -i "associated with" || true
echo "Containers need the Workers Paid plan (\$5/month) on this account."

say "3/5 Storage for the board's files (R2 bucket cohort-board-state)"
npx wrangler r2 bucket create cohort-board-state 2>&1 | grep -v -i "already exists" || true

# Secrets: kept in deploy/.deploy.env (git-ignored) so this script and push_state.py can reuse them.
touch .deploy.env; chmod 600 .deploy.env
# shellcheck disable=SC1091
source .deploy.env
if [ -z "${BOARD_PASSWORD:-}" ]; then
  read -rsp "Choose the board password (what friends type to sign in): " BOARD_PASSWORD; echo
fi
if [ -z "${CONTACT_KEY:-}" ]; then
  if [ -f ../linkedin-ingest/.contact_key ]; then
    CONTACT_KEY=$(cat ../linkedin-ingest/.contact_key); echo "Using the contact key in linkedin-ingest/.contact_key."
  else
    echo "Contact key: it matches the same person across classmates' exports. If you're moving an existing cohort,"
    read -rsp "paste the key from the person who ran it (or press Enter to start a new cohort): " CONTACT_KEY; echo
    [ -n "$CONTACT_KEY" ] || CONTACT_KEY=$(gen)
  fi
fi
STATE_TOKEN=${STATE_TOKEN:-$(gen)}
# The cohort database: the cohort-api Worker and its D1 database on this account (DEPLOY.md, step 1).
if [ -z "${COHORT_API_URL:-}" ]; then
  read -rp "Cohort database address (the cohort-api Worker, https://cohort-api.<your-subdomain>.workers.dev): " COHORT_API_URL
fi
if [ -z "${COHORT_API_TOKEN:-}" ]; then
  read -rsp "Its API token (the API_TOKEN you set on cohort-api): " COHORT_API_TOKEN; echo
fi
curl -fsS -H "Authorization: Bearer $COHORT_API_TOKEN" "$COHORT_API_URL/v1/people" >/dev/null \
  || { echo "Couldn't reach the cohort database at $COHORT_API_URL with that token. Check DEPLOY.md step 1."; exit 1; }

say "4/5 Building and deploying (the first build takes a few minutes)"
OUT=$(npx wrangler deploy 2>&1 | tee /dev/stderr)
URL=$(printf '%s' "$OUT" | grep -Eo 'https://cohort-board\.[a-z0-9.-]+\.workers\.dev' | head -1)
[ -n "$URL" ] || URL=${PUBLIC_URL:-}
[ -n "$URL" ] || { read -rp "Couldn't read the site address from the output; paste it (https://...workers.dev): " URL; }

say "5/5 Saving the secrets on Cloudflare"
python3 - "$BOARD_PASSWORD" "$CONTACT_KEY" "$STATE_TOKEN" "$URL" "$COHORT_API_URL" "$COHORT_API_TOKEN" "${ANTHROPIC_API_KEY:-}" > .secrets.json <<'PY'
import json, sys
p, k, t, u, au, at, a = sys.argv[1:8]
d = {"BOARD_PASSWORD": p, "CONTACT_KEY": k, "STATE_TOKEN": t, "PUBLIC_URL": u, "COHORT_API_URL": au, "COHORT_API_TOKEN": at}
if a:
    d["ANTHROPIC_API_KEY"] = a
print(json.dumps(d))
PY
npx wrangler secret bulk .secrets.json; rm -f .secrets.json
python3 - "$BOARD_PASSWORD" "$CONTACT_KEY" "$STATE_TOKEN" "$URL" "$COHORT_API_URL" "$COHORT_API_TOKEN" > .deploy.env <<'PY'
import shlex, sys
for k, v in zip(("BOARD_PASSWORD", "CONTACT_KEY", "STATE_TOKEN", "PUBLIC_URL", "COHORT_API_URL", "COHORT_API_TOKEN"), sys.argv[1:7]):
    print(f"{k}={shlex.quote(v)}")
PY
chmod 600 .deploy.env

say "Done. The board: $URL"
echo "Next: load the job lists and company directory (DEPLOY.md, step 3):  python3 deploy/push_state.py"
