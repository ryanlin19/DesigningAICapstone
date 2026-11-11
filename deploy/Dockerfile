# The cohort board as a container. Built from the repo root (image_build_context ".." in wrangler.jsonc);
# the root .dockerignore keeps secrets, databases and big downloads out of the image. Those come from R2 at start
# (cohort-board/state.py) and the cohort database (cohort-api).
FROM python:3.12-slim
WORKDIR /app
COPY cohort-board/ cohort-board/
COPY linkedin-ingest/ingest/ linkedin-ingest/ingest/
COPY linkedin-ingest/data/seed_companies.csv linkedin-ingest/data/seed_companies.csv
COPY cohort-api/push_jobs.py cohort-api/sync.py cohort-api/
COPY pipeline/ pipeline/
COPY company-db/companies.py company-db/overrides.json company-db/
COPY site/ site/
# the job pipeline's inputs (firms, feeds found, history); big downloads and private files are left out by .dockerignore
COPY data/ data/
ENV PYTHONUNBUFFERED=1
EXPOSE 8765
CMD ["python3", "cohort-board/serve.py"]
