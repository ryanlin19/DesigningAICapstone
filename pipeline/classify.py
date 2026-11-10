"""Rules-based classifier: is this job a post-MBA strategy / consulting / ops role?

classify(job, is_consulting_firm) returns a dict of tags, or None if the job is
not a match. Ambiguous matches get review=True so a human can skim them.
"""
import re

# Category patterns, checked in order; first match wins.
CATEGORIES = [
    ("Chief of Staff", r"\bchief of staff\b"),
    ("Product Ops", r"\bproduct operations\b|\bproduct ops\b"),
    ("GTM / Revenue Ops", r"\brevenue operations\b|\brevops\b|\brev ops\b|\bgo[- ]to[- ]market (strategy|operations|ops)\b|"
                          r"\bgtm (strategy|operations|ops)\b|\bsales (strategy|operations)\b|\bcommercial (strategy|operations)\b|"
                          r"\bgrowth strategy\b"),
    ("Transformation / PMO", r"\btransformation\b|\bpmo\b|\bprogram management office\b|\bprogram management\b|\bchange management\b"),
    ("BizOps / Strategy & Ops", r"\bbusiness operations\b|\bbizops\b|\bbiz ops\b|\bstrategy (&|and) operations\b|\bstrategy (&|and) ops\b|"
                                r"\bstrategic operations\b|\boperations strategy\b|\bbusiness strategy\b|\bbusiness planning\b|\bstrategic initiatives\b|"
                                r"\bstrategy (&|and) planning\b|\boperations (&|and) strategy\b"),
    ("Corp Strategy", r"\bcorporate strategy\b|\bstrategic planning\b|\bstrategy (manager|lead|associate)\b|\bstrategic finance\b|"
                      r"\bcorporate development\b|\bcorp dev\b|\bhead of strategy\b|\b(manager|senior manager|associate),? strategy\b"),
    # Roles MBAs also go into (added 2026-11-09, user decision). Product management first so "Product Manager, Growth" is a product role.
    ("Product Management", r"\bproduct manager\b|\bproduct management\b|\bproduct lead\b|\bapm\b"),
    ("Business Development", r"\bbusiness development\b|\bbizdev\b|\bbd (manager|lead)\b|\bnew business\b"),
    ("Partnerships", r"\bpartnerships?\b|(?<!business )\bpartner (manager|lead|development)\b|\balliances?\b"),
    ("Growth", r"\bgrowth\b"),
    ("General Management", r"\bgeneral manager\b|\bgeneral management\b|\bgm\b"),
    ("Account Executive", r"\baccount executive\b|\bsales executive\b"),
    ("Tech & Digital Consulting", r"\b(technology|digital|data|ai|cloud|cyber ?security|it) (strategy )?consult(ant|ing)\b|\bdigital strategy\b|"
                                  r"\bsolutions? consultant\b|\btechnology advisory\b|"
                                  r"\b(workday|oracle|sap|salesforce|servicenow|netsuite|microsoft 365|azure|aws|erp|"
                                  r"cyber ?security|technology (audit|risk)|it (audit|risk))\b"),
    ("Strategy Consulting", r"\bconsultant\b|\bconsulting\b|\bengagement manager\b|\bmanagement consult\b|\badvisory\b"),
    ("Corp Strategy", r"\bstrategy\b|\bstrategic\b"),  # bare keyword: low confidence, always reviewed
]
LOW_CONFIDENCE = {r"\bstrategy\b|\bstrategic\b"}

# Generic consulting-ladder titles only count at consulting firms.
# Allows a short firm/unit prefix ("Kearney Associate, ...", "PERLab Manager- ...") before the ladder word.
CONSULTING_LADDER = re.compile(
    r"^(?:(senior |sr\.? )?(associate|manager|consultant)(?:[\s,:-]|$)|"                      # bare: "Senior Associate"
    r"(?P<pre>[a-z0-9.&'-]+ )(senior |sr\.? )?(associate|manager|consultant)\s*[,:-])|"       # "Kearney Associate, ..."
    r"\b(associate|manager)\b,? (consulting|advisory)")
# ...but not when that prefix names a non-consulting function ("Marketing Manager", "Office Manager").
LADDER_PREFIX_NOT = re.compile(
    r"\b(marketing|finance|financial|accounting|hr|human|facilities|office|it|legal|communications|brand|sales|"
    r"procurement|payroll|admin|operations|product|project|program|account|client|content|social|digital|data|"
    r"software|security|network|infrastructure|service|support|talent|people|learning|events?|community|"
    r"practice|regional|general)\b")

