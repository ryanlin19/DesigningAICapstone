"""Match index for resume matching: reads data/skills.txt and turns each role's description into a short list of weighted skill and
industry terms. The page loads the result (match_index.js) only when someone adds a resume, and reads the resume with the SAME
vocabulary, so a resume and a role are compared in the same terms. Nothing here uses an AI service.

    python pipeline/match_index.py        # prints vocabulary statistics
"""
import json
import math
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAX_SKILLS_PER_ROLE = 30
MAX_INDUSTRIES_PER_ROLE = 3


def normalize(text):
    """Lowercase, and make dashes, quotes and ampersand entities plain so the vocabulary matches them."""
    t = (text or "").lower()
    for a, b in (("–", "-"), ("—", "-"), ("‑", "-"), ("’", "'"), ("‘", "'"), ("&amp;", "&"), (" ", " ")):
        t = t.replace(a, b)
    return t


def load_vocab(path=None):
    """-> {"skills": [{"g","l","s"}], "inds": [{"g","l","s"}]} from data/skills.txt (first definition of a synonym wins)."""
    path = Path(path) if path else ROOT / "data" / "skills.txt"
    skills, inds, target = [], [], None
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("# SKILLS"):
            target = skills
        elif line.startswith("# INDUSTRIES"):
            target = inds
        elif line and not line.startswith("#") and target is not None:
            group, label, syns = [x.strip() for x in line.split("|", 2)]
            target.append({"g": group, "l": label, "s": [x.strip() for x in syns.split(";") if x.strip()]})
    return {"skills": skills, "inds": inds}


def _compile(items):
    """-> (regex, {synonym: index}). Longest synonyms first so "strategic partnerships" wins over "partnerships"."""
    index = {}
    for i, it in enumerate(items):
        for syn in it["s"]:
            index.setdefault(syn, i)
    alts = "|".join(re.escape(s) for s in sorted(index, key=len, reverse=True))
    return re.compile(r"(?<![a-z0-9])(?:" + alts + r")(?![a-z0-9])"), index


class Matcher:
    def __init__(self, vocab=None):
        self.vocab = vocab or load_vocab()
        self.sk_re, self.sk_idx = _compile(self.vocab["skills"])
        self.in_re, self.in_idx = _compile(self.vocab["inds"])

    def counts(self, title, description):
        """-> {"k": {skill index: weight}, "i": {industry index: mentions}} for one role. Weight: mentions (max 3), +2 if the term is in the title."""
        title_t, desc_t = normalize(title), normalize(description)[:15000]
        k, i = Counter(), Counter()
        for m in self.sk_re.findall(desc_t):
            k[self.sk_idx[m]] += 1
        for m in self.in_re.findall(desc_t):
            i[self.in_idx[m]] += 1
        in_title = {self.sk_idx[m] for m in self.sk_re.findall(title_t)}
        in_title_ind = {self.in_idx[m] for m in self.in_re.findall(title_t)}
        for s in in_title:
            k[s] = k.get(s, 0)
        weights = {s: min(3, c) + (2 if s in in_title else 0) for s, c in k.items()}
        inds = {n: c for n, c in i.items() if c >= 2 or n in in_title_ind}
        return {"k": weights, "i": inds}

    def terms_in(self, text):
        """Skill indexes mentioned in a text (used by tests and to mirror what the page does with a resume)."""
        return {self.sk_idx[m] for m in self.sk_re.findall(normalize(text))}


def write_index(per_role, matcher, *folders):
    """per_role: {role url: matcher.counts(...)}. Writes match_index.js into each folder; returns its size in bytes."""
    n = max(1, len(per_role))
    df = Counter(s for m in per_role.values() for s in m["k"])
    idf = {s: min(4.0, max(0.3, math.log((n + 1) / (df.get(s, 0) + 1)) + 0.3)) for s in range(len(matcher.vocab["skills"]))}
    roles = {}
    for url, m in per_role.items():
        top = sorted(m["k"].items(), key=lambda kv: -kv[1] * idf[kv[0]])[:MAX_SKILLS_PER_ROLE]
        inds = [i for i, _ in sorted(m["i"].items(), key=lambda kv: -kv[1])[:MAX_INDUSTRIES_PER_ROLE]]
        roles[url] = [[x for pair in top for x in pair], inds]        # [skill, weight, skill, weight, ...], [industry, ...]
    payload = {"v": 1,
               "skills": [{"l": s["l"], "g": s["g"], "s": s["s"], "w": round(idf[i], 2)} for i, s in enumerate(matcher.vocab["skills"])],
               "inds": [{"l": s["l"], "s": s["s"]} for s in matcher.vocab["inds"]],
               "roles": roles}
    text = "window.MATCH_INDEX = " + json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + ";"
    for folder in folders:
        Path(folder).mkdir(exist_ok=True)
        (Path(folder) / "match_index.js").write_text(text, encoding="utf-8")
    return len(text.encode("utf-8"))


if __name__ == "__main__":
    v = load_vocab()
    seen = Counter(s for it in v["skills"] for s in it["s"])
    print(len(v["skills"]), "skills,", len(v["inds"]), "industries;", sum(len(i["s"]) for i in v["skills"]), "skill synonyms")
    print("synonyms defined twice among skills:", [s for s, c in seen.items() if c > 1])
