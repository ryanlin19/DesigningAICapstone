# Cohort API (Cloudflare D1 + Worker)

The cohort's only database. It holds the classmates who uploaded, their own jobs (with locations), education and
skills, their contacts (name, title, company, LinkedIn link, city when known; never emails), connections typed in by
hand, Muse's weekly deliveries and the activity log. Contacts are deduplicated across classmates by a keyed
fingerprint of their profile link. The board (`cohort-board/`) reads and writes it only through this Worker; nothing
about the cohort is kept on anyone's computer.

| Piece | Where |
|---|---|
| Database | Cloudflare D1 `cohort` (SQLite), on Peter Berzins's Cloudflare account |
| API | Worker `cohort-api` at https://cohort-api.pberzins.workers.dev, separate from Ryan's public `job-board` Worker |
| Schema | `migrations/*.sql` (plain SQL) |
| API code | `src/index.js` (no dependencies, no build step) |
| Loading data | uploads on the board (`cohort-board/uploads.py` → `POST /v1/import`); job builds with `push_jobs.py` |
| Backup | `sync.py backup` |

## Access

Every route except `/v1/health` needs `Authorization: Bearer <API_TOKEN>`. The token is a Worker secret
(`wrangler secret put API_TOKEN`) and a local copy lives in `cohort-board/.api`, which is not in git. The
private board (`cohort-board/serve.py`) calls the API from this computer, so the token never reaches a browser.

## Routes

| Route | Does |
|---|---|
| `GET /v1/health` | `{ok: true}`, no token needed |
| `GET /v1/snapshot` | what the company views need in one call: people, company registry, counts, per-job-type contact counts, unique-contact counts, shared contacts, hand-added connections |
| `GET /v1/people` | classmates, every column |
| `GET /v1/positions` | classmates' own jobs, every column (with locations) |
| `GET /v1/companies` | the company registry `{companies, aliases}` (uploads resolve names against it) |
| `GET /v1/contacts?company=<norm>` | contacts at up to 30 companies, with names, titles, links, cities |
| `GET /v1/contacts/all?limit=&offset=` | every contact, paged (up to 10,000 a page) → `{contacts, next}` |
| `GET /v1/log?limit=` | the activity log, newest first |
| `POST /v1/log` | add entries `{rows: [...]}` (ids already there are left alone) |
| `POST /v1/import` | one classmate's whole upload `{person_id, people, contacts, positions, education, skills, company_counts, companies, aliases}`: their old rows are deleted and the new ones inserted in one transaction; companies and aliases are merged |
| `POST /v1/people/:id/link` | set a classmate's own LinkedIn link `{profile_url, self_key}` |
| `DELETE /v1/people/:id` | remove a classmate and every row from their upload |
| `GET /v1/inbox` | Muse's deliveries: `muse_inbox` rows and `manual_connections` rows noted "Muse…" |
| `POST /v1/inbox/apply` | the board's merge of them, in one transaction: `{upsert: [contact rows], delete: [{contact_key, connector_id}], log: [...], clear_inbox: [ids], clear_manual: [ids]}` |
| `GET /v1/jobs/version`, `GET /v1/jobs` | the job board's roles (below) |
| `POST /v1/manual` | add a hand-entered connection `{company, classmate, contact, title, note}` |
| `DELETE /v1/manual/:id` | remove one |

There is no route that runs arbitrary SQL. Writes take rows as JSON; each insert statement binds one JSON array and
reads it with `json_each`, so a large upload stays within D1's 100-bound-parameters-per-query limit.

**Why Muse's changes are worked out on the board, not here:** matching a contact means fingerprinting their profile
link with the cohort's secret, which never leaves the board's computer, and uses the ingest's Python rules for
company names and job types. So `cohort-board/inbox.py` reads the deliveries and the contacts, applies the rules to an
in-memory copy, and sends only the resulting row changes to `/v1/inbox/apply`.

## Deduplication

