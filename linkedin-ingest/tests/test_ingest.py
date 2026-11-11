"""Offline tests. Run from the project folder:  python -m unittest -v"""
import io
import json
import unittest
import zipfile
from pathlib import Path

from ingest import contact_keys, registry, rules
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
        self.assertEqual(rules.title_bucket("Investment Research Analyst"), "finance")
        self.assertEqual(rules.title_bucket("Research Scientist"), "data_ml")


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

    def test_contact_rows_keyed_named_and_no_email(self):
        con = fresh_db()
        s = Ingestor(con, contact_secret=SECRET).ingest(HERE / "fake_Connections.csv", "t1", "connections", "2026-11-09")
        n_contacts = con.execute("SELECT COUNT(*) FROM contacts").fetchone()[0]
        n_counted = con.execute("SELECT SUM(count) FROM derived_connections").fetchone()[0]
        self.assertEqual(n_contacts, n_counted)             # one keyed row per counted connection
        self.assertEqual(s["contacts_keyed"], n_contacts)
        years = {r[0] for r in con.execute("SELECT connected_year FROM contacts")}
        self.assertIn(2025, years)
        # Contacts keep their name, title and profile link (for the relationship graph); emails are never kept.
        dump = "\n".join(con.iterdump())
        self.assertIn("fake-ada-0001", dump)
        self.assertNotIn("kai@example.com", dump)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM contacts WHERE full_name IS NULL").fetchone()[0], 0)


SECRET = b"test-secret-not-for-real-use"


def connections_csv(rows):
    head = "Notes:\n\"preamble\"\n\nFirst Name,Last Name,URL,Email Address,Company,Position,Connected On\n"
    return head + "\n".join(",".join(r) for r in rows) + "\n"


class TestOwnProfileLink(unittest.TestCase):
    """The export owner's link comes from invitations they sent; nothing else from that file is kept."""
    INVITES = ('From,To,Sent At,Message,Direction,inviterProfileUrl,inviteeProfileUrl\n'
               'Owner Person,Rita Recipient,"11/1/26, 9:00 AM","Hi Rita, secret note",OUTGOING,'
               'https://www.linkedin.com/in/owner-person,https://www.linkedin.com/in/rita-recipient\n'
               'Ivan Inviter,Owner Person,"10/1/26, 9:00 AM",,INCOMING,'
               'https://www.linkedin.com/in/ivan-inviter,https://www.linkedin.com/in/owner-person\n'
               'Owner Person,Sol Second,"9/1/26, 9:00 AM",,OUTGOING,'
               'https://www.linkedin.com/in/owner-person/,https://www.linkedin.com/in/sol-second\n')

    def export(self, with_invites=True):
        path = HERE / "_tmp_owner_11-09-2026.zip"
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("Connections.csv", connections_csv([["Ada", "One", "https://www.linkedin.com/in/ada-one", "", "Acme", "Consultant", "01 Jan 2024"]]))
            z.writestr("Profile.csv", "First Name,Last Name,Headline\nOwner,Person,MBA\n")
            if with_invites:
                z.writestr("Invitations.csv", self.INVITES)
        return path

    def test_link_from_sent_invitations(self):
        from ingest.pipeline import own_profile_url
        self.assertEqual(own_profile_url(self.INVITES), "https://www.linkedin.com/in/owner-person/")
        self.assertIsNone(own_profile_url(self.INVITES.replace("OUTGOING", "INCOMING")))
        path = self.export()
        try:
            con = fresh_db()
            s = Ingestor(con, contact_secret=SECRET).ingest(path, "o", "profile,connections")
            self.assertEqual(s["profile_url_source"], "Invitations.csv")
            row = con.execute("SELECT profile_url, self_key FROM people WHERE person_id='o'").fetchone()
            self.assertEqual(row["profile_url"], "https://www.linkedin.com/in/owner-person/")
            self.assertEqual(row["self_key"], contact_keys.contact_key(SECRET, "https://www.linkedin.com/in/owner-person"))
            dump = "\n".join(con.iterdump())
            for leaked in ("Rita", "rita-recipient", "Ivan", "ivan-inviter", "secret note", "sol-second"):
                self.assertNotIn(leaked, dump)
            # a typed-in link wins over the export
            s = Ingestor(con, contact_secret=SECRET).ingest(path, "o", "profile,connections",
                                                            profile_url="https://www.linkedin.com/in/typed-link")
            self.assertEqual(s["profile_url_source"], "given")
            self.assertEqual(con.execute("SELECT profile_url FROM people WHERE person_id='o'").fetchone()[0],
                             "https://www.linkedin.com/in/typed-link/")
        finally:
            path.unlink()

    def test_no_invitations_file(self):
        path = self.export(with_invites=False)
        try:
            con = fresh_db()
            s = Ingestor(con, contact_secret=SECRET).ingest(path, "o", "profile,connections")
            self.assertNotIn("profile_url_source", s)
            self.assertIsNone(con.execute("SELECT profile_url FROM people WHERE person_id='o'").fetchone()[0])
        finally:
            path.unlink()


