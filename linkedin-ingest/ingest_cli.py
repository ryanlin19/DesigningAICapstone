#!/usr/bin/env python3
"""Load LinkedIn data exports into the cohort database.

  python ingest_cli.py <export.zip> --person-id <id> --consent profile,connections [--ai haiku|sonnet] [--db data/cohort.db]

Without --ai the run is fully deterministic: titles the rules can't place stay
"other" and uncertain company matches go to the review queue.

Contact keys (needed for deduplication and shared contacts) use the cohort's secret in
.contact_key or the COHORT_CONTACT_KEY variable. Create it once with
`python -m ingest.contact_keys new`; every export must be loaded with the same secret.
--profile-url is the classmate's own LinkedIn link, so classmates aren't counted as each other's
shared contacts. It is stored only as a key.
"""
import argparse
import json
import sys

from ingest import contact_keys, registry
from ingest.db import connect
from ingest.pipeline import Ingestor


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("export")
    p.add_argument("--person-id", required=True)
    p.add_argument("--consent", required=True, help="comma-separated: profile, connections")
    p.add_argument("--ai", choices=["haiku", "sonnet"], default=None)
    p.add_argument("--snapshot", help="export date YYYY-MM-DD (default: from file name)")
    p.add_argument("--db", default="data/cohort.db")
    p.add_argument("--profile-url", help="the classmate's own LinkedIn profile link (stored only as a key)")
    p.add_argument("--no-contact-keys", action="store_true",
                   help="load counts only, with no per-contact rows (no dedup or shared contacts)")
    a = p.parse_args()

    secret = None if a.no_contact_keys else contact_keys.load_secret()
    if not secret and not a.no_contact_keys:
        p.error("no contact key set up. Run `python -m ingest.contact_keys new` once for the whole cohort "
                "(or pass --no-contact-keys to load counts only).")
    con = connect(a.db)
    registry.seed(con)
    summary = Ingestor(con, ai_model=a.ai, contact_secret=secret).ingest(
        a.export, a.person_id, a.consent, a.snapshot, profile_url=a.profile_url)
    print(json.dumps(summary, indent=2))
    cost = con.execute("SELECT COALESCE(SUM(cost_usd),0) c, COUNT(*) n FROM ai_calls").fetchone()
    print(f"\nAI calls so far: {cost['n']}, total cost ${cost['c']:.4f}")
    print("Done. Delete the original export once you've checked the database.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
