"""Sanity-check H-1B matching against names whose history is well known."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import h1b

agg, files = h1b.load()
print("files:", files, "| employers:", len(agg))
for name in ["McKinsey & Company", "Boston Consulting Group (BCG)", "Bain & Company", "Deloitte", "PwC", "EY", "KPMG",
             "Accenture", "Oliver Wyman", "Kearney", "L.E.K. Consulting", "Alix Partners", "Capco", "Baringa Partners",
             "Stripe", "OpenAI", "Anthropic", "Notion", "Figma", "Ramp", "Block", "Brex", "Harvey",
             "Abt Global", "Strategy&", "Tata Consultancy Services Limited (TCS)", "Zzyzx Nonexistent Co"]:
    r = h1b.lookup(agg, name)
    print(f"{name[:40]:<40} {r['tier']:<11} initial={r['initial']:<6} cont={r['continuing']:<6} {r['matched'][:2]}")
