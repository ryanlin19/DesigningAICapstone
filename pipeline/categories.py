"""Broad job categories and levels (Peter's branch).

Every posting gets ONE broad category (Finance, Data & Analytics, ...) and a level, instead of being kept or
dropped by its title. The Find-a-job page filters by category and judges fit by category + level.

    category(title, is_consulting_firm)  -> one of CATEGORIES
    level(title, min_years)              -> one of LEVELS
"""
import re

CATEGORIES = ["Consulting", "Strategy & Operations", "Finance", "Data & Analytics", "Product", "Marketing & Growth",
              "Sales & Business Development", "Operations & Supply Chain", "Technology & Engineering",
              "People & HR", "Legal & Policy", "Other"]

# Neighbouring categories: a move between them is a stretch, not a pivot.
ADJACENT = {
    "Consulting": {"Strategy & Operations", "Finance", "Data & Analytics"},
    "Strategy & Operations": {"Consulting", "Finance", "Operations & Supply Chain", "Product", "Data & Analytics"},
    "Finance": {"Strategy & Operations", "Consulting", "Data & Analytics"},
    "Data & Analytics": {"Product", "Finance", "Strategy & Operations", "Technology & Engineering", "Consulting"},
    "Product": {"Data & Analytics", "Marketing & Growth", "Technology & Engineering", "Strategy & Operations"},
    "Marketing & Growth": {"Product", "Sales & Business Development"},
    "Sales & Business Development": {"Marketing & Growth", "Strategy & Operations"},
    "Operations & Supply Chain": {"Strategy & Operations"},
    "Technology & Engineering": {"Data & Analytics", "Product"},
    "People & HR": {"Strategy & Operations"},
    "Legal & Policy": {"Strategy & Operations"},
    "Other": set(),
}

# Checked in order on the lower-cased title; the first match wins. Specific functions come before broad words
# ("Financial Analyst" is Finance, "Product Marketing Manager" is Marketing, "Sales Strategy" is Sales).
_RULES = [
    ("People & HR", r"recruit|talent (acquisition|partner)|\bhr\b|human resources|people (partner|operations|ops|business)|"
                    r"\bhrbp\b|compensation|benefits|learning (&|and) development|\bdei\b"),
    ("Legal & Policy", r"counsel|attorney|lawyer|\blegal\b|paralegal|compliance|\bpolicy\b|regulatory|government (affairs|relations)|"
                       r"public policy|privacy|\bjd\b"),
    ("Marketing & Growth", r"product marketing|marketing|\bgrowth\b|\bbrand\b|communications|\bcontent\b|social media|\bseo\b|"
                           r"demand gen|public relations|\bpr\b|community|creative|copywrit|lifecycle|\bcrm\b|partner marketing"),
    ("Product", r"product manag|product owner|product lead|\bapm\b|product operations|product ops|product strategy|"
                r"product design|ux|user experience|user research|\bproduct\b"),
    ("Finance", r"financ|\binvestment|investor relations|banking|\bbanker\b|private equity|venture|portfolio|trader|trading|"
                r"accountant|accounting|controller|treasury|fp&a|\btax\b|\baudit|credit|underwrit|actuar|equity research|"
                r"capital markets|wealth|asset management|\bm&a\b|mergers|valuation|\bcfo\b|fund\b|lending|loan"),
    ("Sales & Business Development", r"\bsales\b|account executive|account manag|business development|partnerships?|alliances?|"
                                     r"customer success|\bbdr\b|\bsdr\b|revenue|go[- ]to[- ]market|\bgtm\b|commercial|"
                                     r"client (partner|director|executive)|channel|solutions? consultant|pre-?sales"),
    # engineering titles before data words: "Data Engineer", "Engineering Manager, Data Platform" are engineering roles
    ("Technology & Engineering", r"\bengineer(ing)?\b|developer|software|devops|\bsre\b|programmer"),
    ("Data & Analytics", r"\bdata\b|analytics|machine learning|\bml\b|\bai\b|scientist|business intelligence|\bbi\b|"
                         r"insights|quantitative|\bquant\b|statistic|economist|\banalyst\b"),
    ("Consulting", r"consultant|consulting|engagement manager|\badvisory\b|management consult"),
    ("Strategy & Operations", r"strateg|chief of staff|business operations|\bbizops\b|biz ops|corporate development|corp dev|"
                              r"transformation|\bpmo\b|program manag|general manag|\bgm\b|business planning|"
                              r"special projects|\binitiatives\b|business manager"),
    ("Operations & Supply Chain", r"supply chain|logistics|procurement|sourcing|\boperations\b|\bops\b|fulfil?ment|"
                                  r"manufactur|warehouse|planning|project manag|facilities|purchasing|inventory"),
    ("Technology & Engineering", r"engineer|developer|software|devops|\bsre\b|architect|\bit\b|infrastructure|security|"
                                 r"technical|technology|designer|programmer|cloud|network|systems"),
]
_RES = [(c, re.compile(p)) for c, p in _RULES]

