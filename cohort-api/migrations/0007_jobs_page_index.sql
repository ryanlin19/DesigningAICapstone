-- Paging through a jobs build (GET /v1/jobs?limit&offset) looks rows up by (build_id, seq). Without this index
-- every page scanned the whole jobs table (~51,000 rows read per 5,000-row page), which used up D1's free daily
-- read limit. With it, a page reads about as many rows as it returns.
CREATE INDEX IF NOT EXISTS jobs_by_seq ON jobs (build_id, seq);
