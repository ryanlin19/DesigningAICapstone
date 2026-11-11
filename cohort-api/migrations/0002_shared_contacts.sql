-- Deep connections: contacts known by two or more classmates.
-- Same definition as SHARED_CONTACTS_VIEW in linkedin-ingest/ingest/db.py; change both together.

ALTER TABLE contacts ADD COLUMN connected_year INTEGER;   -- year the classmate connected with them
ALTER TABLE people ADD COLUMN self_key TEXT;               -- the classmate's own contact key

-- Company and job type come from the newest export that has the contact (they may have changed jobs).
-- Left out: classmates themselves, and students and school staff, who would otherwise dominate.
CREATE VIEW shared_contacts AS
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
