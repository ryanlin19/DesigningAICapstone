"""Application deadline for a posting.

Order of evidence: a structured field from the job system (Greenhouse's application_deadline), then a date near a
deadline phrase in the posting text, then "rolling", then "ASAP". Anything else is "unknown" (the board tells people to
apply ASAP in that case).
"""
import datetime
import re

UNKNOWN_LABEL = "Unknown but apply ASAP"

_MON = (r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|"
        r"sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)")
_MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "oct": 10,
           "nov": 11, "dec": 12}

_DATE = (
    # (?!\d) after each day stops "August 2025" being read as "August 20" + "25".
    rf"(?:(?P<mon1>{_MON})\.?\s+(?P<d1>\d{{1,2}})(?!\d)(?:st|nd|rd|th)?(?:,?\s+(?P<y1>20\d{{2}}))?"
    rf"|(?<!\d)(?P<d2>\d{{1,2}})(?!\d)(?:st|nd|rd|th)?\s+(?:of\s+)?(?P<mon2>{_MON})\.?(?:,?\s+(?P<y2>20\d{{2}}))?"
    rf"|(?<!\d)(?P<m3>\d{{1,2}})/(?P<d3>\d{{1,2}})(?!\d)(?:/(?P<y3>\d{{4}}|\d{{2}}))?"
    rf"|(?P<y4>20\d{{2}})-(?P<m4>\d{{2}})-(?P<d4>\d{{2}}))"
)

# A deadline-style phrase, then (within the same sentence) a date.
_CUE = (r"(?:deadline|apply\s+(?:by|before)|applications?(?:\s+\w+){0,3}?\s+(?:due|close[sd]?|closing|accepted|reviewed)|"
        r"(?:closing|close|due)\s+date|last\s+day\s+to\s+apply|accept(?:ing|ed)?\s+applications?|no\s+later\s+than|"
        r"must\s+(?:apply|submit)[^.\n]{0,20}\bby|submit[^.\n]{0,30}\bby)")
_DATED = re.compile(rf"(?i){_CUE}[^.\n;]{{0,60}}?\b{_DATE}")

_ROLLING = re.compile(r"(?i)rolling\s+(?:basis|admission|review|application|hiring|deadline|recruit)|on\s+a\s+rolling|"
                      r"ongoing\s+basis|until\s+(?:the\s+)?(?:position|role|job|opening)s?\s+(?:is|are)\s+filled|"
                      r"open\s+until\s+filled|reviewed\s+as\s+(?:they\s+are\s+)?received")
# Only explicit urgency. "Apply now" / "Apply today" is boilerplate call-to-action text (Accenture ends every posting
# with it), so it does not count.
_ASAP = re.compile(r"(?i)\bASAP\b|as\s+soon\s+as\s+possible|apply\s+early|encourage[^.\n]{0,40}apply\s+(?:early|soon)")


def _to_date(g, ref):
    """Turn a regex match's named groups into a date, inferring a missing year relative to `ref`."""
    try:
        if g.get("mon1"):
            month, day, year = _MONTHS[g["mon1"][:3].lower()], int(g["d1"]), g.get("y1")
        elif g.get("mon2"):
            month, day, year = _MONTHS[g["mon2"][:3].lower()], int(g["d2"]), g.get("y2")
        elif g.get("m3"):
            month, day, year = int(g["m3"]), int(g["d3"]), g.get("y3")
            if month > 12 >= day:          # looks like dd/mm
                month, day = day, month
            if year and len(year) == 2:
                year = "20" + year
        else:
            return datetime.date(int(g["y4"]), int(g["m4"]), int(g["d4"]))
        if year:
            return datetime.date(int(year), month, day)
        d = datetime.date(ref.year, month, day)
        return d if d >= ref - datetime.timedelta(days=45) else datetime.date(ref.year + 1, month, day)
    except (ValueError, KeyError, TypeError):
        return None


def extract(text, posted=None, structured=None, today=None):
    """-> {"kind": "date" | "rolling" | "asap" | "unknown", "date": "YYYY-MM-DD" | None}"""
    today = today or datetime.date.today()
    try:
        ref = datetime.date.fromisoformat(posted) if posted else today
    except ValueError:
        ref = today
    lo, hi = today - datetime.timedelta(days=120), today + datetime.timedelta(days=540)

    if structured:
        try:
            d = datetime.date.fromisoformat(str(structured)[:10])
            if lo <= d <= hi:
                return {"kind": "date", "date": d.isoformat()}
        except ValueError:
            pass
    text = text or ""
    for m in _DATED.finditer(text):
        d = _to_date(m.groupdict(), ref)
        if d and lo <= d <= hi:
            return {"kind": "date", "date": d.isoformat()}
    if _ROLLING.search(text):
        return {"kind": "rolling", "date": None}
    if _ASAP.search(text):
        return {"kind": "asap", "date": None}
    return {"kind": "unknown", "date": None}


def merge(a, b):
    """Combine the deadlines of two postings of the same role: earliest date, else rolling, else asap, else unknown."""
    if not a:
        return b
    if not b:
        return a
    dates = [x["date"] for x in (a, b) if x["kind"] == "date"]
    if dates:
        return {"kind": "date", "date": min(dates)}
    for kind in ("rolling", "asap"):
        if a["kind"] == kind or b["kind"] == kind:
            return {"kind": kind, "date": None}
    return a
