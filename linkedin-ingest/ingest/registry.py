"""Company registry: the knowledge source, used by retrieval.

It holds every organization seen so far (seeded with common employers and the
cohort's target companies, then grown by every export). For a new name we
retrieve the few registry entries that could plausibly be the same organization
and only those go to the model, so the prompt stays small however large the
registry grows.
"""
import csv
from pathlib import Path

from . import rules
from .config import MAX_CANDIDATES
from .db import now

SEED = Path(__file__).resolve().parents[1] / "data" / "seed_companies.csv"


def seed(con, path=SEED):
    """Load seed companies and aliases. Safe to run repeatedly."""
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            norm = rules.normalize_company(row["company"])
            if not norm:
                continue
            add_company(con, norm, row["company"], source="seed",
                        parent=rules.normalize_company(row.get("parent") or "") or None)
            for alias in filter(None, (row.get("aliases") or "").split("|")):
                a = rules.normalize_company(alias)
                if a:
                    add_alias(con, a, norm, "seed")
    con.commit()


def add_company(con, norm, display, source, parent=None):
    con.execute("INSERT OR IGNORE INTO companies(company_norm, display_name, parent_norm, source, created_at)"
                " VALUES (?,?,?,?,?)", (norm, display, parent, source, now()))
    add_alias(con, norm, norm, source)


def add_alias(con, alias, norm, source):
    con.execute("INSERT OR IGNORE INTO aliases(alias, company_norm, source) VALUES (?,?,?)",
                (alias, norm, source))
    key = rules.compress(alias)
    if key and key != alias:
        con.execute("INSERT OR IGNORE INTO aliases(alias, company_norm, source) VALUES (?,?,?)",
                    (key, norm, source))


def lookup(con, norm):
    """Exact, alias or compressed-key match. Deterministic. Returns company_norm or None."""
    for key in (norm, rules.compress(norm)):
        row = con.execute("SELECT company_norm FROM aliases WHERE alias = ?", (key,)).fetchone()
        if row:
            return row["company_norm"]
    return None


def retrieve(con, norm, k=MAX_CANDIDATES):
    """Return up to k registry companies that might be the same organization as `norm`."""
    scored = []
    new_tokens, new_tri = rules.distinctive_tokens(norm), rules.trigrams(norm)
    for row in con.execute("SELECT company_norm, parent_norm FROM companies"):
        name = row["company_norm"]
        if name == norm or not rules.is_candidate(norm, name):
            continue
        score = 2 * len(new_tokens & rules.distinctive_tokens(name)) + rules.jaccard(new_tri, rules.trigrams(name))
        scored.append((score, name, row["parent_norm"]))
    scored.sort(reverse=True)
    return [{"company_norm": n, "parent_norm": p} for _, n, p in scored[:k]]
