# Company research brief (for research agents)

You are filling in a company directory for a private MBA cohort job board. You get one batch file of companies
and write one result file. Accuracy matters more than coverage: leave a field empty rather than guess.

## Input
`data/company-db/batches/batch_NN.json`: a list of companies. Each has:
- `id` (copy it unchanged), `name`, `linkedin_names` (how classmates' LinkedIn exports spell it)
- `sp500`, `gics` ([sector, sub-industry]) and `sp500_hq` when it's an S&P 500 company
- `wikidata_guess`: an automatic match. **It can be wrong** (e.g. "Ankura" matched a primary school). Check it.
- `offices_seen_in_our_job_postings`: US metro areas where the company currently posts jobs (reliable)

## Output
Write `data/company-db/research/batch_NN.json` (same NN) with a JSON list, one object per input company,
in input order. Write it with the Write tool. Do not edit any other file. Do not run git.

```json
{
  "id": "mckinsey-company",
  "name": "McKinsey & Company",
  "kind": "employer",
  "wikidata_id": "Q310207",
  "vertical": "Consulting",
  "sub_vertical": "Strategy consulting",
  "short_description": "Global management consulting firm",
  "description": "Global management consulting firm that advises companies, governments and nonprofits on strategy, operations and organization.",
  "website": "https://www.mckinsey.com",
  "hq": {"city": "New York", "region": "New York", "country": "United States"},
  "ownership": "private",
  "ticker": null,
  "parent": null,
  "employees": 45000,
  "us_offices": [
    {"city": "Chicago", "region": "Illinois", "source_url": "https://www.mckinsey.com/us/our-offices"}
  ],
  "sources": ["https://www.mckinsey.com/about-us/overview"],
  "confidence": "high",
  "notes": null
}
```

Field rules:
- `name`: the common English name of the company (e.g. "PwC", "JPMorgan Chase", "Meta"), not a legal suffix soup.
- `kind`: one of `employer`, `school` (universities, business schools), `recruiter` (staffing / executive search firms),
  `student_org` (clubs, student-run funds, campus programs), `not_a_company` (events, generic words, unidentifiable).
  For anything other than `employer`, fill only id, name, kind, vertical/sub_vertical if obvious, short_description, notes.
- `wikidata_id`: the correct Wikidata item (Q-number) for the company, or `null` if there is none or you can't tell.
  Keep the guess if it's right; replace it if wrong (you can check https://www.wikidata.org/wiki/Special:Search).
  If the LinkedIn name is ambiguous (e.g. "Climate", "Huron", "Grist"), use the context: these are MBA students'
  connections (consulting, finance, tech, agriculture...). Say how you decided in `notes`.
- `vertical` and `sub_vertical`: **must be exactly one pair from this list**:
  - Consulting: Strategy consulting · Management & operations consulting · Big Four & accounting · Economic & litigation consulting · Technology consulting · Restructuring & turnaround · Other consulting
  - Financial Services: Investment banking · Commercial & retail banking · Private equity · Venture capital · Hedge funds & asset management · Insurance · Fintech & payments · Exchanges & financial data · Real estate investment · Other financial services
  - Technology: Big tech · Software & SaaS · AI · Semiconductors & hardware · Internet & marketplaces · Cybersecurity · IT services · Other technology
  - Consumer & Retail: Consumer packaged goods · Retail & e-commerce · Restaurants & hospitality · Apparel & luxury · Beverages · Other consumer
  - Healthcare & Life Sciences: Pharma & biotech · Medical devices · Healthcare providers · Health insurance & services · Digital health
  - Industrials & Manufacturing: Aerospace & defense · Industrial machinery · Chemicals & materials · Construction & engineering · Automotive · Other industrials
  - Energy & Climate: Oil & gas · Utilities & power · Renewables & climate tech · Other energy
  - Agriculture & Food: Agribusiness & ag tech · Food production · Other agriculture
  - Media, Entertainment & Telecom: Media & publishing · Entertainment & gaming · Telecommunications · Advertising & marketing
  - Transportation & Logistics: Airlines · Ride-hailing & mobility · Logistics & shipping · Other transportation
  - Real Estate: Real estate development & services · Proptech
  - Education: Universities & schools · Edtech
  - Government & Nonprofit: Government · Nonprofit & NGO · International organizations
  - Other: Other

  Pick by what the company mainly does, from an MBA job seeker's point of view ("Big tech" = Apple, Microsoft, Alphabet,
  Amazon, Meta, and similarly huge diversified tech firms).
- `short_description`: at most 8 words. `description`: 1-2 sentences, at most 40 words, factual, in your own words.
- `hq`: global headquarters. `region` is the US state (full name) or the province/region abroad.
- `ownership`: `public`, `private`, `subsidiary`, `nonprofit`, `government`, or `partnership`.
- `employees`: approximate current headcount as an integer, or null.
- `us_offices`: **the company's major US office locations other than HQ**: corporate hubs, regional offices, large
  tech or operations centres. At most 15, biggest first. Not retail stores, bank branches, warehouses, plants
  or hospitals one by one. Each needs a `source_url` you actually opened or saw in search results that states it
  (the company's own locations / offices page is best; Wikipedia is fine). Cities in
  `offices_seen_in_our_job_postings` are already known: include them only if you also confirm them.
  If the company has no meaningful US offices besides HQ, or you can't verify any, use `[]`.
- `sources`: the 1-3 main URLs you used.
- `confidence`: `high` (identity and facts clearly confirmed), `medium`, or `low` (unsure which company this is).

## Method
Web search is shared and rate-limited, so **fetch pages directly first** and search only when you must:
1. Fetch the company's English Wikipedia article (`https://en.wikipedia.org/wiki/<Name>`), which gives identity, HQ,
   ownership, employees, website and often major offices.
2. Fetch the company's own offices / locations page. Try the obvious URLs on its website first
   (`/locations`, `/offices`, `/about/locations`, `/contact`, `/our-offices`); search only if those fail.
3. Use web search for companies that have no Wikipedia article or whose identity is unclear.
If a search or fetch is rate-limited, wait a little and continue with the next company, then come back.

**Never fill a fact from memory alone.** Every non-null field must be supported by a page you fetched or a search
result you saw; list those in `sources`. If you couldn't verify a company, set `confidence: "low"`, keep only
`id`, `name`, `kind` and what you confirmed, and say why in `notes`. Empty is fine; unverified is not.

Expect about 3 fetches per company (so 25-40 tool calls for a batch of 10). A batch finished in a handful of calls
is not acceptable. Work through the whole batch. Write the output file after every ~10 companies (overwrite it with everything
done so far), so nothing is lost if you stop early.
Your final message: the output path, how many companies, and any you couldn't identify.

## Light mode (batch files named `lt_NN.json`)
These are long-tail companies (usually one classmate contact each, often small or private). For each one:
identify it, then fill `name`, `kind`, `wikidata_id` (only if the guess is clearly right, else null), `vertical`,
`sub_vertical`, `short_description`, `description`, `website`, `hq`, `ownership`, `sources`, `confidence`, `notes`.
**Skip offices** (`us_offices: []`) and `employees` (null) unless they're on the first page you open.
One fetch or search per company is usually enough: the company's own website or LinkedIn-style summary in
search results. Small or ambiguous names are common; if you can't tell which company it is, `confidence: "low"`
and say so. The same rule applies: nothing from memory alone. Batches are 30 companies; write the file every 10.
