# Cohort API (Cloudflare D1 + Worker)

The shared database behind the cohort connections layer. It stores what classmates' LinkedIn exports
say about companies (never a contact's name, email or profile URL), plus connections typed in by hand,
and is built so contacts can be deduplicated across classmates.

| Piece | Where |
|---|---|
| Database | Cloudflare D1 `cohort` (SQLite), on Peter Berzins's Cloudflare account |
| API | Worker `cohort-api` at https://cohort-api.pberzins.workers.dev, separate from Ryan's public `job-board` Worker |
| Schema | `migrations/*.sql` (plain SQL) |
| API code | `src/index.js` (no dependencies, no build step) |
| Loading data | `sync.py` (runs `wrangler d1 execute`) |

## Access

Every route except `/v1/health` needs `Authorization: Bearer <API_TOKEN>`. The token is a Worker secret
(`wrangler secret put API_TOKEN`) and a local copy lives in `cohort-board/.api`, which is not in git. The
private board (`cohort-board/serve.py`) calls the API from this computer, so the token never reaches a browser.

## Routes

| Route | Does |
|---|---|
| `GET /v1/health` | `{ok: true}`, no token needed |
| `GET /v1/snapshot` | everything the board needs: people, company registry, counts, per-job-type contact counts, unique-contact counts, hand-added connections |
| `POST /v1/manual` | add a hand-entered connection `{company, classmate, contact, title, note}` |
| `DELETE /v1/manual/:id` | remove one |

## Deduplication

`contacts` has one row per (contact, classmate). `contact_key` is a keyed fingerprint (HMAC) of the
contact's profile URL, made by the ingest (`linkedin-ingest/ingest/contact_keys.py`), so two classmates
who know the same person share a key and the board counts `COUNT(DISTINCT contact_key)`. Exports loaded
before keys existed sit in `company_counts` (totals only) until re-ingested.

The secret behind the keys lives only where the ingest runs (`linkedin-ingest/.contact_key`, not in git,
not in the cloud). It must stay the same for the whole cohort: back it up, and move it with the project.

## Shared contacts ("deep connections")

The `shared_contacts` view (migration 0002) lists people known by two or more classmates, with `depth`
(how many classmates) and `first_connected_year`. Their company and job type come from the newest export.
Left out: classmates themselves (`people.self_key`, from `--profile-url` at ingest), students
(`student_intern`) and anything at a university, college or school. The same view is defined in
`linkedin-ingest/ingest/db.py`; change both together.

Scale note: the view is computed on every snapshot. For a cohort of 50 (about 50,000 contact rows), each
snapshot reads a few hundred thousand rows; the board caches snapshots for 30 seconds. If daily reads near
the free limit (5 million), store the view's result in a table during `sync.py push` instead.

## Day-to-day

```
python cohort-api/sync.py push                 # upload everyone in linkedin-ingest/data/cohort.db
python cohort-api/sync.py push connector-a     # upload or refresh one person
python cohort-api/sync.py remove connector-a   # delete one person and all their rows
python cohort-api/sync.py backup               # download the whole database as plain SQL
cd cohort-api && wrangler deploy               # after changing src/index.js
cd cohort-api && wrangler d1 migrations apply cohort --remote   # after adding a migrations/*.sql file
```

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
tables, then reimplement the four routes above (about 100 lines in any language) or point `serve.py`'s
`RemoteStore` at the new service. The board only knows the API's URL and token.

**Back to local only:** delete `cohort-board/.api` and the board reads `linkedin-ingest/data/cohort.db` again.

Backups hold classmates' data: keep them out of git (`cohort-backup-*.sql` is ignored) and shared folders.
