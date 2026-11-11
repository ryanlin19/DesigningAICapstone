-- Company research for Muse (muse/COMPANY_RESEARCH.md): one row per company in the directory that nobody has checked.
-- company-db/companies.py muse-push adds the rows; Muse fills `result` and sets status 'done'; muse-pull merges them into
-- the company directory and sets 'merged' (or 'needs_fix' with `error` when a result can't be used).
CREATE TABLE IF NOT EXISTS company_research (
  id            TEXT PRIMARY KEY,      -- the directory's company id
  name          TEXT NOT NULL,
  info          TEXT,                  -- JSON: spellings people use, an automatic Wikidata guess (may be wrong), metros with job postings
  tier          INTEGER,               -- 1 = most cohort ties, 3 = fewest: do lower tiers first
  status        TEXT NOT NULL DEFAULT 'todo',   -- todo | done | merged | needs_fix
  result        TEXT,                  -- JSON written by Muse, format in muse/COMPANY_RESEARCH.md
  error         TEXT,                  -- why muse-pull couldn't use the result
  added_at      TEXT NOT NULL,
  researched_at TEXT
);
CREATE INDEX IF NOT EXISTS company_research_by_status ON company_research (status, tier);
