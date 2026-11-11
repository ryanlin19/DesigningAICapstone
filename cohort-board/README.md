# Cohort Job Board (private test version)

The job board with a cohort-connections layer. It runs on this computer only and is never deployed.

```
python cohort-board/serve.py      # then open http://127.0.0.1:8765
```

- **Password:** `cohort-board/.password` (not in git) or the `COHORT_PASSWORD` environment variable.
- **Page:** Ryan's private build in `site/`, with hooks added as it is served. `site/` itself is never edited,
  so a rebuild of the board shows up on refresh. If his page changes shape, the server stops with a message
  naming the hook to update (`PATCHES` in `serve.py`).
- **Where the data lives:** the cloud database (Cloudflare D1 behind the `cohort-api` Worker, see its README),
  reached with the URL and token in `cohort-board/.api` (not in git). Every read and write goes through
  `store.py`; reads are cached for 30 seconds and dropped after each write. Nothing about classmates is kept on this
  computer. Without `.api` the board uses a local test database (`LocalStore`, for offline tests only).
- **Matching:** board companies are matched with the ingest's own normalizer and company registry.
  Subsidiaries count toward their parent. Contact totals are deduplicated where contact keys exist.
- **Connections added by hand:** the "+ Add a connection" form in each company.
- **Filter:** "Cohort: only companies where a classmate has connections" above the search box.
- **Add classmates:** drop LinkedIn export zips or unzipped folders (several at once). For each one the server
  (`uploads.py`) runs the ingest into a temporary SQLite file seeded with the cloud's company registry, sends that
  classmate's rows to the cloud in one request (`POST /v1/import`), and deletes the export and the temporary file.
  From a folder the browser sends only the five files the ingest reads. Loading someone again replaces their data
  (contacts' cities found by Muse are kept); Remove deletes them from the cloud. Needs the contact key
  (`linkedin-ingest/.contact_key` or `COHORT_CONTACT_KEY`). The AI option appears when `ANTHROPIC_API_KEY` is set.
- **Muse's weekly findings** (`inbox.py`, `muse/WEEKLY.md`): merged from the cloud every 15 minutes and on
  "Check now" in the Log tab.
- **Logins** last 30 days and survive restarts (`data/sessions.json`, hashed, not in git).
- **Testing without touching real data:** point the board at `wrangler dev` (`COHORT_API_URL=http://127.0.0.1:8787`,
  `COHORT_API_TOKEN` from `cohort-api/.dev.vars`), or at the offline store (`COHORT_API_URL=` and `COHORT_LOCAL_DB`),
  with `COHORT_BOARD_DATA` (another folder for logins) and `COHORT_PORT`. See `cohort-api/README.md`.

Do not copy any of this into `public/` or deploy it: it shows classmates' networks.
