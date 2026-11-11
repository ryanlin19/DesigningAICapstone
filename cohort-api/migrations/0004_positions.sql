-- Classmates' own work history (from their Positions.csv, shared with consent), for the
-- "Classmate worked here" tag: a classmate who worked at a company is the warmest route in.
CREATE TABLE IF NOT EXISTS positions (
  person_id    TEXT NOT NULL,
  company_norm TEXT NOT NULL,
  title        TEXT,
  title_bucket TEXT,
  started_on   TEXT,
  finished_on  TEXT,
  is_current   INTEGER
);
CREATE INDEX IF NOT EXISTS positions_by_company ON positions (company_norm);
