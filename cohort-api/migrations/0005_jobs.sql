-- The job board's roles, one version per build (written by cohort-api/push_jobs.py after pipeline/build.py).
-- A push loads a new build next to the current one and only switches to it once everything is in, so a
-- failed upload never leaves the board half-empty. The board reads the newest complete build.

CREATE TABLE IF NOT EXISTS job_builds (
  build_id  TEXT PRIMARY KEY,
  generated TEXT,                       -- the build date pipeline/build.py stamped
  pushed_at TEXT NOT NULL,
  jobs      INTEGER NOT NULL,
  complete  INTEGER NOT NULL DEFAULT 0  -- 1 once every row of this build is in
);

CREATE TABLE IF NOT EXISTS jobs (
  build_id  TEXT NOT NULL,
  id        INTEGER NOT NULL,           -- the role's id within its build
  seq       INTEGER NOT NULL,           -- position in the build's list (the page keeps the build's order)
  company   TEXT NOT NULL,
  grp       TEXT,                       -- consulting | tech
  title     TEXT NOT NULL,
  category  TEXT,
  seniority TEXT,
  mba       TEXT,                       -- title | required | preferred | firm | NULL
  review    INTEGER,                    -- 1 = low-confidence match (hidden on the board)
  visa      TEXT,
  posted    TEXT,
  url       TEXT,
  data      TEXT NOT NULL,              -- the full role as the board's page uses it (JSON)
  PRIMARY KEY (build_id, id)
);
CREATE INDEX IF NOT EXISTS jobs_by_company ON jobs (build_id, company);

-- Everything else the page needs from a build (stats, "What's new" changes, ...), as JSON text.
-- Large values are split into parts to stay under D1's statement size limit; read them back in part order.
CREATE TABLE IF NOT EXISTS job_build_meta (
  build_id TEXT NOT NULL,
  key      TEXT NOT NULL,
  part     INTEGER NOT NULL,
  value    TEXT NOT NULL,
  PRIMARY KEY (build_id, key, part)
);
