"""Spike step 1: which companies have a Greenhouse/Lever/Ashby board?

Probes the 169 consulting firms plus a seed list of tech companies, and saves
every job it finds to data/spike_jobs.json for the classification step.
"""
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ats

DATA = Path(__file__).resolve().parents[2] / "data"

TECH_SEED = """Stripe,Airbnb,Databricks,Figma,Notion,Ramp,OpenAI,Anthropic,Plaid,Brex,Rippling,Gusto,Datadog,Snowflake,
Cloudflare,Twilio,Okta,Asana,Airtable,Canva,Instacart,DoorDash,Lyft,Uber,Pinterest,Reddit,Discord,Coinbase,Robinhood,Chime,
Affirm,SoFi,Block,Toast,Square,Shopify,HubSpot,Zendesk,Intercom,Mongodb,Elastic,Hashicorp,Gitlab,Github,Vercel,Netlify,
Scale AI,Glean,Anduril,Palantir,Samsara,Flexport,Faire,Deel,Carta,Mercury,Webflow,Retool,Amplitude,Mixpanel,Segment,
Snyk,Wiz,CrowdStrike,Zscaler,Lattice,Gong,Outreach,Calendly,Grammarly,Duolingo,Peloton,Warby Parker,Allbirds,Oscar Health,
Hims,Ro,Zocdoc,Flatiron Health,Tempus,Benchling,Cityblock,Included Health,Rivian,Lucid,Waymo,Nuro,Aurora,Zipline,Relativity Space,
Anyscale,Cohere,Mistral,Perplexity,Harvey,Rippling,Navan,Lime,Bird,Opendoor,Compass,Zillow,Redfin,Carvana""".replace("\n", "").split(",")


def work(name):
    hit = ats.probe(name.strip())
    if not hit:
        return {"name": name, "found": False}
    plat, slug, jobs = hit
    return {"name": name, "found": True, "platform": plat, "slug": slug,
            "n_jobs": len(jobs), "jobs": jobs}


def main():
    firms = [f["name"] for f in json.loads((DATA / "firms.json").read_text(encoding="utf-8"))]
    targets = [("consulting", n) for n in firms] + [("tech", n.strip()) for n in TECH_SEED if n.strip()]
    with ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(lambda t: {**work(t[1]), "group": t[0]}, targets))
    (DATA / "spike_jobs.json").write_text(json.dumps(results, ensure_ascii=False), encoding="utf-8")
    for g in ("consulting", "tech"):
        rs = [r for r in results if r["group"] == g]
        hits = [r for r in rs if r["found"]]
        print(f"{g}: {len(hits)}/{len(rs)} have a board; {sum(r['n_jobs'] for r in hits)} total jobs")
        by = {}
        for r in hits:
            by[r["platform"]] = by.get(r["platform"], 0) + 1
        print("  by platform:", by)
    print("\nConsulting-firm hits (verify each is the right company):")
    for r in results:
        if r["group"] == "consulting" and r["found"]:
            print(f"  {r['name']:<45} {r['platform']:<11} {r['slug']:<28} {r['n_jobs']} jobs")


if __name__ == "__main__":
    main()
