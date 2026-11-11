# Milestone 2: LinkedIn export ingestion

Component of the Cohort Job and Intro Matcher. It loads classmates' LinkedIn data
exports into the shared database that the matching and intro piece reads.

Numbers marked **[run]** come from `eval/run_eval.py`, `eval/judge.py` and
`eval/econ.py` with an API key. Everything else below was measured on real inputs.

## 1. What it does, end to end

Input: a LinkedIn data export (the zip LinkedIn emails you) and the person's
consent scopes. Output: rows in `data/cohort.db`.

```
python ingest_cli.py Basic_LinkedInDataExport_11-09-2026.zip --person-id <id> --consent profile,connections --ai haiku
```

Real run, two classmates' exports, deterministic mode:

| | Export A | Export B |
|---|---|---|
| Files in the export | 23 | 37 |
| Files opened | 5 | 5 |
| Connections read | 112 | 1,086 |
| Companies after normalization | 86 | 653 |
| Matched the registry exactly | 5 | 42 |
| New with no plausible match | 75 | 530 |
| Needed a judgment (sent to AI) | 7 | 88 |
| Distinct title-company pairs the rules could not place | 21 | 278 |

The database now holds 2 profiles, 14 positions, 5 schools, 12 skills, 739
derived connection rows and a registry of 734 organizations. It holds no
connection's name, email, profile URL or individual title, and none of the
messages, phone numbers, addresses or job applications that were in the exports.

We ingest exports that people choose to hand over rather than scraping profiles.
Scraping breaks LinkedIn's terms and would load data about people who never
agreed to it; the export is also cleaner, structured data.

## 2. AI only where judgment is needed

| Step | How | Why |
|---|---|---|
| Open export, read only 5 allowed files | Code | A whitelist is a rule, not a judgment. |
| Consent check | Code | Must never be skipped or interpreted. |
| Parse profile, positions, education, skills | Code | Fixed CSV formats. |
| Drop names, emails, URLs from connections | Code | Privacy guarantee has to be exact. |
| Normalize company names (case, punctuation, Inc/LLC/L.P.) | Code | Mechanical. |
| Exact, alias and spacing-insensitive registry lookup | Code | "JPMorgan Chase & Co." and "jpmorganchase" are the same string problem. |
| Retrieve candidate matches from the registry | Code | Cheap recall filter: shared distinctive word, prefix/suffix, letter overlap. |
| **Decide same / subsidiary / different** | **AI** | Needs world knowledge: KPMG US is KPMG, Goldman Sachs Ayco is a Goldman unit, Hamilton Recruitment is not Booz Allen Hamilton. |
| Title rules (17 buckets) | Code | 70% of real titles (808 of 1,147) placed by rules. |
| **Bucket titles the rules can't place** | **AI** | "Associate" is finance at Goldman and consulting at McKinsey; needs the company as context. |
| Aggregate to company counts, write DB | Code | Arithmetic. |

The model sees only company names and job titles, never a person's name. Its
output is validated in code: a bucket must be one of the 17, and a "match" must be
one of the candidates retrieval supplied, so it cannot invent a company. Bad output
gets one retry, then goes to a review queue. Answers are cached, so a title or
company is judged once for the whole cohort.

On export B, AI is needed for 88 of 653 companies (13%) and for 278 distinct
title-and-company pairs, sent as 14 batches of 20. Every other step is deterministic and tested.

## 3. Knowledge source: company registry, by retrieval

The knowledge source is the company registry (`companies` and `aliases` tables):
34 seeded organizations with known aliases (target employers, banks, consultancies,
big tech, Cornell units), plus every organization seen in any export, now 734. When
a new name has no exact match, code retrieves at most 5 registry entries that could
be the same organization, and only those go into the prompt.

We chose retrieval rather than putting the registry in context because it grows
with every classmate: about 650 organizations per large export, likely several
thousand for a 50-person cohort. Putting all of it in every prompt would multiply
cost by roughly 100 and make the model's job harder, since the right answer would
be one line among thousands. Each decision only needs the handful of plausible
candidates, and the code that retrieves them is deterministic and testable. The
job-function definitions, by contrast, are 17 short lines that every title call
needs, so they live in the prompt as context.

## 4. Eval pack

20 golden cases in `eval/golden_cases.json`: 2 end-to-end runs, 10 company
resolutions, 8 title classifications. Eight test the rules, twelve need judgment,
and ten of those twelve form the "AI-10" used for the judge and the tier
comparison. Seven inputs are real names from the exports; the rest are realistic
constructions.

| ID | Input | Expected | Path | AI-10 |
|---|---|---|---|---|
| E1 | Synthetic export with look-alike traps | correct counts, traps separate, no personal data | rules | |
| E2 | Export with no connections file, plus messages | profile loaded, messages unopened, no crash | rules | |
| C1 | JPMorgan Chase & Co. | same as jpmorganchase | rules | |
| C2 | Facebook | same as meta | rules | |
| C3 | Scaleway | new (not Scale AI) | rules | |
| C4 | KPMG US | same as kpmg | AI | yes |
| C5 | Goldman Sachs Ayco | subsidiary of goldman sachs | AI | yes |
| C6 | Barclays Investment Bank | subsidiary of barclays | AI | |
| C7 | Huron Consulting Group | same as huron (not BCG) | AI | yes |
| C8 | Hamilton Recruitment | different from Booz Allen Hamilton | AI | yes |
| C9 | Cornell FinTech Club | different from Cornell University | AI | yes |
| C10 | Astera Holdings | different from Solera Holdings | AI | |
| T1 | Associate @ Goldman Sachs | finance | AI | yes |
| T2 | Associate @ McKinsey | consulting | AI | yes |
| T3 | Engagement Manager @ McKinsey | consulting | AI | yes |
| T4 | Member of Technical Staff @ Anthropic | engineering | AI | yes |
| T5 | Principal @ Crestview Partners | finance | AI | yes |
| T6 | Summer Associate Law Clerk @ Latham & Watkins | legal | rules | |
| T7 | Medical Doctor @ Northwell Health | healthcare | rules | |
| T8 | Director of Engineering @ ServiceNow | engineering | rules | |

