# Cohort Job Board: how it works (for an agent planning work on it)

## What it is
A private job board for a small group of MBA friends. It combines job postings with the group's LinkedIn networks
to answer: which jobs fit me, which companies can my friends get me into, and who exactly should I ask.
Repo: `github.com/ryanlin19/DesigningAICapstone`, branch `peter_stuff` (Peter's). `main` and the public site
(`job-board` Worker, `public/` folder) belong to Ryan: don't change or deploy them.

## The pieces
| Folder | What it does |
|---|---|
| `pipeline/` | Downloads public job postings from company job feeds (Greenhouse, Lever, Ashby, Workday, ...), labels each with category, level, visa and MBA signals. Outputs `data/all_jobs.json` (~35,000 US jobs), `site/data.js`, `data/descriptions.db` (full text). |
| `linkedin-ingest/` | Reads a LinkedIn data-export zip (Connections, Profile, Positions, Education, Skills). Stores classmates, their jobs (with locations) and their contacts (name, title, company, profile link, year connected) in `linkedin-ingest/data/cohort.db` (SQLite). Contacts are matched across classmates by a keyed fingerprint of their profile link. |
| `company-db/` | The company directory `data/companies.db`: ~1,650 companies (classmates' connections + S&P 500) with vertical, description, HQ, offices, size. Built from Wikidata, Wikipedia and research. |
| `cohort-board/` | The web app (Python standard library only, `serve.py`). Tabs: Find a job, Map, Companies (each company has a who's-who map of people the cohort knows), Cohort (classmates you're not connected to; people most of the cohort knows that you don't). |
| `cohort-api/` | Optional Cloudflare D1 copy of the data (older setup). |
| `deploy/` | Hosting on any Cloudflare account: one container running the app, files kept in R2. See `deploy/DEPLOY.md`. |

## How data flows
1. Job pipeline (monthly or on demand) → job files → board.
2. A classmate uploads their LinkedIn zip on the board → ingest → `cohort.db` → every page updates.
3. Company directory rebuilt occasionally → `companies.db` → Companies tab and map.
Everything derived (fit, categories, seniority, map regions, rankings) is computed by the board.

## Data the board uses
Full field list with examples: `docs/DATA_REQUIREMENTS.md`. In short:
- **Contacts:** profile link (the key), name, current company, title, date connected, which classmate.
- **Classmates:** name, profile link, every job (company, title, dates, location), education, skills.
- **Companies:** name + every alias, vertical, HQ, office cities, description, size, website.
- **Jobs:** company, title, apply link per location, remote flag, posted date, full description, salary.

## Biggest gaps (where help is most useful)
1. **Contacts' current city.** LinkedIn exports don't include it; the map guesses from company offices.
2. **Fresh contact data between uploads.** Job changes only show when someone uploads a new export.
3. **Jobs at big employers** without a supported feed (Apple, JPMorgan, Microsoft, Goldman, Meta, ...).
4. **Company offices and aliases.** Many companies have only an HQ; missing aliases split one company into several.
5. **Labels.** Many titles land in "Other" for job category or contact function; an AI pass could classify them.

## How to hand data back
CSV, UTF-8, LinkedIn profile link as the person key, a `checked_on` date per row. The contact-refresh format and
optional experience, education and skills files are specified in `docs/DATA_REQUIREMENTS.md` (section 7). The
importer for that file isn't built yet; jobs and companies go in through the existing builders.

## Constraints
- Private data: never commit `cohort.db`, `companies.db`, `.password`, `.api`, `.contact_key`, or anything with
  classmates' contacts. Never publish the board publicly.
- No emails, phone numbers or messages are wanted.
- LinkedIn's User Agreement prohibits bots and automated access to its site; automated profile visits risk the
  account being restricted. Prefer the official data export, people-data services, or manual entry.
- Work on branch `peter_stuff` only; commits only when Peter asks.
