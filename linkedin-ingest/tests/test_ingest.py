"""Offline tests. Run from the project folder:  python -m unittest -v"""
import io
import json
import unittest
import zipfile
from pathlib import Path

from ingest import registry, rules
from ingest.db import connect
from ingest.pipeline import Ingestor

HERE = Path(__file__).resolve().parent


def fresh_db():
    con = connect(":memory:")
    registry.seed(con)
    return con


def fake_caller(answers):
    """Stand-in for the API: returns canned JSON, still run through the real validator."""
    def caller(model, system, user, validate, task=None, con=None, run_id=None, max_tokens=None):
        data = answers(task, json.loads(user))
        return validate(data), {"model": model, "latency_ms": 1, "input_tokens": 10,
                                "output_tokens": 5, "cost_usd": 0.0, "ok": True, "error": None}
    return caller


class TestRules(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(rules.normalize_company("JPMorgan Chase & Co."), "jpmorgan chase")
        self.assertEqual(rules.normalize_company("Silver Point Capital, L.P."), "silver point capital")
        self.assertEqual(rules.normalize_company("Boston Consulting Group (BCG)"), "boston consulting group")
        self.assertIsNone(rules.normalize_company("Self-employed"))

    def test_candidates_reject_lookalikes(self):
        self.assertFalse(rules.is_candidate("scaleway", "scale ai"))
        self.assertFalse(rules.is_candidate("faze clan", "cla"))
        self.assertTrue(rules.is_candidate("goldman sachs ayco", "goldman sachs"))
        self.assertTrue(rules.is_candidate("삼일pwc", "pwc"))

    def test_title_rules(self):
        self.assertEqual(rules.title_bucket("Director of Engineering"), "engineering")
        self.assertEqual(rules.title_bucket("Summer Associate Law Clerk"), "legal")
        self.assertEqual(rules.title_bucket("Associate"), "other")


class TestRegistry(unittest.TestCase):
    def test_alias_and_compressed_lookup(self):
        con = fresh_db()
        self.assertEqual(registry.lookup(con, rules.normalize_company("JPMorgan Chase & Co.")), "jpmorganchase")
        self.assertEqual(registry.lookup(con, "facebook"), "meta")
        self.assertIsNone(registry.lookup(con, "scaleway"))


class TestPipeline(unittest.TestCase):
    def test_fake_connections_counts_and_no_personal_data(self):
        con = fresh_db()
        Ingestor(con).ingest(HERE / "fake_Connections.csv", "t1", "connections", "2026-11-09")
        got = {r["company_norm"]: r["count"] for r in con.execute("SELECT * FROM derived_connections")}
        expected = json.loads((HERE / "expected_connections_match.json").read_text())["expected_counts"]
        for company, n in expected.items():
            norm = registry.lookup(con, rules.normalize_company(company)) or rules.normalize_company(company)
            self.assertEqual(got.get(norm, 0), n, company)
        dump = "\n".join(con.iterdump())
        for leaked in ("Fictional", "fake-ada-0001", "kai@example.com"):
            self.assertNotIn(leaked, dump)

    def test_zip_reads_only_allowed_files(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("Profile.csv", "First Name,Last Name,Headline,Address\nTest,Person,Student,1 Main St\n")
            z.writestr("Positions.csv", "Company Name,Title,Description,Location,Started On,Finished On\nAcme,Engineer,,,Jan 2020,\n")
            z.writestr("messages.csv", "secret\n")
        path = HERE / "_tmp_export_11-09-2026.zip"
        path.write_bytes(buf.getvalue())
        try:
            con = fresh_db()
            s = Ingestor(con).ingest(path, "t2", "profile,connections")
            self.assertEqual(s["connections"], "none in export")
            self.assertEqual(s["files_left_unopened"], 1)
            self.assertEqual(s["snapshot_date"], "2026-11-09")
            self.assertNotIn("1 Main St", "\n".join(con.iterdump()))
        finally:
            path.unlink()

    def test_ai_company_paths(self):
        con = fresh_db()
        registry.add_company(con, "kpmg", "KPMG", "seed")

        def answers(task, payload):
            if payload["new_name"] == "kpmg us":
                return {"decision": "same", "match": "kpmg", "reason": "regional"}
            if payload["new_name"] == "goldman sachs ayco":
                return {"decision": "subsidiary", "match": "goldman sachs", "reason": "owned unit"}
            return {"decision": "different", "match": None, "reason": "unrelated"}
        ing = Ingestor(con, ai_model="haiku", caller=fake_caller(answers))
        self.assertEqual(ing.resolve_company("KPMG US"), "kpmg")
        self.assertEqual(ing.resolve_company("Goldman Sachs Ayco"), "goldman sachs ayco")
        parent = con.execute("SELECT parent_norm FROM companies WHERE company_norm='goldman sachs ayco'").fetchone()[0]
        self.assertEqual(parent, "goldman sachs")
        self.assertEqual(registry.lookup(con, "kpmg us"), "kpmg")  # learned alias, no second call

    def test_ai_rejects_match_outside_candidates(self):
        con = fresh_db()
        registry.add_company(con, "kpmg", "KPMG", "seed")
        bad = fake_caller(lambda t, p: {"decision": "same", "match": "deloitte", "reason": "x"})
        ing = Ingestor(con, ai_model="haiku", caller=bad)
        # validator raises ValueError; the real client retries then raises LLMError
        with self.assertRaises(ValueError):
            ing.resolve_company("KPMG US")

    def test_ai_titles_batched_and_cached(self):
        con = fresh_db()
        calls = []

        def answers(task, payload):
            calls.append(len(payload))
            return [{"i": p["i"], "bucket": "finance"} for p in payload]
        ing = Ingestor(con, ai_model="haiku", caller=fake_caller(answers))
        out = ing.bucket_titles([("Associate", "goldman sachs"), ("Engineer", "x"), ("Associate", "goldman sachs")])
        self.assertEqual(out, ["finance", "engineering", "finance"])
        self.assertEqual(calls, [1])                     # duplicate sent once, rule hit not sent
        ing.bucket_titles([("Associate", "goldman sachs")])
        self.assertEqual(calls, [1])                     # served from cache


if __name__ == "__main__":
    unittest.main()