class TestContactKeys(unittest.TestCase):
    def test_same_profile_same_key_in_any_url_form(self):
        k = lambda u: contact_keys.contact_key(SECRET, u)
        base = k("https://www.linkedin.com/in/jane-doe-1")
        self.assertEqual(base, k("http://linkedin.com/in/Jane-Doe-1/"))
        self.assertEqual(base, k("https://www.linkedin.com/in/jane-doe-1?trk=abc"))
        self.assertNotEqual(base, k("https://www.linkedin.com/in/jane-doe-2"))
        self.assertNotEqual(base, contact_keys.contact_key(b"other-secret", "https://www.linkedin.com/in/jane-doe-1"))
        self.assertNotIn("jane", base)

    def test_name_fallback_and_nothing_to_key(self):
        a = contact_keys.contact_key(SECRET, "", "Lee", "Park", "acme")
        self.assertEqual(a, contact_keys.contact_key(SECRET, None, " lee ", "PARK", "acme"))
        self.assertNotEqual(a, contact_keys.contact_key(SECRET, None, "Lee", "Park", "other co"))
        self.assertIsNone(contact_keys.contact_key(SECRET, None, "", "", "acme"))

    def test_connected_year(self):
        self.assertEqual(contact_keys.connected_year("03 Feb 2025"), 2025)
        self.assertIsNone(contact_keys.connected_year(""))


class TestSharedContacts(unittest.TestCase):
    """Three classmates with overlapping networks. All names are invented."""

    def setUp(self):
        self.tmp = HERE / "_tmp_shared"
        self.tmp.mkdir(exist_ok=True)
        jane = ["Jane", "Doe", "https://www.linkedin.com/in/jane-doe-x1/", "", "McKinsey & Company", "Consultant"]
        cara = ["Cara", "Classmate", "https://www.linkedin.com/in/cara-classmate", "", "Acme Corp", "Consultant"]
        pat = ["Pat", "Student", "https://www.linkedin.com/in/pat-student", "", "Cornell University", "MBA Candidate"]
        lee = ["Lee", "Park", "", "", "Bain & Company", "Consultant"]          # no profile link
        exports = {
            "a": [jane + ["01 Jan 2019"], ["Sam", "Mover", "https://linkedin.com/in/sam-mover", "", "Bain & Company", "Consultant", "05 May 2020"],
                  cara + ["01 Sep 2025"], pat + ["01 Sep 2025"], lee + ["02 Feb 2022"],
                  ["Una", "Only", "https://linkedin.com/in/una-only", "", "Deloitte", "Consultant", "01 Jan 2024"]],
            "b": [["Jane", "Doe", "http://linkedin.com/in/JANE-DOE-X1?trk=1", "", "McKinsey & Company", "Consultant", "01 Jan 2023"],
                  ["Sam", "Mover", "https://www.linkedin.com/in/sam-mover/", "", "Goldman Sachs", "Investment Banking Associate", "01 Jan 2024"],
                  cara + ["01 Sep 2025"], pat + ["01 Sep 2025"], lee + ["03 Mar 2023"]],
            "c": [jane + ["01 Jan 2021"]],
        }
        snaps = {"a": "2026-01-01", "b": "2026-11-01", "c": "2026-11-01"}
        self.con = fresh_db()
        for pid, rows in exports.items():
            path = self.tmp / f"{pid}.csv"
            path.write_text(connections_csv(rows), encoding="utf-8")
            url = "https://www.linkedin.com/in/cara-classmate" if pid == "c" else None   # c is Cara
            Ingestor(self.con, contact_secret=SECRET).ingest(path, pid, "connections", snaps[pid], profile_url=url)

    def tearDown(self):
        for f in self.tmp.iterdir():
            f.unlink()
        self.tmp.rmdir()

    def test_shared_contacts(self):
        rows = {(r["company_norm"], r["depth"]): r for r in self.con.execute("SELECT * FROM shared_contacts")}
        mck = registry.lookup(self.con, "mckinsey & company") or "mckinsey & company"
        gs = registry.lookup(self.con, "goldman sachs") or "goldman sachs"
        bain = registry.lookup(self.con, "bain & company") or "bain & company"
        self.assertIn((mck, 3), rows)                              # Jane: three URL spellings, one person
        self.assertEqual(rows[(mck, 3)]["first_connected_year"], 2019)
        self.assertIn((gs, 2), rows)                               # Sam: newest export says Goldman, not Bain
        self.assertIn((bain, 2), rows)                             # Lee: matched by name + company, no link
        self.assertEqual(len(rows), 3)                             # not Cara (a classmate), Pat (student), Una (one classmate)
        links = {r[0]: r[1] for r in self.con.execute("SELECT person_id, profile_url FROM people")}
        self.assertEqual(links, {"a": None, "b": None, "c": "https://www.linkedin.com/in/cara-classmate/"})
        # Contacts keep their name, title and one standard profile link (for the relationship graph); never an email.
        jane = {tuple(r) for r in self.con.execute("SELECT full_name, position, profile_url FROM contacts WHERE company_norm = ?", (mck,))}
        self.assertIn(("Jane Doe", "Consultant", "https://www.linkedin.com/in/jane-doe-x1/"), jane)

    def test_reload_replaces_rows(self):
        before = self.con.execute("SELECT COUNT(*) FROM contacts WHERE connector_id='c'").fetchone()[0]
        path = self.tmp / "c.csv"
        Ingestor(self.con, contact_secret=SECRET).ingest(path, "c", "connections", "2026-11-02")
        self.assertEqual(before, self.con.execute("SELECT COUNT(*) FROM contacts WHERE connector_id='c'").fetchone()[0])

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
