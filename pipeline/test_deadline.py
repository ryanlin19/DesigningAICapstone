"""Unit checks for the deadline reader, including phrases that must NOT be read as deadlines."""
import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from deadline import extract

TODAY = datetime.date(2026, 10, 22)
cases = [
    ("Application deadline: October 31, 2026", ("date", "2026-10-31")),
    ("Applications will be accepted until Nov 15.", ("date", "2026-11-15")),
    ("Please apply by 11/30/2026 to be considered", ("date", "2026-11-30")),
    ("The application closes on 15 December 2026.", ("date", "2026-12-15")),
    ("Apply by Jan 9 for the spring cohort", ("date", "2027-01-09")),          # year inferred -> next January
    ("Closing date: 2026-11-05", ("date", "2026-11-05")),
    ("Submit your resume by Friday, Nov. 6th", ("date", "2026-11-06")),
    ("We review applications on a rolling basis.", ("rolling", None)),
    ("Position open until filled", ("rolling", None)),
    ("Applications reviewed as they are received - apply early!", ("rolling", None)),
    ("We encourage you to apply as soon as possible.", ("asap", None)),
    ("Apply ASAP, this role is urgent.", ("asap", None)),
    # must not be read as deadlines:
    ("Bachelor's degree awarded no later than August 2025 in Mechanical Engineering", ("unknown", None)),
    ("Gallup is accepting applications through Oct. 30, 2026, for this full-time role", ("date", "2026-10-30")),
    ("Application deadline information (November 20, 2026) Twilio thinks big", ("date", "2026-11-20")),
    ("Ready to lead? Apply now and change the world around you.", ("unknown", None)),
    ("Apply today and become a Reinventor at Accenture!", ("unknown", None)),
    ("Start date: January 5, 2027. Salary range $150,000 - $180,000.", ("unknown", None)),
    ("Due to the nature of the work, travel is required from March through June.", ("unknown", None)),
    ("Founded on March 3, 2015, we are a leading consultancy.", ("unknown", None)),
    ("Apply by January 1, 2020", ("unknown", None)),                           # long past: ignore
    ("", ("unknown", None)),
]
bad = 0
for text, (kind, date) in cases:
    r = extract(text, posted="2026-10-15", today=TODAY)
    ok = (r["kind"], r["date"]) == (kind, date)
    bad += not ok
    print(("ok   " if ok else "FAIL ") + f"{text[:62]:<62} -> {r['kind']}, {r['date']}" + ("" if ok else f"   (wanted {kind}, {date})"))
s = extract("nothing here", structured="2026-12-01", today=TODAY)
print(("ok   " if s == {"kind": "date", "date": "2026-12-01"} else "FAIL ") + "structured field wins ->", s)
bad += s != {"kind": "date", "date": "2026-12-01"}
print("\nALL PASSED" if not bad else f"\n{bad} FAILED")
sys.exit(1 if bad else 0)
