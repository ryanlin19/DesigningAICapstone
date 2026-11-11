# LinkedIn export ingestion

Loads classmates' LinkedIn data exports into `data/cohort.db` for the matching
piece. Python 3.9+, standard library only, nothing to install.

## Folder

```
ingest_cli.py            command-line entry point
ingest/
  pipeline.py            the end-to-end steps, AI and code labeled
  rules.py               deterministic normalization, title rules, candidate filter
  registry.py            company registry: the knowledge source, by retrieval
  ai_tasks.py            the only two model calls, with output validation
  llm.py                 minimal API client, logs latency, tokens and cost
  config.py              models, prices, job-function buckets
  db.py                  schema (plain SQL, ports to Postgres)
data/
  seed_companies.csv     seeded organizations and aliases
  cohort.db              database with the two exports loaded (deterministic run)
eval/
  golden_cases.json      20 cases, expected outputs, scoring rubric
  run_eval.py            run the 20 cases, write the team scoring sheet
  judge.py               cross-model judge on the AI-10, agreement rate
  econ.py                same 10 tasks on Haiku and Sonnet, cost per student
  out/results_rules.csv  measured rules-only baseline
tests/                   offline tests, no API key needed
REPORT.md                the milestone write-up, mapped to the rubric
```

## Load an export

```
python ingest_cli.py <export.zip> --person-id <id> --consent profile,connections            # no AI
python ingest_cli.py <export.zip> --person-id <id> --consent profile,connections --ai haiku # with AI
```

Running the same person again replaces their rows. After checking the result,
delete the original export: it contains messages, phone numbers and more that
this tool never reads. Ask classmates to export only Connections, Profile,
Positions, Education and Skills.

## Finish the milestone (about 1.5 hours plus scoring)

1. `python -m unittest -v` should show 9 tests passing.
2. Set your key: `export ANTHROPIC_API_KEY=...` (Windows: `set ANTHROPIC_API_KEY=...`).
3. Reload with AI so the database reflects the real pipeline:
   `rm data/cohort.db`, then run `ingest_cli.py` with `--ai haiku` on each export.
4. `python eval/run_eval.py --model haiku` and `python eval/run_eval.py --model sonnet`.
5. Team scoring: each teammate opens `eval/out/results_haiku.csv` and fills
   `team_score_a`, `_b`, `_c` with 1-5 using the rubric in `golden_cases.json`,
   without looking at each other's scores. Agree a final `team_score`. Do the
   same for the Sonnet file, at least for the 10 rows where `ai10` is True.
6. `python eval/judge.py --results eval/out/results_haiku.csv` (and the Sonnet
   file). It reports exact and within-one-point agreement with your team scores.
7. `python eval/econ.py --repeat 3` writes `eval/out/econ.md`.
8. Fill every **[run]** in `REPORT.md` from those outputs, update the top three
   failure patterns from the model runs, and write the trade-off sentence.

Expected API spend for all of the above: well under $5, mostly the Sonnet runs
and the Opus judge.

## Privacy rules built in

The model receives company names and job titles only. Connection names, emails,
profile links and individual titles are never stored. Profile addresses, birth
dates and phone numbers are never read. Only five files are opened from each
export. Tests check these guarantees.