EXCLUDE = re.compile(
    r"\bintern(ship)?s?\b|\bsummer (associate|consultant|analyst|intern|program|fellow)\b|\bco-?op\b|\bstudent\b|\bapprentice|\bnew grad|\bgraduate\b|\bentry[- ]level\b|"
    r"\bengineer|\bdeveloper\b|\bsoftware\b|\bscientist\b|\bdesigner\b|\bdevops\b|\bprogrammer\b|\brecruit|\bcounsel\b|\battorney\b|\bparalegal\b|"
    r"\baccountant\b|\bauditor\b|\btax\b|\bpayroll\b|\bsdr\b|\bbdr\b|\bsales development\b|\bbusiness development (representative|rep)\b|\bcustomer success\b|"
    r"\bsupport (specialist|engineer)\b|\bcoordinator\b|\bassistant\b|\badministrative\b|\bmechanic|\btechnician\b|"
    r"\bdirector\b|\bvice president\b|\bvp\b|\bsvp\b|\bevp\b|\bchief (?!of staff)|\bpartner\b(?!s?hips?|\s+(manager|lead|development|alliances?|ecosystem|programs?))|\bprincipal\b|\bhead of\b|"
    r"\banalyst\b|\bjunior\b|\bmanaging director\b|\bsales representative\b|\bnurse\b|\bclinical\b|\bphysician\b|"
    # presales / technical roles that share consulting-sounding words, and staff-level (8+ yrs) titles
    r"\bsolutions? (consultant|architect)\b|\btechnical (solutions|program)\b|\bspecialist\b|(?<!chief of )\bstaff\b|"
    r"\bmarketing operations\b|\bevents?\b|\bimplementation consultant\b|\bsupport\b|"
    # not MBA-track: doctoral hires and technical forensics
    r"\bphd\b|\babd\b|\bpostdoc|\be-?discovery\b|\bforensic|\bincident response\b|\bactuar|"
    r"\btalent (acquisition|partner)\b|\bhuman resources\b|\bpeople partner\b|\bhrbp\b|"
    r"\bexpert\b|\bsubject matter\b|\bsme\b|"
    # hospital operations and EHR (Epic) implementation: healthcare staffing/billing work, not strategy
    r"\bepic\b|\bhospital\b|\bbilling\b|\bsupervisor\b|\bpatient\b"
)
# Government-contractor roles: closed to non-citizens, which matters for the visa label.
CLEARANCE = re.compile(
    r"security clearance|\bts/sci\b|\bsecret clearance\b|\btop secret\b|clearance (is )?required|\bpublic trust\b|"
    r"(must be|requires?|required to be) (a )?(u\.?s\.?|united states) citizen|u\.?s\.? citizenship (is )?required|"
    r"citizenship (is )?required", re.I)

SENIORITY = [
    # pre-MBA ladder titles; shown, but hidden by the board's default seniority filter
    ("Entry-level", r"\bassociate consultant\b|\bconsultant (i|1)\b|\bconsulting associate\b|\bjunior\b|\bgraduate\b"),
    ("Sr. Manager", r"\bsenior manager\b|\bsr\.? manager\b"),
    ("Manager", r"\bmanager\b|\blead\b|\bengagement manager\b"),
    ("Sr. Associate", r"\bsenior (associate|consultant)\b|\bsr\.? (associate|consultant)\b"),
    ("Associate", r"\bassociate\b|\bconsultant\b"),
]

US_STRONG = re.compile(
    r"\bunited states\b|\busa\b|\bu\.s\.?\b|\bus[- ]remote\b|\bremote[- ]us\b|"
    r", (al|ak|az|ar|ca|co|ct|de|dc|fl|ga|hi|id|il|in|ia|ks|ky|la|me|md|ma|mi|mn|ms|mo|mt|ne|nv|nh|nj|nm|ny|nc|nd|oh|ok|or|pa|ri|sc|sd|tn|tx|ut|vt|va|wa|wv|wi|wy)\b|"
    r"\b(new york|san francisco|chicago|boston|seattle|austin|los angeles|atlanta|dallas|denver|washington|houston|minneapolis|"
    r"silicon valley|bay area|nyc|san jose|san mateo|palo alto|mountain view|menlo park|sunnyvale|oakland|brooklyn|"
    r"philadelphia|pittsburgh|miami|charlotte|nashville|raleigh|durham|detroit|cleveland|st\.? louis|salt lake|portland|"
    r"san diego|irvine|baltimore|stamford|cambridge|princeton|jersey city|bellevue|redmond|kirkland)\b", re.I)
