# Cohort Job Board (private test version)

The job board with a cohort-connections layer. It runs on this computer only and is never deployed.

```
python cohort-board/serve.py      # then open http://127.0.0.1:8765
```

- **Password:** `cohort-board/.password` (not in git) or the `COHORT_PASSWORD` environment variable.
- **Page:** Ryan's private build in `site/`, with hooks added as it is served. `site/` itself is never edited,
  so a rebuild of the board shows up on refresh. If his page changes shape, the server stops with a message
  naming the hook to update (`PATCHES` in `serve.py`).
- **Where connections live:** when `cohort-board/.api` exists (not in git; holds the API URL and token),
  everything is read from and saved to the cloud database (`cohort-api/`, see its README). Without it, the
  board falls back to `linkedin-ingest/data/cohort.db` (read-only) and `cohort-board/data/manual_connections.json`.
- **Matching:** board companies are matched with the ingest's own normalizer and company registry.
  Subsidiaries count toward their parent. Contact totals are deduplicated where contact keys exist.
- **Connections added by hand:** the "+ Add a connection" form in each company.
- **Filter:** "Cohort: only companies where a classmate has connections" above the search box.
- **Add classmates:** drop LinkedIn export zips or unzipped folders (several at once). For each one the server
  (`uploads.py`) runs the ingest into `linkedin-ingest/data/cohort.db`, pushes that classmate to the cloud
  database with `cohort-api/sync.py`, and deletes the export. From a folder the browser sends only the five
  files the ingest reads. Loading someone again replaces their data; Remove deletes them locally and in the
  cloud. Needs `linkedin-ingest/.contact_key` and a Wrangler login on this computer. The AI option appears
  when `ANTHROPIC_API_KEY` is set.
- **Logins** last 30 days and survive restarts (`data/sessions.json`, hashed, not in git).
- **Testing without touching real data:** `COHORT_INGEST_DB` (another ingest database), `COHORT_D1_LOCAL=1`
  (push to the `wrangler dev` copy), `COHORT_BOARD_DATA` (another folder for logins), `COHORT_PORT`.

Do not copy any of this into `public/` or deploy it: it shows classmates' networks.
