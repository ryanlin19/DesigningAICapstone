"""Run one golden case through the real pipeline code and score it with the rubric."""
import io
import json
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ingest import registry, rules  # noqa: E402
from ingest.db import connect  # noqa: E402
from ingest.pipeline import Ingestor  # noqa: E402

GOLDEN = Path(__file__).resolve().parent / "golden_cases.json"
NEIGHBORS = {frozenset(p) for p in [("engineering", "data_ml"), ("sales_gtm", "marketing"),
                                    ("operations", "consulting"), ("student_intern", "education"),
                                    ("finance", "consulting")]}


def load_cases():
    return json.loads(GOLDEN.read_text(encoding="utf-8"))


def _db():
    con = connect(":memory:")
    registry.seed(con)
    return con


def _ai_totals(con):
    r = con.execute("SELECT COUNT(*) n, COALESCE(SUM(latency_ms),0) l, COALESCE(SUM(cost_usd),0) c,"
                    " COALESCE(SUM(input_tokens),0) i, COALESCE(SUM(output_tokens),0) o FROM ai_calls").fetchone()
    return {"ai_calls": r["n"], "latency_ms": r["l"], "cost_usd": r["c"], "input_tokens": r["i"], "output_tokens": r["o"]}


def _same(decision):
    return "none" if decision in ("new", "different") else decision


def run_company(case, model, caller=None):
    con = _db()
    for name in case["input"]["registry_add"]:
        registry.add_company(con, rules.normalize_company(name), name, "seed")
    raw = case["input"]["name"]
    norm = rules.normalize_company(raw)
    candidates = [] if registry.lookup(con, norm) else [c["company_norm"] for c in registry.retrieve(con, norm)]
    ing = Ingestor(con, ai_model=model, caller=caller)
    error = None
    try:
        result = ing.resolve_company(raw)
    except Exception as e:  # recorded as a failure, not a crash
        result, error = None, str(e)[:200]
    if result and result != norm:
        out = {"decision": "same", "match": result}
    else:
        row = con.execute("SELECT parent_norm FROM companies WHERE company_norm=?", (norm,)).fetchone()
        out = ({"decision": "subsidiary", "match": row["parent_norm"]} if row and row["parent_norm"]
               else {"decision": "new", "match": None})
    out["candidates"] = candidates
    if error:
        out["error"] = error
    return out, _ai_totals(con)


def run_title(case, model, caller=None):
    con = _db()
    ing = Ingestor(con, ai_model=model, caller=caller)
    error = None
    try:
        bucket = ing.bucket_titles([(case["input"]["title"], case["input"]["company"])])[0]
    except Exception as e:
        bucket, error = "other", str(e)[:200]
    out = {"bucket": bucket}
    if error:
        out["error"] = error
    return out, _ai_totals(con)


def run_e2e(case, model, caller=None):
    con = _db()
    ing = Ingestor(con, ai_model=model, caller=caller)
    checks = {}
    if case["id"] == "E1":
        ing.ingest(ROOT / case["input"]["file"], "e2e", case["input"]["scopes"], "2026-11-09")
        got = {r["company_norm"]: r["count"] for r in con.execute("SELECT * FROM derived_connections")}
        for comp, n in case["expected"]["counts"].items():
            checks[f"count:{comp}"] = got.get(registry.lookup(con, comp) or comp, 0) == n
        for comp in case["expected"]["separate"]:
            checks[f"separate:{comp}"] = comp in got
        dump = "\n".join(con.iterdump())
        checks["no_personal_data"] = not any(s in dump for s in ("Fictional", "fake-ada-0001", "kai@example.com"))
    else:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("Profile.csv", "First Name,Last Name,Headline\nTest,Person,Student\n")
            z.writestr("Positions.csv", "Company Name,Title,Description,Location,Started On,Finished On\n"
                                        "Acme,Engineer,,,Jan 2020,\n")
            z.writestr("messages.csv", "private\n")
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "export_11-09-2026.zip"
            p.write_bytes(buf.getvalue())
            try:
                s = ing.ingest(p, "e2e", case["input"]["scopes"])
                for k, v in case["expected"].items():
                    checks[k] = s.get(k) == v
            except Exception as e:
                checks["no_crash"] = False
                checks["error"] = str(e)[:200]
    out = {"checks_passed": sum(v is True for v in checks.values()), "checks_total": len(checks),
           "failed": [k for k, v in checks.items() if v is not True]}
    return out, _ai_totals(con)


def run_case(case, model=None, caller=None):
    fn = {"company": run_company, "title": run_title, "e2e": run_e2e}[case["type"]]
    out, cost = fn(case, model, caller)
    score, mode = score_case(case, out)
    return {"output": out, "auto_score": score, "failure_mode": mode, **cost}


def score_case(case, out):
    """Return (1-5 suggested score, failure mode or ''). The team assigns final scores."""
    if case["type"] == "e2e":
        if not out["failed"]:
            return 5, ""
        frac = out["checks_passed"] / max(out["checks_total"], 1)
        return (3 if frac >= 0.75 else 1), "e2e:" + ",".join(out["failed"])[:80]

    if case["type"] == "title":
        got, exp = out["bucket"], case["expected"]["bucket"]
        if got == exp:
            return 5, ""
        if any(a["bucket"] == got for a in case.get("acceptable", [])):
            return 4, ""
        if got == "other":
            return 2, "title_left_other"
        if frozenset((got, exp)) in NEIGHBORS:
            return 3, "title_neighbor_bucket"
        return 1, "title_wrong_bucket"

    exp, got = case["expected"], out
    exp_d, got_d = _same(exp["decision"]), _same(got["decision"])
    if got_d == exp_d and got.get("match") == exp.get("match"):
        return 5, ""
    for a in case.get("acceptable", []):
        if _same(a["decision"]) == got_d and a.get("match") == got.get("match"):
            return 4, ""
    if exp_d != "none" and exp["match"] not in got.get("candidates", []) and got_d == "none":
        return 2, "company_retrieval_miss"
    if exp_d != "none" and got_d == "none":
        return 2, "company_missed_merge"
    if exp_d != "none" and got.get("match") == exp["match"]:
        return 3, "company_relation_swap"
    return 1, "company_false_merge"
