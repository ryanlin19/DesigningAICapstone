"""The only two places the pipeline uses a model. Both receive company names and
job titles only, never a person's name, email or profile link.

1. classify_titles: job titles the rules could not place, with the company as context.
2. resolve_company: a new company name plus the registry candidates retrieved for it.
"""
import json

from . import llm
from .config import BUCKETS

TITLE_SYSTEM = (
    "You classify LinkedIn job titles into one job-function bucket. Use the company to "
    "disambiguate generic titles (an 'Associate' at an investment bank is finance, at a "
    "strategy firm is consulting). If the text is not a job, or is truly unclear, use 'other'. "
    "Buckets:\n" + "\n".join(f"- {k}: {v}" for k, v in BUCKETS.items()) +
    "\nReply with JSON only: a list of objects {\"i\": <index>, \"bucket\": <bucket>}, one per input, same order."
)

COMPANY_SYSTEM = (
    "You decide whether a company name refers to an organization already in a registry. "
    "Answer for the purpose of warm introductions: would someone at the new name realistically "
    "count as someone at the candidate?\n"
    "- same: the same organization under another name, spelling, legal form or regional member firm "
    "of the same brand.\n"
    "- subsidiary: a distinct unit, school, campus or subsidiary owned by the candidate.\n"
    "- different: anything else, including student clubs or unrelated firms that share a word.\n"
    "Reply with JSON only: {\"decision\": \"same|subsidiary|different\", \"match\": <candidate company_norm "
    "or null>, \"reason\": <under 20 words>}."
)


def classify_titles(items, model, caller=llm.call_json, **log):
    """items: list of (title, company_norm). Returns (list of buckets, stats)."""
    payload = [{"i": i, "title": t, "company": c} for i, (t, c) in enumerate(items)]

    def validate(data):
        if not isinstance(data, list) or len(data) != len(items):
            raise ValueError(f"expected a list of {len(items)} objects")
        out = [None] * len(items)
        for obj in data:
            i, b = int(obj["i"]), obj["bucket"]
            if b not in BUCKETS:
                raise ValueError(f"unknown bucket {b!r}")
            out[i] = b
        if None in out:
            raise ValueError("missing indexes")
        return out

    return caller(model, TITLE_SYSTEM, json.dumps(payload, ensure_ascii=False), validate,
                  task="classify_titles", **log)


def resolve_company(name, candidates, model, caller=llm.call_json, **log):
    """Returns ({decision, match, reason}, stats). `match` is always one of the candidates or None."""
    allowed = {c["company_norm"] for c in candidates}
    user = json.dumps({"new_name": name, "candidates": candidates}, ensure_ascii=False)

    def validate(data):
        d = data.get("decision")
        if d not in ("same", "subsidiary", "different"):
            raise ValueError(f"bad decision {d!r}")
        m = data.get("match")
        if d == "different":
            m = None
        elif m not in allowed:
            raise ValueError(f"match {m!r} is not one of the candidates")
        return {"decision": d, "match": m, "reason": str(data.get("reason", ""))[:200]}

    return caller(model, COMPANY_SYSTEM, user, validate, task="resolve_company", max_tokens=300, **log)
