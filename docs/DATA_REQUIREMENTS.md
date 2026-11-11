# Cohort board: data requirements

Everything the board uses, field by field, so the data can be collected or recreated from scratch. Each section
says what is **required** (the board breaks or loses a feature without it) and what is **nice to have** (the board
gets better with it; collect it if you can). When in doubt, collect more: extra columns are ignored safely.

The board **derives** some things itself (categories, seniority, regions, scores); those are listed at the end so
they're not collected twice.

---

## General rules for every file

| Rule | Detail |
|---|---|
| Format | CSV, UTF-8, header row, standard quoting (a title with a comma is quoted: `"VP, Finance"`). JSON is fine for nested data. |
| Person key | The LinkedIn profile link, in the form `https://www.linkedin.com/in/<handle>/`. This is how one person is matched across files and months. Never omit it when a person has one. |
| Dates | ISO `YYYY-MM-DD` where the day is known; `YYYY-MM` or `YYYY` otherwise. Keep LinkedIn's own text (e.g. `Jun 2019`) in a separate column if converting. |
| Snapshots | Every row carries the date it was collected (`checked_on`). Keep old snapshots instead of overwriting: month-to-month changes are a feature. |
| Empty values | Leave blank. Don't write `N/A`, `-` or `unknown`. |
| Never needed | Email addresses, phone numbers, street addresses, messages. Don't collect them. |

---

## 1. Your connections (the people your cohort knows)

Today this comes from `Connections.csv` in each classmate's LinkedIn export: one row per connection.

### Required

| Field | Example | Used for |
|---|---|---|
| `profile_url` | `https://www.linkedin.com/in/jane-doe-1/` | Matching the same person across classmates and months; LinkedIn links on every page. |
| `first_name` | `Jane` | Names on company pages, who's-who map, shared connections. |
| `last_name` | `Doe` | Same. |
| `company` | `JPMorgan Chase` | Which company page, map region and job cards the person appears on. |
| `title` | `Vice President, Finance` | Function column and seniority row on the who's-who map; "Senior", "Recruiting" tags; ranking. |
| `connected_on` | `2019-03-01` | "Known since", ranking (older connections score higher). |
| `connected_to` | `peter-berzins` | Which classmate this connection belongs to (one file per classmate works too). |

### Nice to have (more is better)

| Field | Example | What it would add |
|---|---|---|
| `location_city` / `location_region` / `location_country` | `Seattle` / `Washington` / `United States` | The map's "People to know" by where people actually are, not where their company has offices. **Highest-value addition.** |
| `location_raw` | `Greater Seattle Area` | Keep LinkedIn's text as written; the board maps it to regions. |
| `headline` | `Product @ Stripe · ex-McKinsey` | Better role and seniority reading; search. |
| `current_role_start` | `2024-06` | "Changed jobs 2 months ago" signals; fresh movers are good outreach targets. |
| `company_linkedin_url` | `https://www.linkedin.com/company/jpmorganchase/` | Exact company matching (no name guessing). |
| `company_website` | `jpmorganchase.com` | Company matching. |
| `experience` (list) | company, title, location, start, end for every past role | "Worked at McKinsey before" paths; colleague detection; alumni of target companies. |
| `education` (list) | school, degree, field, start, end | Alumni ties (same school), MBA detection. |
| `skills` (list) | `SQL; Financial modeling` | Matching people to roles in your field. |
| `industry` | `Financial Services` | Vertical filtering when the company is unknown. |
| `open_to_work` / `hiring` flags | `true` | Highlight recruiters and hiring managers. |
| `followers` / `connections_count` | `500+` | Weak signal of reach. |
| `profile_photo_url` | — | Avatars on chips (optional; not needed). |
| `checked_on` | `2026-12-01` | Snapshot date (see general rules). |

---

## 2. Classmates (the people uploading)

Today this comes from each classmate's own export: `Profile.csv`, `Positions.csv`, `Education.csv`, `Skills.csv`,
plus their own profile link (typed in, or read from outgoing rows of `Invitations.csv`).

### Required

| File / field | Example | Used for |
|---|---|---|
| Profile: `first_name`, `last_name` | `Ryan`, `Lin` | Names everywhere ("Ask Ryan for an intro"). |
| Profile: `profile_url` | `https://www.linkedin.com/in/ryan-lin/` | Keeps classmates out of each other's "contacts"; detects classmates who are already connected. |
| Positions: `company`, `title`, `started_on`, `finished_on` | `McKinsey & Company`, `Summer Associate`, `2026-06`, `2026-08` | "Works here / worked here" (the strongest way in), colleague detection, ranking. Blank `finished_on` = current. |
| Positions: `location` | `New York, New York, United States` | Map: classmates based in / who've worked in a region. |

### Nice to have

| Field | What it would add |
|---|---|
| Profile: `headline`, `industry`, `geo_location` | Display; "based here" when no current job location. (Used when present.) |
| Positions: `description` | Better function detection for vague titles. |
| Education: `school`, `degree`, `start`, `end` | Alumni ties between classmates and contacts. (Read today, not yet used on pages.) |
| Skills: `name` | Resume-free "What you are" defaults. (Read today.) |
| Target roles / companies each classmate wants | Pre-filled "What you want"; "who else is aiming at Stripe". |

