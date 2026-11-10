# MBA Job Board

A static job board of roles for MBA students (consulting, strategy, ops and similar), with visa signals. No server needed:
open `site/index.html` in a browser (double-click it) after building.

**Live site:** your own Cloudflare address once you deploy (public folder only).

**This folder is the master copy** (moved here from a temporary workspace on 2026-10-22). It deliberately leaves out the
big download cache (`data/raw_fetch.json`, ~170 MB), so the first build here must download everything once
(`python pipeline/build.py`, about an hour); after that `--cached` works again.

## Two versions: private and public

The firm database says **do not share publicly**, so every build writes two versions:

| Folder | Contains | Share it? |
|---|---|---|
| `site/` | Roles only (the Firm directory was removed 2026-11-09); the visa reasons spell out the firm's stated policy | **No.** Local use only. |
| `public/` | **Job listings only.** The visa *label* (Likely / Possible / Unknown / Unlikely) is informed by the firm database, but the page never names it or shows its fields; reasons are public-source evidence or generic wording | Yes. This is the folder to upload. |

Note: because the label uses the database, a firm's stance can be roughly inferred from its labels. If the sheet's owner
objects, set the stance to `None` in `build.py` (the `visa_label(tags, stance)` call) and rebuild.

Before uploading, always run the guard. It fails if anything from the firm database is in `public/`:

```
python pipeline/check_public.py
```

## Publish (Cloudflare)

The public folder is deployed as the Cloudflare site `job-board` (config in `wrangler.jsonc`). To publish a refresh:

```
python pipeline/build.py            # or --cached to reuse the last download
python pipeline/check_public.py     # must print OK
npx wrangler deploy                 # uploads public/ to the same site
```

