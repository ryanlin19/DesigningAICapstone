# Company research

**Where:** table `company_research` in D1 `cohort`. Each row is one company in the board's directory that nobody has
checked. `info` (JSON) has the spellings people use for it, an automatic Wikidata guess that may be wrong, and the US
metros where it posts jobs.

**What to do:** take rows with `status = 'todo'` (or `'needs_fix'`: read `error` first), best tier first:

```sql
SELECT id, name, info, status, error FROM company_research
WHERE status IN ('todo', 'needs_fix') ORDER BY tier, id LIMIT 25;
```

Research each from the company's own website (About, Locations, Careers), Wikipedia, Wikidata, SEC filings and
reputable news. **Not LinkedIn.** Then write one JSON object per company:

```sql
UPDATE company_research
SET result = '{"name": "...", ...}', status = 'done', researched_at = '2026-11-12T10:00:00Z'
WHERE id = 'the-row-id';
```

Inside the SQL string, double every `'` (`O''Brien`). Several `UPDATE`s can run in one go. The board's owner merges
`done` rows into the directory; rows come back as `needs_fix` with an `error` if the JSON couldn't be used.

**The JSON** (leave a field `null` when you can't confirm it, and say why in `notes`):

```json
{
  "name": "proper current name",
  "kind": "employer | school | recruiter | student_org | not_a_company",
  "wikidata_id": "Q-number of the right Wikidata item, or null",
  "vertical": "from the list below",
  "sub_vertical": "from that vertical's list",
  "short_description": "under 10 words",
  "description": "one or two plain sentences: what it does and for whom",
  "website": "https://...",
  "hq": {"city": "...", "region": "state or province", "country": "..."},
  "ownership": "public | private | government | nonprofit | subsidiary",
  "ticker": "e.g. NYSE: XYZ, or null",
  "parent": "parent company if a unit or subsidiary, else null",
  "employees": 1200,
  "us_offices": [{"city": "...", "region": "state", "source_url": "page listing it"}],
  "confidence": "high | medium | low",
  "sources": ["urls used"],
  "notes": "anything uncertain"
}
```

- `us_offices`: US only, not the HQ again, the 15 biggest at most, each with a page that lists it.
- `confidence`: high = name, website and HQ confirmed on official sources; medium = mostly; low = unsure it's the
  right organization (shared name, little published).
- `kind`: `not_a_company` for "Self-employed", "Stealth", "Freelance" and the like.
- Verticals and sub-verticals, exactly as written:
  - Consulting: Strategy consulting, Management & operations consulting, Big Four & accounting, Economic & litigation consulting, Technology consulting, Restructuring & turnaround, Other consulting
  - Financial Services: Investment banking, Commercial & retail banking, Private equity, Venture capital, Hedge funds & asset management, Insurance, Fintech & payments, Exchanges & financial data, Real estate investment, Other financial services
  - Technology: Big tech, Software & SaaS, AI, Semiconductors & hardware, Internet & marketplaces, Cybersecurity, IT services, Other technology
  - Consumer & Retail: Consumer packaged goods, Retail & e-commerce, Restaurants & hospitality, Apparel & luxury, Beverages, Other consumer
  - Healthcare & Life Sciences: Pharma & biotech, Medical devices, Healthcare providers, Health insurance & services, Digital health
  - Industrials & Manufacturing: Aerospace & defense, Industrial machinery, Chemicals & materials, Construction & engineering, Automotive, Other industrials
  - Energy & Climate: Oil & gas, Utilities & power, Renewables & climate tech, Other energy
  - Agriculture & Food: Agribusiness & ag tech, Food production, Other agriculture
  - Media, Entertainment & Telecom: Media & publishing, Entertainment & gaming, Telecommunications, Advertising & marketing
  - Transportation & Logistics: Airlines, Ride-hailing & mobility, Logistics & shipping, Other transportation
  - Real Estate: Real estate development & services, Proptech
  - Education: Universities & schools, Edtech
  - Government & Nonprofit: Government, Nonprofit & NGO, International organizations
  - Other: Other

## For the board's owner

```bash
python3 company-db/companies.py muse-push    # offer every unresearched company (safe to repeat)
python3 company-db/companies.py muse-pull    # merge Muse's 'done' rows into the directory (research/muse.json), then rebuild it
```
