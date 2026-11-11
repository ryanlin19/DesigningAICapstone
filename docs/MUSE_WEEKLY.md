# Muse weekly run: what to check and how to deliver it

Run once a week. Deliver results into the Cloudflare D1 database **`cohort`** (Cloudflare dashboard → Storage & Databases →
D1 → `cohort` → Console). The cohort board picks them up within 15 minutes, merges them, logs them on its Log tab,
and clears them. Nothing else needs to happen after you write the rows. (Pickup needs the board to be running; rows
wait safely in `muse_inbox` until it is.)

## 1. Start the run

```sql
INSERT INTO activity_log (id, at, source, action, summary)
VALUES ('muse-2026-11-18', '2026-11-18T09:00:00Z', 'muse', 'run', 'Muse weekly run started');
```
Use a new `id` each run (e.g. `muse-` + the date). Use the same value as `run_id` below.

## 2. For each change you find, add one row to `muse_inbox`

| change | when | fill in |
|---|---|---|
| `new_connection` | a classmate has a connection that isn't in the board yet | classmate, profile_url, full_name, company, title, connected_on, location if shown |
| `job_change` | a known contact's current company or title changed | profile_url, full_name, company, title (the new ones), previous_company, previous_title |
| `location` | a contact's city is shown or changed | profile_url, full_name, location (e.g. `Seattle, WA`) |
| `removed_connection` | a classmate is no longer connected to someone | classmate, profile_url, full_name |

```sql
INSERT INTO muse_inbox (id, run_id, found_at, classmate, change, profile_url, full_name, company, title, location,
                        connected_on, previous_company, previous_title, note)
VALUES ('muse-2026-11-18-001', 'muse-2026-11-18', '2026-11-18T09:05:00Z', 'peter-berzins', 'new_connection',
        'https://www.linkedin.com/in/jane-doe-1/', 'Jane Doe', 'Stripe', 'Product Manager', 'Seattle, WA',
        '2026-11-15', NULL, NULL, NULL);
```

Rules:
- `id`: unique per row (run id + a counter).
- `classmate`: the person whose connections you checked, as their board id (`peter-berzins`, `ryan-lin`, `sean-kim`,
  `matthew-mccammon`) or full name.
- `profile_url`: **always** include the LinkedIn profile link (`https://www.linkedin.com/in/<handle>/`). It's how the
  board matches the exact person. Rows without it are matched by name only, or skipped.
- Dates as `YYYY-MM-DD`, times as UTC ISO (`...Z`). Quote text with single quotes; double any `'` inside text (`O''Brien`).
- Report changes only: don't re-send people the board already has unchanged.
- No emails, phone numbers or messages.

## 3. Finish the run

```sql
INSERT INTO activity_log (id, at, source, action, summary)
VALUES ('muse-2026-11-18-done', '2026-11-18T09:40:00Z', 'muse', 'run', 'Muse weekly run finished: 3 new connections, 1 job change');
```

## Notes
- The board's Log tab shows "Muse last ran" from these rows, then one entry per change it merged.
- Don't write to `contacts`, `people` or other tables directly: the board applies the matching rules (same person by
  profile link, every classmate's copy updated, the log entry) only to what comes through `muse_inbox`.
- The older way (rows in `manual_connections` with a note starting "Muse") still works, but supports new connections only.
