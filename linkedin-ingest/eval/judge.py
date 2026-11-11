#!/usr/bin/env python3
"""Have a different model score the 10 AI cases, then measure agreement with the team.

  python eval/judge.py --results eval/out/results_haiku.csv     # needs ANTHROPIC_API_KEY

The judge (Opus by default) is a different model from both tiers under test. It
gets the same 1-5 rubric the team uses. Agreement is reported against the
team_score column; until the team has filled it in, it falls back to the
suggested scores and says so.
"""
import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness import load_cases  # noqa: E402
from ingest import llm  # noqa: E402
from ingest.config import JUDGE_MODEL, MODELS  # noqa: E402

SYSTEM = (
    "You are grading one step of a data pipeline that loads LinkedIn exports. "
    "Score the OUTPUT against the EXPECTED answer using this rubric, and judge meaning, "
    "not formatting. For company cases, a decision of 'new' and 'different' mean the same thing.\n{rubric}\n"
    "Reply with JSON only: {{\"score\": <1-5>, \"reason\": <under 25 words>}}."
)


def validate(d):
    s = int(d["score"])
    if not 1 <= s <= 5:
        raise ValueError("score must be 1-5")
    return {"score": s, "reason": str(d.get("reason", ""))[:200]}


def main(caller=llm.call_json):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--results", required=True)
    p.add_argument("--judge", default=JUDGE_MODEL, choices=sorted(MODELS))
    a = p.parse_args()

    golden = load_cases()
    rubric = "\n".join(f"{k}: {v}" for k, v in golden["scoring_rubric"].items())
    notes = {c["id"]: c.get("note", "") for c in golden["cases"]}
    with open(a.results, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    tested = Path(a.results).stem.replace("results_", "")
    if MODELS.get(tested) == MODELS[a.judge]:
        sys.exit("The judge must be a different model from the one being judged.")

    ten = [r for r in rows if r["ai10"] == "True"]
    team_filled = all(r["team_score"].strip() for r in ten)
    ref_name = "team_score" if team_filled else "auto_score"

    out_rows, pairs, cost = [], [], 0.0
    for r in ten:
        user = json.dumps({"case": r["id"], "type": r["type"], "note": notes.get(r["id"], ""),
                           "input": json.loads(r["input"]), "expected": json.loads(r["expected"]),
                           "acceptable": json.loads(r["acceptable"]), "output": json.loads(r["output"])},
                          ensure_ascii=False)
        res, stats = caller(MODELS[a.judge], SYSTEM.format(rubric=rubric), user, validate,
                            task="judge", max_tokens=200)
        cost += stats["cost_usd"]
        ref = int(float(r[ref_name]))
        pairs.append((res["score"], ref))
        out_rows.append({**r, "judge_model": MODELS[a.judge], "judge_score": res["score"],
                         "judge_reason": res["reason"]})
        print(f"{r['id']:<4} judge {res['score']}  {ref_name} {ref}  {res['reason']}")

    exact = sum(j == t for j, t in pairs) / len(pairs)
    within1 = sum(abs(j - t) <= 1 for j, t in pairs) / len(pairs)
    mad = sum(abs(j - t) for j, t in pairs) / len(pairs)
    path = Path(a.results).with_name(Path(a.results).stem + "_judged.csv")
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()))
        w.writeheader()
        w.writerows(out_rows)

    print(f"\nJudge {MODELS[a.judge]} on {len(pairs)} cases from {tested}, compared with {ref_name}:")
    print(f"  exact agreement {exact:.0%}, within one point {within1:.0%}, mean absolute difference {mad:.2f}")
    print(f"  judge cost ${cost:.4f}")
    if not team_filled:
        print("  NOTE: team_score is not filled in yet, so this compares with the suggested scores. "
              "Fill team_score for the 10 AI cases and rerun for the number to report.")
    print(f"Wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
