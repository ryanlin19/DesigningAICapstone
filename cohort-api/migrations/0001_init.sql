-- Cohort connections. Plain SQL: runs on SQLite (Cloudflare D1) and, with the types unchanged, on Postgres.
-- No table holds a contact's name, email or profile URL.

CREATE TABLE IF NOT EXISTS people (                -- classmates who shared their export
  person_id      TEXT PRIMARY KEY,
  display_name   TEXT NOT NULL,
  consent_scopes TEXT NOT NULL,                    -- e.g. "connections,profile"
  consent_at     TEXT NOT NULL,
  updated_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS companies (             -- company registry (from the ingest)
  company_norm TEXT PRIMARY KEY,
  display_name TEXT,
  parent_norm  TEXT                                -- set for a subsidiary or unit of another company
);

CREATE TABLE IF NOT EXISTS aliases (               -- other spellings that mean the same company
  alias        TEXT PRIMARY KEY,
  company_norm TEXT NOT NULL
);

-- One row per contact per classmate. This is what makes deduplication possible:
-- contact_key is a keyed fingerprint (HMAC) of the contact's profile URL, never the URL itself,
-- so two classmates who know the same person share a contact_key.
CREATE TABLE IF NOT EXISTS contacts (
  contact_key   TEXT NOT NULL,
  connector_id  TEXT NOT NULL,
  company_norm  TEXT NOT NULL,
  title_bucket  TEXT NOT NULL,
  snapshot_date TEXT,
  PRIMARY KEY (contact_key, connector_id)
);
CREATE INDEX IF NOT EXISTS contacts_by_company ON contacts (company_norm);

-- Per-company counts from exports loaded before contact keys existed. These cannot be deduplicated;
-- re-ingesting that classmate's export with contact keys replaces them.
CREATE TABLE IF NOT EXISTS company_counts (
  connector_id     TEXT NOT NULL,
  company_norm     TEXT NOT NULL,
  count            INTEGER NOT NULL,
  top_title_bucket TEXT NOT NULL,
  snapshot_date    TEXT,
  PRIMARY KEY (connector_id, company_norm)
);

-- Connections a classmate typed in on the board.
CREATE TABLE IF NOT EXISTS manual_connections (
  id        TEXT PRIMARY KEY,
  company   TEXT NOT NULL,                         -- company name as shown on the board
  classmate TEXT NOT NULL,
  contact   TEXT,
  title     TEXT,
  note      TEXT,
  added_at  TEXT NOT NULL
);
