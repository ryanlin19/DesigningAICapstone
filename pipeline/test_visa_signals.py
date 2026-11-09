"""Checks for the sponsorship wording rules, including the immigration-support signal and its negations."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from classify import immigration_support

cases = [
    # (text, offers, declines)
    ("Benefits include in-house immigration support for foreign nationals and those conducting international business travel.", True, False),
    ("We offer visa assistance and relocation support.", True, False),
    ("Relocation and visa support is available for the right candidate.", True, False),
    ("Our team will help with your visa application.", True, False),
    ("Employees receive relocation & immigration services.", True, False),
    # declines
    ("We do not provide visa support for this role.", False, True),
    ("Unfortunately we are unable to offer immigration assistance.", False, True),
    ("No visa support is available.", False, True),
    ("We cannot provide work authorization assistance.", False, True),
    # no signal at all
    ("You must be authorized to work in the United States.", False, False),
    ("Join our team and support clients with strategy work.", False, False),
    ("", False, False),
]
from classify import YES_SPONSOR, NO_SPONSOR

# the stronger "we will sponsor" wording
yes_cases = [
    ("If visa sponsorship is required for work authorization, please note that the company in collaboration with immigration "
     "counsel will manage and submit all necessary legal filings on behalf of the candidate.", True),
    ("If you require sponsorship, we will provide it for the right candidate.", True),
    ("We will sponsor H-1B visas.", True),
    ("If sponsorship is required, we will not be able to provide it.", False),
    ("If you require sponsorship, we cannot provide it for this role.", False),
    ("Candidates must be authorized to work in the US.", False),
]
bad = 0
for text, want in yes_cases:
    got = bool(YES_SPONSOR.search(text)) and not NO_SPONSOR.search(text)
    ok = got == want
    bad += not ok
    print(("ok   " if ok else "FAIL ") + f"[sponsors?] {text[:66]:<66} -> {got}")
print()
for text, want_offer, want_decline in cases:
    got = immigration_support(text)
    ok = got == (want_offer, want_decline)
    bad += not ok
    print(("ok   " if ok else "FAIL ") + f"{text[:78]:<78} -> offers={got[0]}, declines={got[1]}")
print("\nALL PASSED" if not bad else f"\n{bad} FAILED")
sys.exit(1 if bad else 0)
