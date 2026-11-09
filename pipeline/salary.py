"""Pull a pay range out of a job posting's text when the job feed did not give a structured one.

Only yearly US-dollar ranges are read ("$147,000 - $170,000", "$120K to $150K"). Bonus, equity and sign-on ranges are skipped.
Returns (salary, several): salary is {"min", "max", "currency"} or None; several is True when the posting lists more than one
different range (usually one per location).
"""
import html
import re

_NUM = r"(\d{2,3}(?:,\d{3})+|\d{2,3}(?:\.\d)?\s?[kK]\b)"
RANGE = re.compile(r"\$\s?" + _NUM + r"\s*(?:-|–|—|to|and)\s*\$?\s?" + _NUM)
SKIP_BEFORE = re.compile(r"bonus|equity|stock|rsu|sign-?on|signing|commission|ote\b|retention|relocation|tuition|stipend", re.I)
PAY_WORDS = re.compile(r"salary|pay|compensation|base|range|wage", re.I)


def _value(s):
    s = s.replace(",", "").strip().lower()
    return float(s[:-1]) * 1000 if s.endswith("k") else float(s)


def from_text(text):
    text = html.unescape(html.unescape(text or ""))
    text = text.replace("&mdash;", "—").replace("&ndash;", "–")
    found = []
    for m in RANGE.finditer(text):
        lo, hi = _value(m.group(1)), _value(m.group(2))
        before = text[max(0, m.start() - 70):m.start()]
        if SKIP_BEFORE.search(before) or not (30000 <= lo <= hi <= 900000) or hi > 3 * lo:
            continue
        found.append((lo, hi, bool(PAY_WORDS.search(before))))
    if not found:
        return None, False
    preferred = [f for f in found if f[2]] or found
    lo, hi, _ = preferred[0]
    several = len({(f[0], f[1]) for f in found}) > 1
    return {"min": int(lo), "max": int(hi), "currency": "USD"}, several
