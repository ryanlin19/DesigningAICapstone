"""Print a random sample of confident matches so precision can be eyeballed."""
import json
import random
from pathlib import Path

m = json.loads((Path(__file__).resolve().parents[2] / "data" / "spike_matches.json").read_text(encoding="utf-8"))
conf = [x for x in m if not x["review"]]
print(len(conf), "confident matches of", len(m))
random.seed(7)
for x in random.sample(conf, 30):
    print(f"{x['company'][:18]:<18}| {x['title'][:62]:<62}| {x['category'][:14]:<14}| {x['seniority']}")