`contacts` has one row per (contact, classmate). `contact_key` is a keyed fingerprint (HMAC) of the
contact's profile URL, made by the ingest (`linkedin-ingest/ingest/contact_keys.py`), so two classmates
who know the same person share a key and the board counts `COUNT(DISTINCT contact_key)`. Exports loaded
before keys existed sit in `company_counts` (totals only) until re-ingested.

The secret behind the keys lives only where the ingest runs (`linkedin-ingest/.contact_key`, not in git,
not in the cloud). It must stay the same for the whole cohort: back it up, and move it with the project.

## Job board roles

Migration 0005 adds `job_builds`, `jobs` (one row per role: filterable columns plus the full role as JSON in
`data`) and `job_build_meta` (stats, "What's new" changes; long values split into parts). Load a build with
`python cohort-api/push_jobs.py` after `pipeline/build.py`, or run `pipeline/build.py --push-db`. A push adds
the new build next to the current one, marks it complete last, then deletes older builds, so the board never
sees a half-loaded build. `GET /v1/jobs` returns the newest complete build shaped like the page's
`window.BOARD_DATA`; the private board uses it and falls back to `site/data.js` when no build is loaded.

## Shared contacts ("deep connections")

The `shared_contacts` view (migration 0002) lists people known by two or more classmates, with `depth`
(how many classmates) and `first_connected_year`. Their company and job type come from the newest export.
Left out: classmates themselves (`people.self_key`, from `--profile-url` at ingest), students
(`student_intern`) and anything at a university, college or school. The same view is defined in
`linkedin-ingest/ingest/db.py`; change both together.

Scale note: the view is computed on every snapshot. For a cohort of 50 (about 50,000 contact rows), each
snapshot reads a few hundred thousand rows; the board caches snapshots for 30 seconds. If daily reads near
the free limit (5 million), store the view's result in a table when an upload is imported instead.

## Day-to-day

Classmates upload, re-upload and are removed on the board. Muse's deliveries are merged by the board every 15
minutes. From a terminal:

```
python cohort-api/sync.py backup               # download the whole database as plain SQL (schema, data, migration history)
cd cohort-api && wrangler deploy               # after changing src/index.js
cd cohort-api && wrangler d1 migrations apply cohort --remote   # after adding a migrations/*.sql file
```

Testing without the real database: `npx wrangler d1 migrations apply cohort --local && npx wrangler dev --local
--port 8787` (token in `.dev.vars`), then run a board against it with `COHORT_API_URL=http://127.0.0.1:8787
COHORT_API_TOKEN=<that token> COHORT_PORT=8766 COHORT_BOARD_DATA=<scratch folder>`. Only fictional data there;
delete `.wrangler/state` afterwards.

Schema changes go in a new numbered file in `migrations/`, never by editing an applied one.

## Moving it

Nothing here depends on whose account it runs on, or on Cloudflare beyond the thin Worker.

**To another Cloudflare account** (for example a team account):
1. `python cohort-api/sync.py backup cohort.sql` while logged in to the old account.
2. `wrangler login` to the new account, then `wrangler d1 create cohort` and put the new `database_id` in `wrangler.jsonc`.
3. `wrangler d1 execute cohort --remote --file cohort.sql` (the backup includes the schema and migration history).
4. `wrangler deploy`, then `wrangler secret put API_TOKEN` with a fresh token.
5. Update `COHORT_API_URL` and `COHORT_API_TOKEN` in `cohort-board/.api`. Delete `cohort.sql`.

**Off Cloudflare** (Postgres, or SQLite on a server): the backup is SQLite SQL and the schema uses only
standard types, `PRIMARY KEY`, `ON CONFLICT` and `COUNT(DISTINCT ...)`, which Postgres also supports. Load the
tables, then reimplement the routes above (a few hundred lines in any language) and point `cohort-board/.api` at the
new service. The board only knows the API's URL and token.

**Offline testing only:** without `cohort-board/.api` the board uses a local SQLite file with the same tables
(`cohort-board/store.py`, `LocalStore`). It is not a copy of the cloud data.

Backups hold classmates' data: keep them out of git (`cohort-backup-*.sql` is ignored) and shared folders.