---

## 3. Companies (the directory)

Today: `data/companies.db`, built by `company-db/companies.py` from Wikidata, Wikipedia, the S&P 500 list,
research, and job postings.

### Required

| Field | Example | Used for |
|---|---|---|
| `name` | `JPMorgan Chase` | Company pages, cards, search. |
| `aliases` (list) | `JPMorganChase; J.P. Morgan; Chase` | Matching LinkedIn company names and job-feed names to one company. **Critical:** missing aliases split one company into several. |
| `vertical` + `sub_vertical` | `Financial Services` + `Commercial & retail banking` | Companies tab grouping; generic titles ("Associate") take the company's line of work. Allowed values: see `VERTICALS` in `company-db/companies.py`. |
| `hq_city`, `hq_region`, `hq_country` | `New York`, `New York`, `United States` | Company page; the map's regions. |
| `offices` (list of city, region, country) | `Chicago, Illinois; Columbus, Ohio` | The map's "Who's there". **More offices = better map.** |
| `description` | one or two sentences | Company pages and search. |

### Nice to have

| Field | What it would add |
|---|---|
| `website`, `linkedin_url` | Links; exact matching. |
| `employees` | Size shown on pages; sorting. |
| `ownership` (public / private / subsidiary / nonprofit), `ticker`, `parent` | Tags; rolling units up to their parent (e.g. Google → Alphabet). |
| `founded` | Display. |
| `careers_url` and the job system it uses (Greenhouse, Lever, Ashby, Workday, Oracle, own site) | Pulling that company's jobs automatically (big gap today: Apple, JPMorgan, Microsoft, Goldman…). |
| `office_size` per office (headcount or "HQ / major hub / small") | Rank offices; "the Seattle office is a major hub". |
| `source_url` per fact | Trust and later checks. |

---

## 4. Jobs (postings)

Today: `data/all_jobs.json` (every US posting, ~35,000) and `site/data.js` (Ryan's filtered board), built by
`pipeline/build.py` + `expand.py` from public company job feeds; full text in `data/descriptions.db`.

### Required

| Field | Example | Used for |
|---|---|---|
| `id` | stable per posting | De-duplication; links between pages. |
| `company` | `Stripe` | Matching to the company directory and cohort ties. |
| `title` | `Product Manager, Radar` | Category, level, fit, search. |
| `url` | the posting's apply page | Apply button. |
| `locations` (list of name + url) | `[{"name": "Seattle, WA", "url": "…"}]` | Map regions; Apply menu when each city has its own posting. |
| `remote` | `true` | "Remote / US-wide" region. |
| `posted` | `2026-11-02` | Timeline, Newest sort, freshness in ranking. |
| `description` (full text) | — | "Job description" toggle; skills, years, MBA and visa detection. |

### Nice to have

| Field | What it would add |
|---|---|
| `salary_min`, `salary_max`, `salary_currency`, `salary_period` | Pay shown and the "pay at least" filter (read from text today when present). |
| `min_years` | Fit ("asks 5+ yrs"); extracted from text today. |
| `department`, `employment_type` (full-time, intern, contract) | Better category and level. |
| `seniority` as the employer states it | Better level. |
| `deadline` | "Apply by" (Ryan's board has it for some roles). |
| `visa_sponsorship` statement | Sponsorship filter (detected from text today). |
| `recruiter` / `hiring_manager` name and profile link | Direct match to people your cohort knows. **High value.** |
| `closed_on` | Removing filled roles; "open for N days". |

---

## 5. You (the person using the board)

Kept in the browser and per login; listed for completeness.

| Field | Used for |
|---|---|
| Resume text (not stored) → years, MBA, fields, skills | "What you are"; fit buckets. |
| Target fields, levels, verticals, companies, things to avoid, pay floor | "What you want"; ranking and gaps. |
| Which classmate you are | "You" on pages; leaving yourself out of "ways in". |
| Visa preference, regions | Filters on every tab. |

---

## 6. What the board derives itself (don't collect)

- Contact fingerprint (matches people across exports; made from `profile_url` with the cohort's secret key).
- Role group of a contact (consulting, finance, recruiting, leadership, …) and the who's-who **function** and
  **seniority tier** (from title + company vertical).
- A job's **category**, **level**, skills, years asked, MBA and visa signals (from title + description).
- **Map regions** for any location text (`Greater Seattle Area` → Seattle area).
- Fit buckets, "Closer with" gaps, rankings ("Best ways in", shared connections, people to know).

---

## 7. Hand-off format for a monthly refresh of connections

If connection data is collected outside LinkedIn's export (by hand, a lookup service or another tool), one CSV per
run with these columns lets the board import it (importer to be built):

```
profile_url,first_name,last_name,company,title,location_raw,location_city,location_region,location_country,
current_role_start,headline,company_linkedin_url,connected_to,connected_on,checked_on
```

Optional extra files, joined on `profile_url`: `experience.csv` (profile_url, company, title, location, start, end),
`education.csv` (profile_url, school, degree, field, start, end), `skills.csv` (profile_url, skill).
