"""Deterministic steps. No AI here: everything is a rule that can be tested exactly."""
import re

from .config import GENERIC_TOKENS

LEGAL_SUFFIX = re.compile(
    r"\s+(inc|incorporated|llc|l l c|llp|lp|l p|ltd|limited|corp|corporation|co|gmbh|ag|plc|sa|"
    r"technologies|labs|&|and)\s*$"
)
NOT_A_COMPANY = re.compile(
    r"^(self[- ]?employed|freelance(r)?|independent( consultant)?|stealth( startup| mode| company)?|"
    r"unemployed|retired|student|looking for (new )?opportunities|open to work|n/?a|none|-+|confidential)$"
)


def normalize_company(name):
    """Lowercase, strip punctuation and legal suffixes. Returns None for non-companies."""
    s = re.sub(r"\s+", " ", (name or "").strip().lower())
    if not s or NOT_A_COMPANY.match(s):
        return None
    s = re.sub(r"\(.*?\)", " ", s)              # drop parentheticals like (BCG)
    s = re.sub(r"[,.'’]", " ", s)
    s = re.sub(r"^the\s+", "", s)
    prev = None
    while prev != s:
        prev = s
        s = LEGAL_SUFFIX.sub("", re.sub(r"\s+", " ", s).strip())
    s = re.sub(r"\s+", " ", s).strip()
    if not s or NOT_A_COMPANY.match(s):
        return None
    return s


def compress(name):
    """Key that ignores spaces and symbols: 'jpmorgan chase' == 'jpmorganchase'."""
    return re.sub(r"[^0-9a-z\u0080-\uffff]", "", name or "")


def distinctive_tokens(name):
    return {t for t in re.findall(r"[0-9a-z\u0080-\uffff]+", name or "")
            if t not in GENERIC_TOKENS and len(t) >= 3}


def trigrams(s):
    s = f"  {compress(s)} "
    return {s[i:i + 3] for i in range(len(s) - 2)}


def jaccard(a, b):
    return len(a & b) / len(a | b) if a and b else 0.0


def is_candidate(new, existing):
    """Could these two names be the same organization? Cheap, recall-oriented test.

    True when they share a distinctive word, one compressed name starts or ends
    with the other (3+ chars), or their character trigrams overlap strongly.
    """
    if distinctive_tokens(new) & distinctive_tokens(existing):
        return True
    a, b = compress(new), compress(existing)
    short, long_ = sorted((a, b), key=len)
    if len(short) >= 3 and (long_.startswith(short) or long_.endswith(short)):
        return True
    return jaccard(trigrams(new), trigrams(existing)) >= 0.5


# Title rules. Function words are checked in order; seniority-only words fall
# through to "leadership" last, so "Director of Engineering" stays engineering.
TITLE_RULES = [
    ("recruiting", r"recruit|talent acquisition|talent partner|sourcer|people partner|\bhr\b|human resources"),
    ("legal", r"counsel|attorney|lawyer|paralegal|law clerk|\blegal\b"),
    ("healthcare", r"physician|\bdoctor\b|\bnurse\b|\bmedical\b|clinical|surgeon|\bmd\b|resident physician"),
    ("engineering", r"engineer|developer|software|\bsde\b|\bswe\b|architect|devops|\bsre\b|programmer|tech lead|technical lead|\bcto\b"),
    ("data_ml", r"\bdata\b|machine learning|\bml\b|scientist|analytics|\bnlp\b|business intelligence|data analyst"),
    ("product", r"\bproduct\b"),
    ("design", r"design|\bux\b|\bui\b"),
    ("sales_gtm", r"sales|account executive|account manager|business development|\bbd\b|\bgtm\b|go-to-market|partnerships|customer success"),
    ("marketing", r"marketing|growth|brand|communications"),
    ("finance", r"financ|investment bank|banking|private equity|venture|portfolio|trader|accountant|\bcfa\b|financial analyst"),
    ("consulting", r"consultant|consulting"),
    ("research", r"research|professor|lecturer|\bphd\b|postdoc|faculty"),
    ("education", r"\bteacher\b|\binstructor\b"),
    ("operations", r"operations|\bops\b|program manager|project manager|supply chain|logistics"),
    ("student_intern", r"\bintern\b|internship|\bstudent\b|\bcandidate\b|teaching assistant|course assistant|graduate assistant"),
    ("leadership", r"founder|\bceo\b|\bcoo\b|\bcfo\b|chief|\bvp\b|vice president|director|head of|president|managing partner|owner"),
]
_TITLE_RES = [(b, re.compile(p)) for b, p in TITLE_RULES]


def title_bucket(title):
    """Return a bucket, or 'other' when no rule fires (those go to AI if enabled)."""
    t = (title or "").lower()
    for bucket, rx in _TITLE_RES:
        if rx.search(t):
            return bucket
    return "other"


def norm_title(title):
    return re.sub(r"\s+", " ", (title or "").strip().lower())
