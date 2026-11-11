"""SQLite database. The schema is plain SQL so it ports to Postgres for the larger app.

Contract for downstream code: read `people`, `positions`, `education`, `skills`,
`derived_connections`, `contacts`, `shared_contacts`, `companies`. `contacts` holds each connection's
name, title and LinkedIn profile link (for the cohort's relationship graph); emails are never kept.
`contacts.contact_key` is a keyed fingerprint of the profile link (see contact_keys.py) that matches the
same person across classmates' exports.

The `contacts` table and `shared_contacts` view match cohort-api/migrations in the cloud database.
"""
import json
import sqlite3
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS people (
  person_id TEXT PRIMARY KEY,
  first_name TEXT, last_name TEXT, headline TEXT, industry TEXT, geo_location TEXT,
  consent_scopes TEXT NOT NULL,            -- e.g. "profile,connections"
  consent_at TEXT NOT NULL,
  export_date TEXT,
  updated_at TEXT NOT NULL,
  self_key TEXT,                           -- this classmate's own contact key, if their profile link was given
  profile_url TEXT                         -- this classmate's own LinkedIn link (never a contact's), given with consent
);
CREATE TABLE IF NOT EXISTS positions (
  person_id TEXT NOT NULL REFERENCES people(person_id),
  company_raw TEXT, company_norm TEXT, title TEXT, title_bucket TEXT,
  started_on TEXT, finished_on TEXT, is_current INTEGER
);
CREATE TABLE IF NOT EXISTS education (
  person_id TEXT NOT NULL REFERENCES people(person_id),
  school_raw TEXT, school_norm TEXT, degree TEXT, start_date TEXT, end_date TEXT
);
CREATE TABLE IF NOT EXISTS skills (
  person_id TEXT NOT NULL REFERENCES people(person_id),
  skill TEXT
);
CREATE TABLE IF NOT EXISTS derived_connections (
  connector_id TEXT NOT NULL REFERENCES people(person_id),
  company_norm TEXT NOT NULL,
  count INTEGER NOT NULL,
  top_title_bucket TEXT NOT NULL,
  snapshot_date TEXT NOT NULL,
  PRIMARY KEY (connector_id, company_norm)
);
-- One row per contact per classmate. Same person, same key, in every classmate's export.
CREATE TABLE IF NOT EXISTS contacts (
  contact_key TEXT NOT NULL,
  connector_id TEXT NOT NULL REFERENCES people(person_id),
  company_norm TEXT NOT NULL,
  title_bucket TEXT NOT NULL,
  connected_year INTEGER,
  snapshot_date TEXT,
  PRIMARY KEY (contact_key, connector_id)
);
CREATE INDEX IF NOT EXISTS contacts_by_company ON contacts (company_norm);
-- Knowledge source: the company registry, retrieved per ambiguous name.
CREATE TABLE IF NOT EXISTS companies (
  company_norm TEXT PRIMARY KEY,
  display_name TEXT,
  parent_norm TEXT,                        -- set when a subsidiary or unit of another
  source TEXT NOT NULL,                    -- seed | export | ai
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS aliases (
  alias TEXT PRIMARY KEY,                  -- a normalized or compressed name
  company_norm TEXT NOT NULL REFERENCES companies(company_norm),
  source TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS title_cache (
  title_norm TEXT NOT NULL, company_norm TEXT NOT NULL,
  bucket TEXT NOT NULL, source TEXT NOT NULL,
  PRIMARY KEY (title_norm, company_norm)
);
CREATE TABLE IF NOT EXISTS review_queue (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL, payload TEXT NOT NULL, reason TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ai_calls (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT, task TEXT, model TEXT, input_tokens INTEGER, output_tokens INTEGER,
  latency_ms INTEGER, cost_usd REAL, ok INTEGER, error TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ingest_runs (
  run_id TEXT PRIMARY KEY, person_id TEXT, source_file TEXT, ai_model TEXT,
  started_at TEXT, finished_at TEXT, summary TEXT
);
"""

# Contacts known by two or more classmates ("deep connections"). The company and job type come from the
# newest export that has the contact, in case they changed jobs between exports. Left out: classmates
# themselves (self_key), and students and school staff, who would otherwise dominate the list.
SHARED_CONTACTS_VIEW = """
CREATE VIEW IF NOT EXISTS shared_contacts AS
WITH latest AS (
  SELECT contact_key, company_norm, title_bucket,
         ROW_NUMBER() OVER (PARTITION BY contact_key ORDER BY snapshot_date DESC, connector_id) AS rn
  FROM contacts
)
SELECT k.contact_key, l.company_norm, l.title_bucket,
       COUNT(DISTINCT k.connector_id) AS depth,
       MIN(k.connected_year) AS first_connected_year
FROM contacts k
JOIN latest l ON l.contact_key = k.contact_key AND l.rn = 1
WHERE k.contact_key NOT IN (SELECT self_key FROM people WHERE self_key IS NOT NULL)
  AND l.title_bucket <> 'student_intern'
  AND l.company_norm NOT LIKE '%university%'
  AND l.company_norm NOT LIKE '%college%'
  AND l.company_norm NOT LIKE '%school%'
GROUP BY k.contact_key, l.company_norm, l.title_bucket
HAVING COUNT(DISTINCT k.connector_id) >= 2;
"""


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path):
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    # databases made before contact keys existed
    cols = {r["name"] for r in con.execute("PRAGMA table_info(people)")}
    for col in ("self_key", "profile_url"):
        if col not in cols:
            con.execute(f"ALTER TABLE people ADD COLUMN {col} TEXT")
    # contacts' names, titles and profile links (kept since the relationship graph)
    cols = {r["name"] for r in con.execute("PRAGMA table_info(contacts)")}
    for col in ("full_name", "position", "profile_url", "location"):
        if col not in cols:
            con.execute(f"ALTER TABLE contacts ADD COLUMN {col} TEXT")
    # what happened and when (Muse runs, merges, uploads); mirrors cohort-api/migrations/0011
    con.execute("""CREATE TABLE IF NOT EXISTS activity_log (id TEXT PRIMARY KEY, at TEXT NOT NULL, source TEXT NOT NULL,
                   action TEXT NOT NULL, person TEXT, summary TEXT NOT NULL, details TEXT)""")
    con.execute("CREATE INDEX IF NOT EXISTS activity_log_by_time ON activity_log (at)")
    # where each of a classmate's own jobs was (Positions.csv "Location"), for the map
    if "location" not in {r["name"] for r in con.execute("PRAGMA table_info(positions)")}:
        con.execute("ALTER TABLE positions ADD COLUMN location TEXT")
    con.executescript(SHARED_CONTACTS_VIEW)
    return con


def queue_review(con, kind, payload, reason):
    con.execute("INSERT INTO review_queue(kind, payload, reason, created_at) VALUES (?,?,?,?)",
                (kind, json.dumps(payload, ensure_ascii=False), reason, now()))
