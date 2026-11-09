"""Turn messy job-location strings into the place names used by the board's location filter.

"Chicago - 550 Van Buren", "CHICAGO" and "Chicago, IL" all become "Chicago". Neighbouring towns are grouped into the
metro areas job seekers think in ("McLean, VA" -> "Washington, DC area"). One string can give several places
("San Francisco or Seattle"), and anything remote or nationwide becomes "Remote / US-wide".
"""
import re

REMOTE_LABEL = "Remote / US-wide"

# (place shown in the filter, pattern). Every pattern that matches counts.
METROS = [
    ("New York City area", r"\bnew york\b|\bnyc\b|manhattan|brooklyn|jersey city|hoboken"),
    ("San Francisco Bay Area", r"san fran[a-z]*|\bsf\b|bay area|oakland|berkeley|san mateo|redwood city|palo alto|menlo park|"
                               r"mountain view|sunnyvale|santa clara|san jose|fremont|cupertino|foster city|burlingame|emeryville|silicon valley|"
                               r"walnut creek|pleasanton|san ramon|hayward|alameda|livermore"),
    ("Washington, DC area", r"^dc\b|washington,? ?d\.?c|\bd\.c\b|district of columbia|arlington,? ?va|\bmclean\b|\breston\b|tysons|"
                            r"alexandria,? ?va|bethesda|rockville|herndon|springfield,? ?va|fairfax|falls church|chantilly|vienna,? ?va|annapolis"),
    ("Los Angeles area", r"los angeles|santa monica|culver city|el segundo|pasadena|burbank|long beach|playa vista|beverly hills|irvine|orange county"),
    ("Seattle area", r"seattle|bellevue|redmond|kirkland"),
    ("Boston area", r"boston|cambridge|somerville|waltham|burlington,? ?ma|quincy"),
    ("Chicago", r"chicago|\bchi\b"),
    ("Dallas-Fort Worth", r"dallas|plano|irving|fort worth"),
    ("Houston", r"houston"),
    ("Austin", r"austin"),
    ("Atlanta", r"atlanta"),
    ("Philadelphia", r"philadelphia"),
    ("Charlotte", r"charlotte"),
    ("Miami area", r"miami|f(?:or)?t\.? lauderdale|boca raton"),
    ("Tampa", r"tampa"),
    ("Orlando", r"orlando"),
    ("Denver", r"denver|boulder"),
    ("Pittsburgh", r"pittsburgh"),
    ("Minneapolis-St. Paul", r"minneapolis|st\.? paul"),
    ("Detroit area", r"detroit|southfield|ann arbor|troy,? ?mi"),
    ("San Diego", r"san diego"),
    ("Portland", r"portland|beaverton|hillsboro"),
    ("St. Louis area", r"st\.? louis|belleville,? ?il"),
    ("Salt Lake City", r"salt lake"),
    ("Nashville", r"nashville"),
    ("Raleigh-Durham", r"raleigh|durham"),
    ("Columbus", r"columbus"),
    ("Cleveland", r"cleveland"),
    ("Cincinnati", r"cincinnati"),
    ("Baltimore", r"baltimore"),
    ("Phoenix area", r"phoenix|scottsdale|tempe"),
    ("Las Vegas", r"las vegas"),
    ("Indianapolis", r"indianapolis"),
    ("Kansas City", r"kansas city"),
    ("New Orleans", r"new orleans"),
    ("Stamford, CT", r"stamford"),
    ("Princeton, NJ", r"princeton"),
]
_METRO_RES = [(label, re.compile(pat, re.I)) for label, pat in METROS]
_REMOTE = re.compile(r"remote|virtual|work from home|anywhere", re.I)
_NATIONWIDE = {"united states", "usa", "us", "u.s.", "u.s", "united states of america", "us-wide", "nationwide"}
_STATES = {s.lower() for s in (
    "Alabama Alaska Arizona Arkansas California Colorado Connecticut Delaware Florida Georgia Hawaii Idaho Illinois Indiana Iowa "
    "Kansas Kentucky Louisiana Maine Maryland Massachusetts Michigan Minnesota Mississippi Missouri Montana Nebraska Nevada "
    "Ohio Oklahoma Oregon Pennsylvania Tennessee Texas Utah Vermont Virginia Washington Wisconsin Wyoming").split()}
_STATES |= {"new hampshire", "new jersey", "new mexico", "new york", "north carolina", "north dakota", "rhode island",
            "south carolina", "south dakota", "west virginia"}
_ABBR = dict(zip(
    "al ak az ar ca co ct de fl ga hi id il in ia ks ky la me md ma mi mn ms mo mt ne nv nh nj nm ny nc nd oh ok or pa ri sc sd tn tx ut vt va wa wv wi wy".split(),
    ["Alabama", "Alaska", "Arizona", "Arkansas", "California", "Colorado", "Connecticut", "Delaware", "Florida", "Georgia", "Hawaii",
     "Idaho", "Illinois", "Indiana", "Iowa", "Kansas", "Kentucky", "Louisiana", "Maine", "Maryland", "Massachusetts", "Michigan",
     "Minnesota", "Mississippi", "Missouri", "Montana", "Nebraska", "Nevada", "New Hampshire", "New Jersey", "New Mexico", "New York",
     "North Carolina", "North Dakota", "Ohio", "Oklahoma", "Oregon", "Pennsylvania", "Rhode Island", "South Carolina", "South Dakota",
     "Tennessee", "Texas", "Utah", "Vermont", "Virginia", "Washington", "West Virginia", "Wisconsin", "Wyoming"]))
_NOT_A_PLACE = {"hybrid", "office", "hq", "corp", "multiple offices", "multiple locations", "various", "other", "west coast",
                "east coast", ""}


def labels(name):
    """Place names for one location string (possibly none, e.g. a bare "Hybrid")."""
    s = (name or "").strip()
    out = []
    for label, rx in _METRO_RES:
        if rx.search(s):
            out.append(label)
    if _REMOTE.search(s) or s.lower() in _NATIONWIDE:
        out.append(REMOTE_LABEL)
    if out:
        return out

    # no known metro: fall back to the first meaningful piece of the string
    if s.lower() in _ABBR:                              # a bare state code: "IN"
        return [_ABBR[s.lower()] + " (statewide)"]
    m = re.match(r"^([A-Za-z]{2})\s*[-–—]\s*(.+)$", s)   # "KS - Overland Park": a state code in front of the city
    if m and m.group(1).lower() in _ABBR:
        s = m.group(2)
    m = re.match(r"^([A-Za-z .]+)-(.+)$", s)           # "Indiana-Johnson County" -> "Johnson County"
    if m and m.group(1).strip().lower() in _STATES:
        s = m.group(2)
    first = re.split(r"\s+[-–—]\s+|,|\(|\s+or\s+|/|;", s)[0].strip()
    if first.lower() in _NOT_A_PLACE or first.lower() in _NATIONWIDE:
        return []
    if first.lower() in _STATES:
        return [first.title() + " (statewide)"]
    return [first.title() if first.isupper() else first]


def place_labels(names):
    """Distinct place names for all of a role's location strings, in first-seen order."""
    seen = []
    for n in names:
        for lab in labels(n):
            if lab not in seen:
                seen.append(lab)
    return seen
