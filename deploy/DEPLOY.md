# Hosting the cohort board (one-time setup)

This puts the private cohort board online for the whole group: one shared site, one password, data that persists.
It runs on **your** Cloudflare account. Nothing here is tied to anyone else's account.

It is separate from the public job board: `npx wrangler deploy` at the repo root still publishes only `public/`
as the `job-board` Worker. The board deploys from `deploy/` as its own Worker, `cohort-board`, and its database from
`cohort-api/` as the `cohort-api` Worker.

**What gets created:** two Workers and their storage.
- `cohort-api` with its D1 database `cohort`: the cohort database (classmates, their contacts and jobs, Muse's
  deliveries, the activity log). It is the only copy of that data. Code and schema: `cohort-api/`.
- `cohort-board`: one container running the board, and one R2 bucket (`cohort-board-state`) for its other files (the
  company directory, the job lists, logins). The container stops after 20 idle minutes and starts again on the next
  visit (a few seconds).

## You need

- The Cloudflare **Workers Paid** plan ($5/month) on your account: containers need it.
- **Docker Desktop**, running: <https://www.docker.com/products/docker-desktop/> (it builds the board's container).
- Node.js and Python 3 (you already use both for the job board).
- From whoever ran the cohort until now, sent privately (not in git or chat history you keep):
  the **contact key** (`linkedin-ingest/.contact_key`) and a **backup of the cohort database** (`cohort.sql`, step 1).
  The key matches the same person across classmates' exports; without the same key, existing data and new uploads
  won't line up. Starting a brand-new cohort? Skip both.

## 1. The cohort database (cohort-api + D1)

```bash
git pull                                        # with peter_stuff merged in
cd cohort-api
npx wrangler login                              # your account
npx wrangler d1 create cohort                   # put the database_id it prints into cohort-api/wrangler.jsonc
```

Then either bring the existing cohort over, or start empty:

```bash
npx wrangler d1 execute cohort --remote --file cohort.sql     # moving: the backup holds the schema and the data
npx wrangler d1 migrations apply cohort --remote              # starting empty (also run after a move: applies newer files)
```

The backup is made on the old account with `python3 cohort-api/sync.py backup cohort.sql`. It holds classmates' data:
delete it once loaded.

```bash
npx wrangler deploy                             # the cohort-api Worker; prints https://cohort-api.<your-subdomain>.workers.dev
python3 -c 'import secrets; print(secrets.token_urlsafe(32))'
npx wrangler secret put API_TOKEN               # paste the token you just made; keep it for step 2
curl -s -H "Authorization: Bearer <token>" https://cohort-api.<your-subdomain>.workers.dev/v1/people | head -c 200
cd ..
```

The last line should print `{"people":[...` (empty for a new cohort).

## 2. The board

```bash
deploy/setup.sh
```

It installs the tools, logs you into Cloudflare if needed, creates the R2 bucket, asks for a **board password**
(what friends type to sign in), the **contact key**, and the cohort database's address and token from step 1, checks
it can reach the database, builds and deploys, and saves the secrets on Cloudflare. At the end it prints the site
address, e.g. `https://cohort-board.<your-subdomain>.workers.dev`.

Your answers are kept in `deploy/.deploy.env` (git-ignored, readable only by you) so you can run `setup.sh` again
to redeploy after pulling changes. It keeps all stored data.

## 3. Load the job lists and company directory

Open the address, sign in with the board password. Classmates and contacts show already (they come from the cohort
database); jobs and the company directory need this step. These files live on the computer that ran the board until
now (they're git-ignored, so they're not in your clone). On **that** computer, create `deploy/.deploy.env` with the
two lines from yours:

```
PUBLIC_URL='https://cohort-board.<your-subdomain>.workers.dev'
STATE_TOKEN='...'
```

then run:

```bash
python3 deploy/push_state.py
```

It uploads the company directory, the job lists and descriptions. Restart the container to see them right away
(redeploy, or wait for it to sleep); they're also picked up on their own within 10 minutes.

## Day to day

- **Friends:** open the address, sign in, use "Upload your data" (top right) to add their LinkedIn export. It goes
  straight into the cohort database.
- **New job download:** run the job pipeline as usual (`pipeline/build.py`, `expand.py`, `descriptions.py`), then
  `python3 deploy/push_state.py all_jobs.json data.js descriptions.db`.
- **Company directory updated** (`company-db/companies.py merge`): `python3 deploy/push_state.py companies.db`.
- **Back up the cohort database:** `python3 cohort-api/sync.py backup` (logged in to the account that has it).
- **Back up the site's other files:** `python3 deploy/push_state.py --pull` (writes to this repo's usual paths).
- **Change the password:** edit `BOARD_PASSWORD` in `deploy/.deploy.env`, run `deploy/setup.sh`.
- **Logs:** Cloudflare dashboard → Workers → cohort-board (or cohort-api) → Logs, or `npx wrangler tail` in `deploy/`
  or `cohort-api/`.

## Optional: sign-in by email instead of a shared password

Cloudflare Zero Trust → Access → add an application for the site address, with a policy listing your friends'
emails. They then get a one-time code by email before they reach the board (free for up to 50 people). The board
password still applies after that.

## If something goes wrong

- The board stops with "needs the cohort database": `COHORT_API_URL` / `COHORT_API_TOKEN` weren't saved; run
  `deploy/setup.sh` again. "Couldn't reach the cohort database": check step 1 (deployed, `API_TOKEN` set, same token).

- `setup.sh` says Docker isn't running: open Docker Desktop, wait for it to start, run again.
- Deploy rejects `instance_type`: set it in `deploy/wrangler.jsonc` to one of the types the error lists (the board
  needs about 400 MB of memory).
- The site shows "Set a password": the secrets weren't saved; run `deploy/setup.sh` again.
- Uploads fail with "No contact key": the `CONTACT_KEY` secret is missing; run `deploy/setup.sh` again.