NON_US = re.compile(
    r"\b(london|uk|united kingdom|england|scotland|canada|toronto|vancouver|montreal|india|bangalore|bengaluru|mumbai|delhi|hyderabad|"
    r"pune|chennai|gurgaon|singapore|germany|berlin|munich|frankfurt|paris|france|dublin|ireland|australia|sydney|melbourne|brazil|"
    r"sao paulo|mexico|japan|tokyo|netherlands|amsterdam|spain|madrid|barcelona|poland|warsaw|krakow|krak.w|czech|prague|hungary|"
    r"budapest|italy|milan|rome|china|beijing|shanghai|korea|seoul|romania|bucharest|portugal|lisbon|sweden|stockholm|denmark|"
    r"copenhagen|norway|oslo|finland|helsinki|israel|tel aviv|uae|dubai|saudi|qatar|south africa|nigeria|kenya|egypt|argentina|"
    r"chile|colombia|bogota|peru|philippines|manila|vietnam|thailand|bangkok|malaysia|indonesia|jakarta|hong kong|taiwan|taipei|"
    r"new zealand|auckland|belgium|brussels|switzerland|zurich|geneva|austria|vienna|luxembourg|greece|turkey|istanbul|ukraine|"
    r"kyiv|pakistan|emea|apac|latam)\b", re.I)

YEARS = re.compile(r"(\d{1,2})\s*(?:\+|-|–|to)?\s*(?:\d{1,2})?\s*\+?\s*years?", re.I)
NO_SPONSOR = re.compile(
    r"(not|no|unable to|cannot|can't|won't|will not|without|does not|do not|doesn't)\b.{0,50}\b(visa )?sponsor|"
    r"sponsorship (is )?(not|un)available|must be (legally )?(authorized|eligible) to work.{0,40}without", re.I)
YES_SPONSOR = re.compile(r"(will|can|able to|may|do|does|we) (also )?(provide |offer )?(visa |immigration |employment )?sponsor|"
                         r"sponsorship (is |will be )?(available|provided|offered)|open to sponsor|"
                         r"(visa|h-?1b|immigration|work visa) (sponsorship|support|assistance) (is |are )?(provided|offered|available)|"
                         r"visa (sponsorship|support) for (qualified|eligible|the right)|we sponsor|"
                         # "If visa sponsorship is required ... the company will manage and submit all necessary filings"
                         r"sponsorship (?:is|will be) required[^.]{0,160}\b(?:will|can)\b(?! not)[^.]{0,60}\b(?:manage|submit|handle|file|provide|assist|support|cover|pay|sponsor)\b|"
                         r"if (?:you|a candidate|the candidate) require[sd]? (?:visa )?sponsorship[^.]{0,120}\b(?:will|can)\b(?! not)[^.]{0,40}"
                         r"\b(?:manage|submit|handle|file|provide|assist|support|cover|pay|sponsor)\b", re.I)
# A softer signal than "we sponsor": benefits wording such as "in-house immigration support for foreign nationals".
IMMIGRATION_SUPPORT = re.compile(
    r"immigration\s+(?:support|assistance|services|benefits|help|attorneys?|counsel)|"
    r"(?:visa|work[- ]permit|work[- ]authori[sz]ation)\s+(?:support|assistance|help)|"
    r"(?:assist|help|support)\w*\s+(?:with|for)\s+(?:your\s+|their\s+)?(?:visa|immigration|work[- ](?:permit|authori[sz]ation))|"
    r"relocation\s+(?:and|&)\s+(?:visa|immigration)", re.I)
_NEGATION = re.compile(r"\b(?:no|not|never|unable|cannot|can't|won't|without|doesn't|don't|unavailable)\b|n't\b", re.I)


def immigration_support(text):
    """(offers, declines): does the posting offer immigration/visa support, or say it will not?"""
    offers = declines = False
    for m in IMMIGRATION_SUPPORT.finditer(text or ""):
        sentence_before = re.split(r"[.\n;]", text[max(0, m.start() - 60): m.start()])[-1]
        if _NEGATION.search(sentence_before):
            declines = True
        else:
            offers = True
    return offers, declines


