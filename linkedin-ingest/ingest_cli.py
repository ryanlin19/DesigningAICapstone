#!/usr/bin/env python3
"""Load LinkedIn data exports into the cohort database.

  python ingest_cli.py <export.zip> --person-id <id> --consent profile,connections [--ai haiku|sonnet] [--db data/cohort.db]

Without --ai the run is fully deterministic: titles the rules can't place stay
"other" and uncertain company matches go to the review queue.
"""
import argparse
import json
import sys

from ingest import registry
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
    a = p.parse_args()

    con = connect(a.db)
    registry.seed(con)
    summary = Ingestor(con, ai_model=a.ai).ingest(a.export, a.person_id, a.consent, a.snapshot)
    print(json.dumps(summary, indent=2))
    cost = con.execute("SELECT COALESCE(SUM(cost_usd),0) c, COUNT(*) n FROM ai_calls").fetchone()
    print(f"\nAI calls so far: {cost['n']}, total cost ${cost['c']:.4f}")
    print("Done. Delete the original export once you've checked the database.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
