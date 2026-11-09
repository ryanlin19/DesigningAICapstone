"""Checks for reading pay ranges and years of experience out of posting text."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from classify import _min_years
from salary import from_text

salary_cases = [
    ("New York Pay Range $147,000 &mdash; $170,000 USD", ({"min": 147000, "max": 170000, "currency": "USD"}, False)),
    ("Base salary: $120K - $150K plus bonus", ({"min": 120000, "max": 150000, "currency": "USD"}, False)),
    ("The salary range is $110,000 to $140,000 in Chicago and $130,000 to $160,000 in New York.",
     ({"min": 110000, "max": 140000, "currency": "USD"}, True)),
    ("Sign-on bonus $20,000 - $30,000", (None, False)),
    ("Hourly $45 - $60 per hour", (None, False)),
    ("We pay well and offer benefits.", (None, False)),
]
years_cases = [
    ("You have... 6+ years in sales strategy, sales planning. Tuition reimbursement for continuing education (upon 2 years of service)", 6),
    ("At least 3-4 years of relevant experience, ideally with a top firm", 3),
    ("Minimum of 5 &#43; years in management consulting", 5),
    ("We were founded 20 years ago. 4+ years of experience required.", 4),
    ("No requirement stated here.", None),
]
bad = 0
for text, want in salary_cases:
    got = from_text(text)
    ok = got == want
    bad += not ok
    print(("ok   " if ok else "FAIL ") + f"salary {text[:50]!r} -> {got}" + ("" if ok else f" (wanted {want})"))
for text, want in years_cases:
    got = _min_years(text)
    ok = got == want
    bad += not ok
    print(("ok   " if ok else "FAIL ") + f"years  {text[:50]!r} -> {got}" + ("" if ok else f" (wanted {want})"))
print("\nALL PASSED" if not bad else f"\n{bad} FAILED")
sys.exit(1 if bad else 0)