_MBA = r"(?:\bMBA\b|master(?:'s|’s|s)? (?:of|in) business administration)"
MBA_RE = re.compile(_MBA, re.I)
# "MBA" named as one of several acceptable degrees ("e.g., MBA, MHA, MPH") is a soft mention, not a preference for an MBA.
_MBA_LIST = re.compile(
    r"\bMBA\b\s*[,/]\s*(?:MHA|MPH|MPP|MPA|MS|MA|PhD|JD|MSc|MEng|MD)\b|"
    r"\b(?:MHA|MPH|MPP|MPA|MS|MA|PhD|JD|MSc|MD)\s*[,/]\s*(?:or\s+)?MBA\b|"
    r"(?:e\.g\.|for example|such as|including)[^.\n]{0,12}\bMBA\b|"
    r"\b(?:CPA|CMA|ACCA|CFA|CIA|PMP)\b[^.\n]{0,25}\bMBA\b", re.I)   # a list of credentials, e.g. "CPA, CMA, MBA, or equivalent"
_MBA_PREFER = re.compile(r"prefer|desired|a plus|beneficial|advantage|strongly|highly|or equivalent|ideal", re.I)
_MBA_REQUIRE = re.compile(r"\b(?:required|requirement|must)\b", re.I)
_MBA_BEFORE = re.compile(r"\b(?:have|having|hold|holding|possess|with|earned|obtained|pursuing|currently|enrolled|completing|"
                         r"prefer(?:red)?|desired|ideally)\s+(?:an?\s+|the\s+)?$", re.I)
_MBA_RANK = {None: 0, "firm": 1, "preferred": 2, "required": 3, "title": 4}     # "firm": the firm recruits MBAs (see build.py)


def mba_kind(title, desc):
    """'title' (MBA in the job title), 'required' / 'preferred' (the posting says so), or None.

    A passing mention, or an MBA listed among other acceptable degrees, returns None.
    """
    if MBA_RE.search(title or ""):
        return "title"
    text = _MBA_LIST.sub(" ", desc or "")
    best = None
    for m in MBA_RE.finditer(text):
        after = re.split(r"[.\n;]", text[m.end(): m.end() + 60])[0]
        before = re.split(r"[.\n;]", text[max(0, m.start() - 50): m.start()])[-1]
        if _MBA_PREFER.search(after):
            kind = "preferred"
        elif _MBA_REQUIRE.search(after):
            kind = "required"
        elif _MBA_BEFORE.search(before) or re.match(r"\s*(?:degree|candidate|graduate|student)", after, re.I):
            kind = "preferred"
        else:
            continue
        if _MBA_RANK[kind] > _MBA_RANK[best]:
            best = kind
    return best


def stronger_mba(a, b):
    """The stronger of two MBA kinds (used when postings of the same role are merged)."""
    return a if _MBA_RANK[a] >= _MBA_RANK[b] else b


ADVANCED_DEGREE = re.compile(r"\bmba\b|master['’]?s|master of|graduate degree|advanced degree|graduate-level|\bph\.?d\b|\bj\.?d\b", re.I)


def advanced_degree_mentioned(text):
    """True when a posting names an MBA or another degree beyond a bachelor's. "Bachelor's or master's degree" is the usual
    boilerplate for entry-level work, so a master's printed right next to "bachelor" does not count."""
    text = text or ""
    for m in ADVANCED_DEGREE.finditer(text):
        if m.group(0).lower().startswith("master"):
            before = re.split(r"[.;:\n]", text[max(0, m.start() - 45):m.start()])[-1]      # same clause only
            after = re.split(r"[.;:\n]", text[m.end():m.end() + 30])[0]
            if re.search(r"bachelor|undergraduate", before + " " + after, re.I):
                continue
        return True
    return False


def location_ok(place):
    """False for a single place that is clearly outside the US (used when splitting multi-location postings)."""
    return not (NON_US.search(place) and not US_STRONG.search(place))


# "N years" mentions that are not a requirement: benefits, company history
YEARS_NOT_REQUIREMENT_AFTER = re.compile(r"of service|with (the )?company|tenure|years? old|ago\b|in business|of history|track record|\bvest", re.I)
YEARS_NOT_REQUIREMENT_BEFORE = re.compile(r"reimburse|\bvest|\bafter\b|upon|eligible|accru|anniversar|tuition|founded|since", re.I)