# Generic ladder titles at consulting firms ("Senior Associate", "Manager") are consulting work.
_CONSULTING_LADDER = re.compile(r"^(senior |sr\.? )?(associate|manager|consultant|principal|director)\b")


def category(title, is_consulting_firm=False):
    t = (title or "").lower()
    for name, rx in _RES:
        if rx.search(t):
            if name in ("Data & Analytics", "Operations & Supply Chain") and is_consulting_firm and "consult" in t:
                return "Consulting"
            return name
    if is_consulting_firm and _CONSULTING_LADDER.search(t):
        return "Consulting"
    return "Other"


LEVELS = ["Internship", "Entry", "Mid", "Senior", "Executive"]
# Years of experience a level usually asks for, when the posting doesn't say.
LEVEL_YEARS = {"Internship": 0, "Entry": 1, "Mid": 3, "Senior": 7, "Executive": 12}

_LEVEL_RULES = [
    ("Internship", r"\bintern(ship)?s?\b|\bsummer (associate|analyst|consultant|intern|fellow|mba)\b|\bco-?op\b|\bmba (intern|summer)\b"),
    ("Executive", r"\bchief\b(?! of staff)|\bvp\b|vice president|\bsvp\b|\bevp\b|\bhead of\b|managing director|"
                  r"(?<!talent )(?<!people )(?<!business )(?<!hr )(?<!account )(?<!channel )(?<!client )(?<!success )(?<!acquisition )"
                  r"\bpartner\b(?!s?hips?| manager| marketing| success| development| solutions)|\bpresident\b"),
    ("Senior", r"\bdirector\b|\bprincipal\b|\bsenior manager\b|\bsr\.? manager\b|(?<!chief of )\bstaff\b|\blead\b|\bgeneral manager\b"),
    ("Entry", r"\bjunior\b|\bentry[- ]level\b|\bnew grad|\bgraduate\b|\bassociate consultant\b|\bcoordinator\b|\bassistant\b|"
              r"\bapprentice|(?<!senior )(?<!sr\. )(?<!sr )\banalyst\b(?! ii| iii| 2| 3)|\b(i|1)$|\brepresentative\b|\bbdr\b|\bsdr\b"),
]
_LEVEL_RES = [(lv, re.compile(p)) for lv, p in _LEVEL_RULES]


def level(title, min_years=None):
    """Level from the title; a stated years-of-experience figure settles titles that don't say."""
    t = (title or "").lower()
    found = next((lv for lv, rx in _LEVEL_RES if rx.search(t)), None)
    if found in ("Internship", "Executive", "Senior"):
        return found
    if min_years is not None:
        by_years = "Entry" if min_years <= 1 else "Mid" if min_years <= 5 else "Senior" if min_years <= 9 else "Executive"
        if found == "Entry" and by_years != "Entry":
            return "Mid" if by_years == "Mid" else by_years
        return found or by_years
    return found or "Mid"
