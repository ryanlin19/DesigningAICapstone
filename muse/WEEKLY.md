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

## 2. Check every classmate who has uploaded, newest connections first

Check **every** classmate in the `people` table, not only Peter, one at a time:

```sql
SELECT person_id, display_name, profile_url FROM people ORDER BY person_id;
```

For each classmate, get the connections the board already has for them (you only read `contacts`, never write it):

```sql
SELECT profile_url, full_name FROM contacts WHERE connector_id = 'ryan-lin';
```

Then on LinkedIn:
1. Open that classmate's connections list **sorted by recently added, newest first**. For Peter this is his own
   Connections page. For other classmates, open their profile's connections list from Peter's account.
2. Read from the top. Every connection that isn't in the board's list for that classmate is a `new_connection`
   (step 3).
3. **Stop at the first 3 connections in a row that the board already has.** Everything below them is older. Don't page
   through the rest of the list.
4. Never load more than **10 pages** of one classmate's list. If you hit that limit before finding 3 known ones in a
   row, stop there and say so in that classmate's log entry.

When the list can't be sorted newest first (LinkedIn may not offer that sort for someone else's connections), don't
read the whole list. Instead, check only whether that classmate is now connected to each of the **other classmates**
(search their connections for each classmate's name), report any new classmate-to-classmate connection, and write
`"how": "no recent-first sort; checked classmates only"` in their log entry.

If a classmate's connections aren't visible to Peter (they hid them), skip that classmate and log
`"connections hidden"`.

Job changes, locations and removed connections stay as before: report them when you notice them on the way. Don't
open extra profiles to look for them.

## 3. For each change you find, add one row to `muse_inbox`

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

## 4. Log what you did on LinkedIn, one entry per classmate

After you finish each classmate (whether or not you found changes), record what you looked at. This is how the board's
owner sees what the run did; keep it accurate.

```sql
INSERT INTO activity_log (id, at, source, action, person, summary, details)
VALUES ('muse-2026-11-18-peter-berzins', '2026-11-18T09:12:00Z', 'muse', 'checked', 'peter-berzins',
        'Checked Peter Berzins''s connections: 832 listed, 6 profiles opened, 2 changes',
        '{"started_at": "2026-11-18T09:05:00Z", "finished_at": "2026-11-18T09:12:00Z", "connections_listed": 832,
          "pages_viewed": 9, "profiles_opened": ["https://www.linkedin.com/in/jane-doe-1/"], "changes": 2,
          "how": "scrolled the Connections page sorted by recently added; stopped at 3 known in a row",
          "stopped_because": "3 known in a row | 10-page limit | no recent-first sort | connections hidden"}');
```

- `id`: run id + `-` + the classmate's id. `person`: the classmate's board id.
- `details` is JSON: when you started and finished, how many connections the list showed, how many LinkedIn pages you
  loaded in total, the link of every profile you opened, the number of changes, and one sentence on how you checked.
- **If LinkedIn shows any warning, captcha, "unusual activity" notice, sign-in challenge or limit: stop the whole run
  immediately**, log it, and don't continue with other classmates:

```sql
INSERT INTO activity_log (id, at, source, action, person, summary, details)
VALUES ('muse-2026-11-18-warning', '2026-11-18T09:20:00Z', 'muse', 'warning', 'sean-kim',
        'LinkedIn showed a security check while checking Sean Kim''s connections; run stopped',
        '{"what_linkedin_showed": "exact wording of the notice", "pages_viewed_before": 14}');
```

## 5. Finish the run

```sql
INSERT INTO activity_log (id, at, source, action, summary)
VALUES ('muse-2026-11-18-done', '2026-11-18T09:40:00Z', 'muse', 'run', 'Muse weekly run finished: 3 new connections, 1 job change');
```

## Notes
- The board's Log tab shows "Muse last ran" from these rows, then one entry per change it merged.
- Don't write to `contacts`, `people` or other tables directly: the board applies the matching rules (same person by
  profile link, every classmate's copy updated, the log entry) only to what comes through `muse_inbox`.
- The older way (rows in `manual_connections` with a note starting "Muse") still works, but supports new connections only.