def _min_years(text):
    """Years of experience a posting asks for (the lower end of a range), or None.
    Postings double-encode plus signs ("7&#43; years"), so decode first. Mentions in benefits ("2 years of service") are
    skipped. Of what is left, a figure tied to the word experience wins, then a "6+" or "at least 6" figure, then the first."""
    import html
    text = html.unescape(html.unescape(text or ""))
    found = []                                  # (years, tied to "experience", stated as a minimum)
    for m in YEARS.finditer(text):
        n = int(m.group(1))
        if not 0 < n <= 20:
            continue
        before, after = text[max(0, m.start() - 60):m.start()], text[m.end():m.end() + 120]
        if YEARS_NOT_REQUIREMENT_AFTER.search(after[:40]) or YEARS_NOT_REQUIREMENT_BEFORE.search(re.split(r"[.;!?\n]", before)[-1]):
            continue
        if re.search(r"\bfor (?:over|more than)\s*$", before, re.I) and after.lstrip().startswith(","):
            continue                            # company history: "For over 20 years, LSC has been ..."
        tied = bool(re.search(r"experience", after, re.I) or re.search(r"experience", before, re.I))
        minimum = "+" in m.group(0) or bool(re.search(r"at least|minimum|min\.|require", before, re.I))
        found.append((n, tied, minimum))
    for test in (lambda f: f[1], lambda f: f[2], lambda f: True):
        hit = next((f for f in found if test(f)), None)
        if hit:
            return hit[0]
    return None


# Some firms use "Vice President" for a mid-level consulting rung (AlixPartners: about a senior associate). build.py passes
# allow_vp=True for those firms only; senior and executive VPs stay excluded everywhere.
VP_TITLE = re.compile(r"(?<!senior )(?<!executive )(?<!sr\. )(?<!sr )\b(vice president|vp)\b")
VP_NOT_STRATEGY = re.compile(r"\bcpa\b|ediscovery|investigations|disputes|valuations?|compliance|\brisk\b|\btax\b|\blegal\b")


def classify(job, is_consulting_firm, allow_vp=False, keep=False):
    """keep=True is for a role the user picked by hand (data/early_career_keep.json): the title filters do not apply to it."""
    title = job["title"].strip()
    tl = title.lower()
    is_vp = bool(allow_vp and is_consulting_firm and VP_TITLE.search(tl) and not VP_NOT_STRATEGY.search(tl))
    if not keep and EXCLUDE.search(VP_TITLE.sub("", tl) if is_vp else tl):
        return None

    category, review = None, False
    for name, pat in CATEGORIES:
        if re.search(pat, tl):
            category, review = name, pat in LOW_CONFIDENCE
            break
    if category is None and is_consulting_firm:
        m = CONSULTING_LADDER.search(tl)
        if m and not LADDER_PREFIX_NOT.search(m.groupdict().get("pre") or ""):
            category = "Strategy Consulting"  # generic ladder title at a consulting firm
    if category is None and (is_vp or keep):
        category = "Strategy Consulting"
    if category is None:
        return None
    if not keep and not is_consulting_firm and (category in ("Strategy Consulting", "Tech & Digital Consulting") or review):
        # At tech companies "consultant", "engagement manager" and bare "strategic" are services, implementation
        # and account roles ("Strategic Account Manager"), not MBA strategy roles.
        return None

    loc = job.get("location", "") or ""
    if loc and not US_STRONG.search(loc):
        # No US evidence. Keep only a bare "Remote" (or nothing) with no foreign place named; otherwise drop.
        if NON_US.search(loc) or not re.search(r"\bremote\b|\bhybrid\b|\bmultiple\b|\banywhere\b", loc, re.I):
            return None
        review = True

    seniority = None
    for name, pat in SENIORITY:
        if re.search(pat, tl):
            seniority = name
            break

    if is_vp:
        seniority = "Sr. Associate"       # treated as a senior associate (see VP_TITLE)

    desc = job.get("description", "") or ""
    years = _min_years(desc[:6000])
    if years is not None and years >= 10:
        return None  # senior hire, not post-MBA
    mba = bool(re.search(r"\bmba\b|master of business administration", desc + " " + title, re.I))
    immig_offers, immig_declines = immigration_support(desc)
    if not seniority and years is not None:
        seniority = "Associate" if years <= 3 else "Manager" if years <= 7 else "Sr. Manager"

    return {
        "category": category,
        "seniority": seniority or "Unspecified",
        "min_years": years,
        "mba_mentioned": mba,
        "mba_kind": mba_kind(title, desc),
        "requires_clearance": bool(CLEARANCE.search(desc)),
        "says_no_sponsorship": bool(NO_SPONSOR.search(desc)) or immig_declines,   # "we do not provide visa support" counts as a no
        "says_sponsors": bool(YES_SPONSOR.search(desc)),
        "immigration_support": immig_offers and not immig_declines,
        "review": review,
    }
