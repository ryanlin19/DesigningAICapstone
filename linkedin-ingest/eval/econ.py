#!/usr/bin/env python3
"""Unit economics: the same 10 AI tasks on two model tiers.

  python eval/econ.py --repeat 3          # needs ANTHROPIC_API_KEY

For each tier it runs the 10 golden cases marked ai10, `repeat` times, and reports
median and p90 latency per task, cost per 100 task runs, and quality (mean
suggested score and share scoring 4+). It also times one realistic 20-title
batch and projects the cost of ingesting one student's export, using the step
counts from your real runs in data/cohort.db. Writes eval/out/econ.md.
"""
import argparse
import json
import math
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness import load_cases, run_case  # noqa: E402
from ingest import ai_tasks, llm  # noqa: E402
from ingest.config import MODELS, TITLE_BATCH_SIZE  # noqa: E402
from ingest.db import connect  # noqa: E402

OUT = Path(__file__).resolve().parent / "out"
BATCH_TITLES = [("Associate", "goldman sachs"), ("Associate", "mckinsey & company"), ("Principal", "crestview partners"),
                ("Engagement Manager", "mckinsey & company"), ("Member of Technical Staff", "anthropic"),
                ("Fund Manager", "bregal investments"), ("Senior Associate", "ankura"), ("Analyst", "jefferies"),
                ("Summer Analyst", "morgan stanley"), ("Manager", "deloitte"), ("Underwriter", "chubb"),
                ("Investor", "golub capital"), ("Member", "cornell fintech club"), ("Senior Analyst", "huron"),
                ("Lead Analyst", "citi"), ("Principal", "kearney"), ("Incoming Associate", "goldman sachs"),
                ("Course Assistant", "cornell university"), ("Board Member, Treasurer", "educational alliance"),
                ("Associate", "latham & watkins")]


def pct(values, q):
    values = sorted(values)
    return values[min(len(values) - 1, math.ceil(q * len(values)) - 1)]


def measure_batch(tier, caller=llm.call_json):
    t0 = time.perf_counter()
    _, stats = ai_tasks.classify_titles(BATCH_TITLES[:TITLE_BATCH_SIZE], MODELS[tier], caller=caller)
    stats["latency_ms"] = stats.get("latency_ms") or int((time.perf_counter() - t0) * 1000)
    return stats


def real_step_counts(db_path):
    """Per-export AI work from real deterministic runs: companies needing judgment, titles left 'other'."""
    if not Path(db_path).exists():
        return []
    con = connect(db_path)
    out = []
    for r in con.execute("SELECT person_id, summary FROM ingest_runs ORDER BY started_at"):
        s = json.loads(r["summary"])
        steps = s.get("steps", {})
        out.append({"person_id": r["person_id"], "connections": s.get("connections"),
                    "company_calls": steps.get("company_queued_for_review", 0),
                    "titles": steps.get("title_left_other_ai_off", 0)})
    return out


def main(caller=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--tiers", nargs=2, default=["haiku", "sonnet"])
    p.add_argument("--repeat", type=int, default=3)
    p.add_argument("--db", default=str(ROOT / "data" / "cohort.db"))
    a = p.parse_args()

    ten = [c for c in load_cases()["cases"] if c["ai10"]]
    summary = {}
    for tier in a.tiers:
        lat, cost, scores, comp_cost = [], [], [], []
        for _ in range(a.repeat):
            for case in ten:
                r = run_case(case, tier, caller)
                lat.append(r["latency_ms"])
                cost.append(r["cost_usd"])
                scores.append(r["auto_score"])
                if case["type"] == "company":
                    comp_cost.append(r["cost_usd"])
        batch = measure_batch(tier, caller or llm.call_json)
        summary[tier] = {
            "model": MODELS[tier], "runs": len(lat),
            "median_latency_ms": statistics.median(lat), "p90_latency_ms": pct(lat, 0.9),
            "cost_per_100_runs": 100 * sum(cost) / len(cost),
            "mean_score": sum(scores) / len(scores), "share_4_plus": sum(s >= 4 for s in scores) / len(scores),
            "company_call_cost": sum(comp_cost) / max(len(comp_cost), 1),
            "batch20_cost": batch["cost_usd"], "batch20_latency_ms": batch["latency_ms"],
        }
        s = summary[tier]
        print(f"{tier}: median {s['median_latency_ms']:.0f} ms, p90 {s['p90_latency_ms']:.0f} ms, "
              f"${s['cost_per_100_runs']:.4f} per 100 runs, mean score {s['mean_score']:.2f}, "
              f"{s['share_4_plus']:.0%} scored 4+")

    counts = real_step_counts(a.db)
    lines = ["# Unit economics: same 10 tasks on two tiers", "",
             f"Each tier ran the 10 AI golden cases {a.repeat} times. Quality uses the suggested rubric scores;"
             " replace with team scores once filled in.", "",
             "| Tier | Model | Median latency per task | p90 latency | Cost per 100 runs | Mean score (1-5) | Scored 4+ |",
             "|---|---|---|---|---|---|---|"]
    for tier, s in summary.items():
        lines.append(f"| {tier} | {s['model']} | {s['median_latency_ms'] / 1000:.2f} s | {s['p90_latency_ms'] / 1000:.2f} s"
                     f" | ${s['cost_per_100_runs']:.4f} | {s['mean_score']:.2f} | {s['share_4_plus']:.0%} |")
    if counts:
        lines += ["", "## Projected cost per student export", "",
                  "From the real deterministic runs: companies that needed a judgment and titles the rules left"
                  f" as 'other' (sent in batches of {TITLE_BATCH_SIZE}).", "",
                  "| Export | Connections | Company calls | Title batches | " +
                  " | ".join(f"{t} cost" for t in summary) + " |",
                  "|---|---|---|---|" + "---|" * len(summary)]
        for c in counts:
            batches = math.ceil(c["titles"] / TITLE_BATCH_SIZE)
            costs = [c["company_calls"] * s["company_call_cost"] + batches * s["batch20_cost"] for s in summary.values()]
            lines.append(f"| {c['person_id']} | {c['connections']} | {c['company_calls']} | {batches} | " +
                         " | ".join(f"${x:.4f}" for x in costs) + " |")
    OUT.mkdir(exist_ok=True)
    (OUT / "econ.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (OUT / "econ.json").write_text(json.dumps({"tiers": summary, "exports": counts}, indent=2), encoding="utf-8")
    print("\n" + "\n".join(lines))
    print(f"\nWrote {OUT / 'econ.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
