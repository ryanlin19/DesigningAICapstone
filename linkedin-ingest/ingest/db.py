"""SQLite database. The schema is plain SQL so it ports to Postgres for the larger app.

Contract for downstream code: read `people`, `positions`, `education`, `skills`,
`derived_connections`, `companies`. No table holds a connection's name, email,
profile URL or individual title.
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
  updated_at TEXT NOT NULL
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


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path):
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def queue_review(con, kind, payload, reason):
    con.execute("INSERT INTO review_queue(kind, payload, reason, created_at) VALUES (?,?,?,?)",
                (kind, json.dumps(payload, ensure_ascii=False), reason, now()))
