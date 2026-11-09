"""Checks for how a posting's location string becomes places plus a remote-friendly flag."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build import split_locations

cases = [
    # (location string, expected places, expected remote flag)
    ("San Francisco · Remote", ["San Francisco"], True),          # Ashby: a city posting flagged remote-eligible
    ("New York · Remote", ["New York"], True),
    ("San Francisco · New York · Remote", ["San Francisco", "New York"], True),
    ("US - San Francisco · Remote", ["US - San Francisco"], True),
    ("Remote", ["Remote"], True),                                      # purely remote keeps its own place
    ("Remote - US", ["Remote"], True),
    ("Remote · Remote - US", ["Remote"], True),
    ("San Francisco", ["San Francisco"], False),
    ("McLean, VA; Remote - US; Arlington, VA", ["McLean, VA", "Arlington, VA"], True),
    ("Remote - SF Bay Area", ["Remote - SF Bay Area"], False),        # remote but tied to a place: kept as a place
    ("", ["Location not listed"], False),
]
bad = 0
for text, want_places, want_remote in cases:
    got = split_locations(text)
    ok = got == (want_places, want_remote)
    bad += not ok
    print(("ok   " if ok else "FAIL ") + f"{text!r:<44} -> {got}" + ("" if ok else f"   (wanted {(want_places, want_remote)})"))
print("\nALL PASSED" if not bad else f"\n{bad} FAILED")
sys.exit(1 if bad else 0)
