"""Map regions for job locations: the metro areas of pipeline/places.py, a few more large cities, one
"Elsewhere in <state>" region per state, and Remote / US-wide. Each has map coordinates.

    regions_for(location_names, remote) -> list of region names for one job
    REGIONS                              -> [{name, lat, lon, kind}] for drawing the map

A job listing several regions counts 1/n in each on the map (weighting), so a posting copied to 25 cities
doesn't outweigh 25 single-city postings.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
import places  # noqa: E402

REMOTE = places.REMOTE_LABEL
UNKNOWN = "Location not given"

# Coordinates (approximate city centres) for places.py's metros.
_METRO_XY = {
    "New York City area": (40.71, -74.01), "San Francisco Bay Area": (37.62, -122.20), "Washington, DC area": (38.90, -77.04),
    "Los Angeles area": (34.05, -118.24), "Seattle area": (47.61, -122.33), "Boston area": (42.36, -71.06), "Chicago": (41.88, -87.63),
    "Dallas-Fort Worth": (32.78, -96.80), "Houston": (29.76, -95.37), "Austin": (30.27, -97.74), "Atlanta": (33.75, -84.39),
    "Philadelphia": (39.95, -75.17), "Charlotte": (35.23, -80.84), "Miami area": (25.76, -80.19), "Tampa": (27.95, -82.46),
    "Orlando": (28.54, -81.38), "Denver": (39.74, -104.99), "Pittsburgh": (40.44, -79.99), "Minneapolis-St. Paul": (44.98, -93.27),
    "Detroit area": (42.33, -83.05), "San Diego": (32.72, -117.16), "Portland": (45.52, -122.68), "St. Louis area": (38.63, -90.20),
    "Salt Lake City": (40.76, -111.89), "Nashville": (36.16, -86.78), "Phoenix area": (33.45, -112.07), "Raleigh-Durham": (35.84, -78.78),
    "Columbus": (39.96, -83.00), "Cleveland": (41.50, -81.69), "Cincinnati": (39.10, -84.51), "Kansas City": (39.10, -94.58),
    "Indianapolis": (39.77, -86.16), "Baltimore": (39.29, -76.61), "Las Vegas": (36.17, -115.14),
    "Stamford, CT": (41.05, -73.54), "Princeton, NJ": (40.35, -74.66), "New Orleans": (29.95, -90.07),
}
# Shorthand that multi-city postings use ("SF, NYC, CHI, ATL, SEA") and places.py doesn't read.
_SHORTHAND = [("Atlanta", re.compile(r"\bATL\b")), ("Seattle area", re.compile(r"\bSEA\b"))]
# More large cities that places.py leaves as plain city names.
_EXTRA = [
    ("Sacramento", 38.58, -121.49, r"\bsacramento\b"), ("Memphis", 35.15, -90.05, r"\bmemphis\b"),
    ("Hartford", 41.76, -72.68, r"\bhartford\b"), ("Milwaukee", 43.04, -87.91, r"\bmilwaukee\b"),
    ("Oklahoma City", 35.47, -97.52, r"\boklahoma city\b"), ("San Antonio", 29.42, -98.49, r"\bsan antonio\b"),
    ("Des Moines", 41.59, -93.62, r"\bdes moines\b"), ("Richmond", 37.54, -77.44, r"\brichmond,? ?(va|virginia)\b|^richmond$"),
    ("Jacksonville", 30.33, -81.66, r"\bjacksonville\b"), ("Louisville", 38.25, -85.76, r"\blouisville\b"),
    ("Albany", 42.65, -73.75, r"\balbany\b"), ("Rochester", 43.16, -77.61, r"\brochester\b"),
    ("Grand Rapids", 42.96, -85.67, r"\bgrand rapids\b"), ("Boise", 43.62, -116.21, r"\bboise\b"),
    ("Omaha", 41.26, -95.93, r"\bomaha\b"), ("Birmingham", 33.52, -86.80, r"\bbirmingham\b"),
    ("Buffalo", 42.89, -78.88, r"\bbuffalo\b"),
    ("Honolulu", 21.31, -157.86, r"\bhonolulu\b"), ("Anchorage", 61.22, -149.90, r"\banchorage\b"),
]
_EXTRA_RES = [(n, re.compile(rx, re.I)) for n, _, _, rx in _EXTRA]

# State centroids, for "Elsewhere in <state>".
_STATE_XY = {
    "Alabama": (32.8, -86.8), "Alaska": (64.0, -150.0), "Arizona": (34.3, -111.7), "Arkansas": (34.9, -92.4), "California": (37.2, -119.5),
    "Colorado": (39.0, -105.5), "Connecticut": (41.6, -72.7), "Delaware": (39.0, -75.5), "Florida": (28.6, -82.4), "Georgia": (32.7, -83.4),
    "Hawaii": (20.8, -156.3), "Idaho": (44.4, -114.6), "Illinois": (40.0, -89.2), "Indiana": (39.9, -86.3), "Iowa": (42.1, -93.5),
    "Kansas": (38.5, -98.4), "Kentucky": (37.5, -85.3), "Louisiana": (31.1, -92.0), "Maine": (45.4, -69.2), "Maryland": (39.0, -76.8),
    "Massachusetts": (42.3, -71.8), "Michigan": (44.3, -85.4), "Minnesota": (46.3, -94.3), "Mississippi": (32.7, -89.7),
    "Missouri": (38.4, -92.5), "Montana": (47.0, -109.6), "Nebraska": (41.5, -99.8), "Nevada": (39.3, -116.6), "New Hampshire": (43.7, -71.6),
    "New Jersey": (40.1, -74.7), "New Mexico": (34.4, -106.1), "New York": (42.9, -75.5), "North Carolina": (35.6, -79.4),
    "North Dakota": (47.5, -100.5), "Ohio": (40.3, -82.8), "Oklahoma": (35.6, -97.5), "Oregon": (43.9, -120.6), "Pennsylvania": (40.9, -77.8),
    "Rhode Island": (41.7, -71.5), "South Carolina": (33.9, -80.9), "South Dakota": (44.4, -100.2), "Tennessee": (35.9, -86.4),
    "Texas": (31.5, -99.3), "Utah": (39.3, -111.7), "Vermont": (44.0, -72.7), "Virginia": (37.5, -78.9), "Washington": (47.4, -120.5),
    "West Virginia": (38.6, -80.6), "Wisconsin": (44.6, -89.9), "Wyoming": (43.0, -107.5), "District of Columbia": (38.9, -77.0),
}
_ABBR = {k: v for k, v in places._ABBR.items()}
_ABBR["dc"] = "District of Columbia"
_STATE_NAME = re.compile(r"\b(" + "|".join(sorted((s.lower() for s in _STATE_XY), key=len, reverse=True)) + r")\b", re.I)
_STATE_ABBR = re.compile(r"(?:,|\s-|^)\s*([A-Z]{2})\b(?!\w)")


def elsewhere(state):
    return f"Elsewhere in {state}"


REGIONS = ([{"name": n, "lat": xy[0], "lon": xy[1], "kind": "metro"} for n, xy in _METRO_XY.items()] +
           [{"name": n, "lat": la, "lon": lo, "kind": "metro"} for n, la, lo, _ in _EXTRA] +
           [{"name": elsewhere(s), "lat": xy[0], "lon": xy[1], "kind": "state"} for s, xy in _STATE_XY.items()] +
           [{"name": REMOTE, "lat": None, "lon": None, "kind": "remote"}, {"name": UNKNOWN, "lat": None, "lon": None, "kind": "unknown"}])
_KNOWN = {r["name"] for r in REGIONS}


def _state_of(s):
    m = _STATE_ABBR.search(s)
    if m and m.group(1).lower() in _ABBR:
        return _ABBR[m.group(1).lower()]
    m = _STATE_NAME.search(s)
    if m:
        name = m.group(1).title().replace("Of", "of")
        return name if name in _STATE_XY else None
    return None


def _one(s):
    """Regions for one location string."""
    out = [lab for lab in places.labels(s) if lab in _KNOWN]                  # a metro, or Remote / US-wide
    out += [n for n, rx in _SHORTHAND if rx.search(s) and n not in out]
    if any(lab != REMOTE for lab in out):
        return out
    hits = [n for n, rx in _EXTRA_RES if rx.search(s)]
    if hits:
        return out + hits
    state = _state_of(s)
    return out + ([elsewhere(state)] if state else [])


def regions_for(location_names, remote=False):
    seen = []
    for s in location_names or []:
        for r in _one(s or ""):
            if r not in seen:
                seen.append(r)
    if remote and REMOTE not in seen:
        seen.append(REMOTE)
    return seen or [UNKNOWN]
