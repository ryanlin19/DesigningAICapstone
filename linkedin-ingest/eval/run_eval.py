#!/usr/bin/env python3
"""Run the 20 golden cases and write a scoring sheet for the team.

  python eval/run_eval.py --model rules      # no AI, runs anywhere
  python eval/run_eval.py --model haiku      # needs ANTHROPIC_API_KEY
  python eval/run_eval.py --model sonnet

Writes eval/out/results_<model>.csv. Each row has the output, a suggested score
from the rubric, and empty team_score columns for each teammate to fill in 1-5.
Prints the top failure patterns across the run.
"""
import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import load_cases, run_case  # noqa: E402

OUT = Path(__file__).resolve().parent / "out"
FIELDS = ["id", "type", "path", "ai10", "tags", "input", "expected", "acceptable", "output",
          "auto_score", "failure_mode", "ai_calls", "latency_ms", "cost_usd", "input_tokens",
          "output_tokens", "team_score_a", "team_score_b", "team_score_c", "team_score", "team_notes"]


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--model", choices=["rules", "haiku", "sonnet"], default="rules")
    a = p.parse_args()
    model = None if a.model == "rules" else a.model

    golden = load_cases()
    OUT.mkdir(exist_ok=True)
    rows = []
    for case in golden["cases"]:
        r = run_case(case, model)
        rows.append({
            "id": case["id"], "type": case["type"], "path": case["path"], "ai10": case["ai10"],
            "tags": "|".join(case["tags"]), "input": json.dumps(case["input"], ensure_ascii=False),
            "expected": json.dumps(case["expected"], ensure_ascii=False),
            "acceptable": json.dumps(case.get("acceptable", []), ensure_ascii=False),
            "output": json.dumps(r["output"], ensure_ascii=False),
            **{k: r[k] for k in ("auto_score", "failure_mode", "ai_calls", "latency_ms", "cost_usd",
                                 "input_tokens", "output_tokens")},
            "team_score_a": "", "team_score_b": "", "team_score_c": "", "team_score": "", "team_notes": "",
        })
        print(f"{case['id']:<4} {case['type']:<8} score {r['auto_score']}  {r['failure_mode'] or 'ok'}")

    path = OUT / f"results_{a.model}.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)

    scores = [r["auto_score"] for r in rows]
    ai_rows = [r for r in rows if r["path"] == "ai"]
    print(f"\nModel: {a.model}")
    print(f"Mean suggested score, all 20: {sum(scores) / len(scores):.2f}")
    print(f"Mean on the 12 AI cases: {sum(r['auto_score'] for r in ai_rows) / len(ai_rows):.2f}")
    print(f"Mean on the 8 rules cases: "
          f"{sum(r['auto_score'] for r in rows if r['path'] == 'rules') / (len(rows) - len(ai_rows)):.2f}")
    print(f"Cases scoring 4 or 5: {sum(s >= 4 for s in scores)}/20")
    print(f"AI cost for the run: ${sum(r['cost_usd'] for r in rows):.5f}")

    modes = Counter(r["failure_mode"].split(":")[0] for r in rows if r["failure_mode"])
    print("\nTop failure patterns:")
    for mode, n in modes.most_common(3):
        ids = [r["id"] for r in rows if r["failure_mode"].startswith(mode)]
        print(f"  {mode}: {n} ({', '.join(ids)})")
    if not modes:
        print("  none")
    print(f"\nWrote {path}. Each teammate fills team_score_a/b/c (1-5); team_score is the agreed final.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
