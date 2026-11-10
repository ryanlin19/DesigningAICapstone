"""Resume matching: the skills vocabulary and the match index (pipeline/match_index.py).
Run: python pipeline/test_match.py"""
import json
import sys
import tempfile
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import match_index as M

bad = 0


def check(name, ok, detail=""):
    global bad
    if not ok:
        bad += 1
        print(f"FAIL {name} {detail}")


vocab = M.load_vocab()
check("vocabulary is not empty", len(vocab["skills"]) > 80 and len(vocab["inds"]) > 10)
for kind in ("skills", "inds"):
    dup = [s for s, c in Counter(x for it in vocab[kind] for x in it["s"]).items() if c > 1]
    check(f"no synonym defined twice in {kind}", not dup, str(dup))

m = M.Matcher(vocab)
labels = [s["l"] for s in vocab["skills"]]
inds = [s["l"] for s in vocab["inds"]]


def skills_of(text):
    return {labels[i] for i in m.terms_in(text)}


check("finds SQL, Excel and P&L", {"SQL", "Excel", "P&L management"} <= skills_of("Wrote SQL and MySQL queries, built Excel models and owned the P&L."))
check("whole words only: 'excellent' is not Excel", "Excel" not in skills_of("An excellent communicator."))
check("longest synonym wins", "Corporate development" in skills_of("Led strategic partnerships and corporate development work."))
check("dashes and ampersands are normalised", "FP&A" in skills_of("Head of FP&amp;A – budgeting"))

c = m.counts("Senior Product Manager, Payments", "You will own the product roadmap and run A/B testing. We serve fintech and banking customers. SQL required. Fintech.")
w = {labels[k]: v for k, v in c["k"].items()}
check("title terms weigh more than one mention", w.get("Product management", 0) == 2 and w.get("SQL", 0) == 1, str(w))
check("an industry needs two mentions", any(inds[i] == "Fintech" for i in c["i"]), str(c["i"]))

with tempfile.TemporaryDirectory() as tmp:
    size = M.write_index({"https://example.com/job/1": c}, m, tmp)
    text = (Path(tmp) / "match_index.js").read_text(encoding="utf-8")
    data = json.loads(text[text.index("{"):text.rindex("}") + 1])
    check("index has the role", "https://example.com/job/1" in data["roles"])
    check("index carries the vocabulary for the page", len(data["skills"]) == len(vocab["skills"]) and "s" in data["skills"][0])
    check("rare skills get a higher weight than common ones", max(s["w"] for s in data["skills"]) >= min(s["w"] for s in data["skills"]))

print("ok" if not bad else f"{bad} failed")
sys.exit(1 if bad else 0)
