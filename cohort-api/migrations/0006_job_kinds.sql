-- Two job sets, each with its own versions: "board" (Ryan's filtered build, site/data.js) and
-- "all" (every US posting, labelled by category and level: pipeline/expand.py -> data/all_jobs.json).
ALTER TABLE job_builds ADD COLUMN kind TEXT NOT NULL DEFAULT 'board';
