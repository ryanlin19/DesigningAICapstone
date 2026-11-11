-- What happened, when, and who did it: Muse runs and what they found, merges into the cohort data, uploads and
-- removals. Mirrored in the local ingest database; shown on the board's Log tab.
CREATE TABLE IF NOT EXISTS activity_log (
  id      TEXT PRIMARY KEY,
  at      TEXT NOT NULL,          -- ISO time, UTC
  source  TEXT NOT NULL,          -- muse | upload | board | sync
  action  TEXT NOT NULL,          -- run | new_connection | merge | upload | remove | push
  person  TEXT,                   -- the classmate it concerns, if any (person_id)
  summary TEXT NOT NULL,          -- one plain sentence
  details TEXT                    -- JSON with specifics
);
CREATE INDEX IF NOT EXISTS activity_log_by_time ON activity_log (at);