**Scoring rubric (team and judge use the same one):** 5 exact; 4 an accepted
alternative; 3 partly right (right company, same/subsidiary swapped, or a
neighboring bucket); 2 unhelpful but harmless (left as "other" or unmatched);
1 harmful (wrong merge, or a bucket that would misroute an intro).

**Team scores:** each teammate fills `team_score_a/b/c` in
`eval/out/results_<model>.csv`; `team_score` is the agreed final. **[run]**

**Cross-model judge:** Claude Opus 5.5 scores the AI-10, using the rubric,
for the Haiku and Sonnet runs, so the judge is never the model being judged.
Agreement with team scores: exact **[run]**, within one point **[run]**.

**Measured baseline, rules only (no AI):**

| | Mean score | Scored 4+ |
|---|---|---|
| 8 rules cases | 5.00 | 8/8 |
| 12 judgment cases | 2.75 | 3/12 |
| All 20 | 3.65 | 11/20 |

Rules never made a harmful error. They only failed safe: five titles left as
"other" and four real merges missed. The three "different" company cases pass
without AI because the safe default is "new company".

**Top three failure patterns** (rules baseline now; update from the model runs **[run]**):

1. Generic titles need company context (T1 to T5). "Associate", "Principal" and
   "Engagement Manager" carry no function on their own. 30% of real titles (339 of 1,147) fell through
   the rules, most of them generic titles like these.
2. Missed merges of related organizations (C4 to C7). Regional member firms,
   divisions and subsidiaries look like new companies to string rules, which
   splits one employer's contacts across several rows.
3. String similarity is misleading. Boston Consulting Group scores 0.84 against
   Huron Consulting Group but Goldman Sachs Ayco scores lower against Goldman
   Sachs. We use similarity only to *retrieve* candidates and never to merge, which
   is why retrieval noise costs money but never causes a wrong merge.

Watch for in the model runs: false merges on shared-word pairs (C8, C9, C10), and
same/subsidiary swaps (C5, C6).

## 5. Unit economics

Same AI-10 tasks on Claude Haiku 5.5 and Claude Sonnet 5.5, 3 repeats each.
Prices: Haiku $0.10 / $0.50, Sonnet $2 / $10 per million input / output tokens.

| Tier | Median latency per task | p90 latency | Cost per 100 runs | Mean score | Scored 4+ |
|---|---|---|---|---|---|
| Haiku 5.5 | **[run]** | **[run]** | **[run]** | **[run]** | **[run]** |
| Sonnet 5.5 | **[run]** | **[run]** | **[run]** | **[run]** | **[run]** |

Projected AI cost to ingest one student, from the real step counts above
(`eval/out/econ.md` fills this in):

| Export | Connections | Company calls | Title batches | Haiku | Sonnet |
|---|---|---|---|---|---|
| A | 112 | 7 | 2 | **[run]** | **[run]** |
| B | 1,086 | 88 | 14 | **[run]** | **[run]** |

**Trade-off we accept:** **[after the run]** Default plan: run Haiku in the
pipeline. Ingestion is a one-time batch per student, and every AI answer is
validated, cached and fails safe. So a cheaper model's occasional miss costs a
missed merge, not a wrong intro. Switch the company step to Sonnet only if Haiku
makes a harmful (score 1) merge on the golden set. At Sonnet's price that is
still cents per student.

## 6. Economic value

The product turns a cohort's scattered LinkedIn networks into a map of who can
open which door, so a job seeker gets a warm introduction instead of a cold
application. This component is the part that makes that map possible: without
it, someone does what Claude did manually in the original session, reading
exports and reconciling company names by hand, which took a long working session
for one student and ten companies.

Value per student = (hours saved finding a contact) × (value of a student's
hour) + (lift in interview odds from a referral) × (value of an earlier offer).
Cost per student = AI ingestion cost **[run]** + matching and drafting cost
(teammate's piece) + hosting. The cost side is measured in section 5; the
benefit side rests on two assumptions the pilot has to test, the hours saved and
the referral lift. Because ingestion is a few cents or less per student and runs
once, the whole cost is dominated by the downstream steps, and the economics
hinge on whether intros actually get sent (PRD Gate 3).

Scaling helps: the registry and title cache are shared, so each new classmate
costs less than the last, because many of their companies and titles were already
judged.

## 7. Contract for the matching piece

Read from `data/cohort.db` (plain SQL, ports to Postgres):
`people` (consent scopes and timestamp), `positions` (with `company_norm` and
`title_bucket`, for "classmate worked there"), `education`, `skills`,
`derived_connections (connector_id, company_norm, count, top_title_bucket,
snapshot_date)`, and `companies` (use `parent_norm` to count a subsidiary's
contacts toward its parent). `review_queue` lists company matches waiting for a
human or AI decision.
