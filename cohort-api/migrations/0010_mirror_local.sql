-- Make the cloud copy a mirror of the local ingest database (linkedin-ingest/data/cohort.db) for everything about
-- classmates and their contacts: the same columns in people and positions, plus education and skills.
ALTER TABLE people ADD COLUMN first_name TEXT;
ALTER TABLE people ADD COLUMN last_name TEXT;
ALTER TABLE people ADD COLUMN headline TEXT;
ALTER TABLE people ADD COLUMN industry TEXT;
ALTER TABLE people ADD COLUMN geo_location TEXT;
ALTER TABLE people ADD COLUMN export_date TEXT;
ALTER TABLE positions ADD COLUMN company_raw TEXT;
CREATE TABLE IF NOT EXISTS education (
  person_id TEXT NOT NULL, school_raw TEXT, school_norm TEXT, degree TEXT, start_date TEXT, end_date TEXT
);
CREATE INDEX IF NOT EXISTS education_by_person ON education (person_id);
CREATE TABLE IF NOT EXISTS skills (person_id TEXT NOT NULL, skill TEXT);
CREATE INDEX IF NOT EXISTS skills_by_person ON skills (person_id);
