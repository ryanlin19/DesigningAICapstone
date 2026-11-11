-- What Muse delivers after each run: one row per change it found, read and cleared by the board (cohort-board/inbox.py).
-- change: new_connection | job_change | location | removed_connection. Keyed by the contact's LinkedIn profile link.
CREATE TABLE IF NOT EXISTS muse_inbox (
  id               TEXT PRIMARY KEY,
  run_id           TEXT,
  found_at         TEXT NOT NULL,
  classmate        TEXT NOT NULL,     -- whose connection: person_id (e.g. peter-berzins) or full name
  change           TEXT NOT NULL,
  profile_url      TEXT,
  full_name        TEXT,
  company          TEXT,
  title            TEXT,
  location         TEXT,
  connected_on     TEXT,
  previous_company TEXT,
  previous_title   TEXT,
  note             TEXT
);
-- a contact's current city (from Muse's location changes), mirrored like every other column
ALTER TABLE contacts ADD COLUMN location TEXT;
