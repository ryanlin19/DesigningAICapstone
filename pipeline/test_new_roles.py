"""Role types MBAs also go into (product management, business development, partnerships, growth, general management, account executive).
Run: python pipeline/test_new_roles.py"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import classify as C
from build import fold_ae_title

CASES = [
    ("Product Manager", "Product Management"), ("Senior Product Manager, Payments", "Product Management"),
    ("Product Manager, Growth", "Product Management"), ("Technical Product Manager", "Product Management"),
    ("Director, Product Management", None), ("Staff Product Manager", None),
    ("Business Development Manager", "Business Development"), ("Business Development Representative", None),
    ("Sales Development Representative", None),
    ("Partnerships Manager", "Partnerships"), ("Strategic Partner Manager", "Partnerships"), ("HR Business Partner Manager", None), ("Employee Success Business Partner Lead", None),
    ("Partner", None), ("Senior Partner, Consulting", None), ("Head of Partnerships", None),
    ("Growth Manager", "Growth"), ("Growth Marketing Manager", "Growth"), ("Head of Growth", None), ("Growth Analyst", None),
    ("Growth Strategy Lead", "GTM / Revenue Ops"),
    ("General Manager, Starlink", "General Management"),
    ("Enterprise Account Executive", "Account Executive"), ("Account Executive, Mid-Market", "Account Executive"),
    ("Account Manager", None), ("Software Engineer", None), ("Chief of Staff", "Chief of Staff"),
]
bad = 0
for title, want in CASES:
    r = C.classify({"title": title, "location": "New York, NY", "description": ""}, False)
    got = r["category"] if r else None
    if got != want:
        bad += 1
        print(f"FAIL {title!r}: wanted {want}, got {got}")
print("ok" if not bad else f"{bad} failed")


# Account executive postings that differ only by territory are folded into one title.
FOLD = [
    ("Territory Account Executive, Atlanta", "Atlanta, GA", "Territory Account Executive"),
    ("Bilingual Strategic Cuisines Account Executive (Spanish) - Brownsville, TX", "Brownsville, TX", "Bilingual Strategic Cuisines Account Executive"),
    ("Enterprise Account Executive Mexico", "Mexico City", "Enterprise Account Executive"),
    ("Enterprise Account Executive, KS/MO", "Kansas City, MO", "Enterprise Account Executive"),
    ("Federal Account Executive, DHS", "Washington, DC", "Federal Account Executive, DHS"),
]
bad2 = 0
for title, loc, want in FOLD:
    got = fold_ae_title(title, loc)
    if got != want:
        bad2 += 1
        print(f"FAIL fold {title!r}: wanted {want!r}, got {got!r}")
print("fold ok" if not bad2 else f"{bad2} fold failures")
sys.exit(1 if (bad or bad2) else 0)
