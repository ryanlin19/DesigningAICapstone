-- Contacts' names, titles and LinkedIn profile links, for the cohort's relationship graph (a private board for a
-- group of friends). Emails are never stored.
ALTER TABLE contacts ADD COLUMN full_name TEXT;
ALTER TABLE contacts ADD COLUMN position TEXT;
ALTER TABLE contacts ADD COLUMN profile_url TEXT;
