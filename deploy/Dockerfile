# The cohort board as a container. Built from the repo root (image_build_context ".." in wrangler.jsonc);
# the root .dockerignore keeps secrets, databases and big downloads out of the image.
FROM python:3.12-slim
WORKDIR /app
COPY cohort-board/ cohort-board/
COPY linkedin-ingest/ingest/ linkedin-ingest/ingest/
COPY linkedin-ingest/data/seed_companies.csv linkedin-ingest/data/seed_companies.csv
COPY cohort-api/sync.py cohort-api/sync.py
COPY pipeline/ pipeline/
COPY company-db/companies.py company-db/companies.py
COPY site/ site/
COPY data/skills.txt data/skills.txt
ENV PYTHONUNBUFFERED=1
EXPOSE 8765
CMD ["python3", "cohort-board/serve.py"]