Node.js and Wrangler are installed; log in once with `npx wrangler login`. Never upload `site/` (its visa reasons spell out each firm's stated policy).

## Refresh the data

```
python pipeline/clean_firms.py     # only when the firm database CSV changes
python pipeline/build.py           # refetch jobs, reclassify, rewrite site/data.js (~1 hour)
python pipeline/build.py --reprobe # also rediscover every company's job-board name (longer)
python pipeline/build.py --cached  # rebuild from the last download (seconds); use after changing rules or the page
```

Firms that use their own job system (Kearney, Accenture, Guidehouse, Protiviti, Huron, Booz Allen, BCG, Deloitte, EY and
EY-Parthenon, KPMG, Simon-Kucher, Cartesian) are listed in `data/custom_boards.json`. Each line names a reader
(`workday`, `recsolu`, `pinpoint`, `phenom`, `sfhtml`, `avature`, `csod`, `kpmg`, `talnet`, all in `pipeline/ats.py`); `exclude` drops
titles (tax, audit...) and `split` credits part of a feed to a sub-brand. To try a firm on its own, run
`python pipeline/probe_firm.py "EY"`.

On this machine Python lives at `%LOCALAPPDATA%\Programs\Python\Python312\python.exe`.

## What feeds it

| Input | Where | Notes |
|---|---|---|
| Consulting firm database | Job Tracker folder (CSV), read-only | 169 firms: visa stance, offices, industries, functions |
| Companies to scan | `data/seed_companies.txt` | One per line. **Add companies here to grow the board.** |
| Wrong board matches | `data/board_overrides.json` | `"Company": null` excludes a bad match |

USCIS H-1B filing history is **no longer used** (decided 2026-10-23: the FY2021-23 data predates the 2025-26 rule and fee
changes). `pipeline/archive/h1b.py` and the `h1b_datahubexport-*.csv` files in the Job Tracker folder are kept but unused.

## Visa labels

Likely / Case-by-case / Unlikely / Unknown, from: what the posting says (sponsors, does not sponsor, offers immigration
support, needs a clearance or citizenship) and the firm database's stated stance (consulting firms only). "Immigration
support" wording is a soft signal and only ever gives Case-by-case. Tech companies are mostly "Unknown" unless the posting
says something. Tests: `pipeline/test_visa_signals.py` (or all tests: `python pipeline/run_tests.py`).

## Files

What builds the board:

- `pipeline/build.py` - ties it together, writes `site/data.js`, `public/` and `data/build_report.txt`; the board's rules are near the top
- `pipeline/ats.py` - Greenhouse / Lever / Ashby public job feeds, plus the readers for firms with their own job system
- `pipeline/classify.py` - role category, seniority, location, MBA and sponsorship-language rules
- `pipeline/places.py` - turns messy location strings into the places in the Location filter
- `pipeline/deadline.py` - application deadlines
- `pipeline/salary.py` - pay ranges stated in the posting text
- `site/index.html` - the page (filters, What's new, My list); `build.py` makes the public copy from it

Running and checking it:

- `pipeline/refresh.py` - download, rebuild, check and deploy in one go (`refresh_daily.bat` runs it)
- `pipeline/check_public.py` - the leak check; must print OK before any upload
- `pipeline/check_links_safari.py` - apply-link certificate check
- `pipeline/run_tests.py` - runs every `test_*.py` (visa wording, MBA tag, places, deadlines, pay and years)
- `pipeline/probe_firm.py`, `pipeline/refetch_firms.py` - try one firm's reader / re-download named firms for a `--cached` build
- `pipeline/clean_firms.py` - turns the firm database CSV into `data/firms.json`
- `pipeline/coverage.py` - which database firms have live roles on the board

`pipeline/archive/` holds one-off scripts from building the board (see its README); nothing above uses them.

## Known limits

- Only companies on Greenhouse, Lever or Ashby (plus the few firms in `data/custom_boards.json`) appear as live roles. MBB,
  Big 4 and most large consultancies post elsewhere, so they appear as "see careers page" cards instead.
- Visa labels are a guide. Always confirm with the employer.
- "Vice President" titles are excluded as too senior, except at AlixPartners where the rung is about a senior associate
  (`VP_FIRMS` in `pipeline/build.py`; senior/executive VPs and forensic, compliance and e-discovery VPs stay out).
- Classification is rules-based; borderline titles (low-confidence matches) are left out of the board.

## Future to-dos (not started)

- **Search caps at Workday firms (next, after the Nov 2 deploy; decided 2026-11-02).** Several readers stop before the end of
  some searches, so each download sees a different slice and counts swing while postings are still open (EY had this and was fixed
  on Nov 2 with one full search). Results against the limit (`max_per_term` in `data/custom_boards.json`):
  - Booz Allen: up to 1,874 against 200.
  - Guidehouse: up to 690 against 200.
  - HP: up to 376 against 100.
  - Huron: up to 259 against 200.
  - Accenture: its searches return worldwide results, each reporting 2,000 (Workday's maximum), so it needs a US-only filter,
    not just a higher limit.

  Raising a limit makes the download longer. After a fix, correct that firm's entries in `data/history.json` the way EY's were
  (see STATUS.md), or its newly visible older postings show up as "new" in the next download.

- **Replace the visa signal for tech companies with recent Department of Labor filings (on hold, decided 2026-10-23).**
  USCIS history was dropped because FY2021-23 predates the 2025-26 rule and fee changes, so most tech roles are now
  "Unknown". The DOL's public LCA disclosure data runs through FY2026 Q3 (Oct 2025 - Jun 2026; Q4 expected Nov 2026 -
  Feb 2027) and would show which employers have filed H-1B applications since the changes. It needs a large file download
  (ask first), and an LCA shows intent to hire, not an approval. See https://www.dol.gov/agencies/eta/foreign-labor/performance
- **Automatic daily refresh and redeploy** (the site only updates when someone rebuilds and runs `npx wrangler deploy`).
- **Old "posted" dates:** some Greenhouse postings report a first-published date years old (a role showed "60 months ago").
- **Firms not read automatically:** McKinsey and Bain (their job lists load behind scripts; Bain's job API answers
  "Direct API access is not allowed") appear as two hand-typed standing roles in `data/standing_roles.json`; re-check
  them by eye now and then and update `checked`. Alvarez & Marsal shows a bot-check page, and PwC / Strategy& and TCS
  have no US list a script can read. This project does not work around any of that. Check those directly.

## Open review notes

- **BCG manager roles (noted 2026-10-23):** some BCG "Manager" roles (mostly BCG Vantage and BCG Platinion) probably should not be on the board. Not changed yet; the likely fix is an `exclude` pattern on the BCG line in `data/custom_boards.json`.

## Newer hiring-policy news

`data/stance_overrides.json` holds visa-stance changes that are newer than the firm database (currently PwC and Strategy&: permanent work authorization now required for full-time roles). It feeds the visa label only and is never shown on the board.

## To-do: firms that still need an automatic job feed

Done 2026-10-23: **Insero** (job list embedded in its Zoho page), **ECG Management Consultants** (Jibe feed), **Alexander Group** (plain-text openings page), **Capgemini**
(public job-search API). The rest show on the board as "see careers page" cards. Only pages and feeds a normal visitor can
use are read; never work around a bot check or an "API access not allowed" message.

- **Alvarez & Marsal:** careers.alvarezandmarsal.com shows a bot-check page to scripts. Do not work around it.
- **Kroll** (TalentBrew) and **DHL Consulting:** their careers sites refuse script requests (HTTP 403). Do not work around it.
- **TCS (US):** jobs are in the iBegin portal (ibegin.tcsapps.com), a login-style JavaScript app with no public list.
- **Wipfli:** careers.wipfli.com searches a shared multi-client index (/api/appSearch) and the filters that pick out Wipfli's own postings are not visible without the page's own requests; most roles are audit and tax. Left as a careers-page card.
- **StoneTurn:** ADP feed works (cid in their careers page) but currently lists a single non-consulting job.
- **McKinsey and Bain:** only hand-typed standing roles; both load jobs by script (Bain's API refuses scripts).
- Revisit **Gallup, Baringa and similar** if their counts look low after a refresh.

## Daily refresh (script)

`refresh_daily.bat` (or `python pipeline/refresh.py`) downloads every feed, rebuilds, runs the leak check and deploys to
Cloudflare, about an hour (most of it is the download). It uses no AI tokens. The live site is only touched when all checks pass: the leak check
prints OK, the role count is at least 75% of the last build, and no firm that had 15 or more roles lost more than 60% of them.
If a check fails, the previous `public/` is put back and nothing is deployed. Each run writes `logs/refresh-DATE.txt`
(status, role counts, the biggest changes). `python pipeline/refresh.py --no-deploy` does everything except deploy.

To run it every morning, create the Windows scheduled task (the computer must be on and signed in):

    schtasks /Create /SC DAILY /ST 06:30 /TN "Job Board Refresh" /TR "\"<path to this folder>\refresh_daily.bat\""

Remove it with `schtasks /Delete /TN "Job Board Refresh" /F`. Hand-typed roles in `data/standing_roles.json` are not
refreshed by the script; check them by eye now and then.

## Link check for Safari and other browsers

`python pipeline/check_links_safari.py` opens a sample of apply links with a Safari user agent and checks every host's secure
connection and certificate against what Safari requires (TLS 1.2 or newer, forward secrecy, a valid and unexpired certificate,
the 398-day limit). It cannot launch Safari itself. Run it after a refresh. If a host's certificate is broken, add a replacement
host to `LINK_HOST_FIXES` in `pipeline/build.py` (West Monroe's bare domain needed this on 2026-10-26).

## "What's new" tab

Each full download (`build.py` without `--cached`, so also every `refresh.py` run) compares its posting links with the previous
download and records the result in `data/history.json`: postings whose link was not there before are "new", and previously listed
roles whose links are gone from the firms' pages are "no longer listed". Because it compares links in the firms' raw lists (not our
filtered board), changes caused by our own rule changes are not reported. Every update since `CHANGES_SINCE` in `build.py`
(Oct 23) is shipped in `data.js` as `changes`, and the page combines them into one comparison with that update. Roles that appeared
later and are gone again, or dropped off and came back, count as no change. Removed roles keep their links (since Oct 30) so this
netting works. Move `CHANGES_SINCE` forward to start a fresh comparison. Hand-typed standing roles (`data/standing_roles.json`,
McKinsey and Bain) are never reported as new or gone. `pipeline/archive/seed_history.py` started the file once (do not run it again) (baseline Oct 27, first update Oct 23 to Oct 27). A `--cached` build never
changes the history.

## VC portfolio companies (added 2026-11-09)

The seed list (`data/seed_companies.txt`) now ends with a section of venture-backed companies taken from the portfolios of
General Catalyst, Oak HC/FT, USV and IVP. Company names came from each firm's public sitemap or portfolio page. Each name was
tried against Greenhouse, Lever and Ashby, and only companies with a readable feed that also named the company in its
postings were kept (317 of 935). Jobs are read from the company's own job page, never from the VC's job aggregator, so apply
links go to the company. The same title filters apply, so engineering roles stay out.

Second round (2026-11-09): the same method was run on the portfolios of a16z, Lightspeed, Index, Khosla, Greylock, Upfront, Accel,
Sequoia, Bessemer and NEA (company names from their public sitemaps or portfolio pages). Of about 3,500 new names, 779 had a
readable feed that named the company in its postings, and about 200 roles passed the filters. A few generic names matched the
wrong company ("Pulse", "Remote", "Agency") and were left out by hand.

Not done: GV (its site exposes no company list), and companies whose feed exists but was empty on 2026-11-09. Companies on other
job systems (Workday, Lever sub-sites, custom pages) are not covered by this method.

## Role types added 2026-11-09

On request, the title filters now also keep product management, business development, partnerships, growth, general management and
account executive roles (`CATEGORIES` and `EXCLUDE` in `pipeline/classify.py`; tests in `pipeline/test_new_roles.py`). Still left out:
director, VP, head of, principal and staff titles; business development / sales development *representatives*; analysts; and
account managers. Technical product managers and growth marketing were added on 2026-11-09. Account executive postings that differ only
by territory, state, country or language are folded into one role with several locations (`fold_ae_title` in `pipeline/build.py`). At firms read through a custom feed (Workday, Avature, KPMG and so on) the
download only opens titles the filters accepted at the time, so the new role types appear there after the next full download.

The Role type filter starts with **Account Executive unticked** (about a third of the board; user decision 2026-11-09). Visitors can tick it, and
the "Role type: 13 of 14 shown" tag above the results restores it. The default lives in `initFilters()` in `site/index.html`.

## Big tech companies (added 2026-11-09)

Read through their own job systems (`data/custom_boards.json`, group `tech`, US postings only):
Nvidia, Salesforce, Adobe, Intel and Cisco use Workday; AMD uses the iCIMS Jibe reader. About 120 roles pass the filters.
Meta, Tesla, Qualcomm, Intuit and IBM only get "see careers page" cards (`DIRECT` in `site/index.html`): Meta and Tesla block automated
reading, and Qualcomm, Intuit and IBM use systems the board has no reader for.

Not done yet: Amazon, Google, Microsoft, Apple, Uber and Netflix. Each needs its own reader and a check of the site's terms.
Workday searches stop at `max_per_term` (300 here), so a big firm's list can be partial; Intel returned very few roles for that reason or because
few of its postings match.

The resume panel and My list share one **Profile & My list** tab: "Your resume fit" on top, "My list" below it (the tab's number counts saved roles).
The role tabs show a one-line pointer to it, and "See my best matches" jumps to the role list sorted by fit. An old remembered "My list" tab opens this one.
