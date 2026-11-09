"""Survey: which job system does each major firm's careers page use?

Fetches each careers URL and reports the final URL plus any known job-system fingerprints found in the HTML.
Read-only; used to decide which adapters are worth building.
"""
import re
import urllib.request
from concurrent.futures import ThreadPoolExecutor

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"

FIRMS = {
    "McKinsey": "https://www.mckinsey.com/careers/search-jobs",
    "BCG": "https://careers.bcg.com/global/en/search-results",
    "Bain": "https://www.bain.com/careers/find-a-role/",
    "Deloitte": "https://apply.deloitte.com/en_US/careers",
    "PwC": "https://www.pwc.com/us/en/careers/experienced-careers.html",
    "EY": "https://careers.ey.com/ey/search",
    "KPMG": "https://www.kpmguscareers.com/",
    "Accenture": "https://www.accenture.com/us-en/careers/jobsearch",
    "Strategy&": "https://www.strategyand.pwc.com/gx/en/careers.html",
    "Oliver Wyman": "https://www.oliverwyman.com/careers.html",
    "LEK": "https://www.lek.com/careers",
    "ZS": "https://www.zs.com/careers",
    "Kearney": "https://kearney.recsolu.com/job_boards/1",
    "Capgemini": "https://www.capgemini.com/careers/",
    "Booz Allen": "https://careers.boozallen.com/",
    "Huron": "https://www.huronconsultinggroup.com/careers",
    "FTI": "https://www.fticonsulting.com/careers",
    "Guidehouse": "https://guidehouse.com/careers",
    "Alvarez & Marsal": "https://www.alvarezandmarsal.com/careers",
    "Slalom": "https://www.slalom.com/us/en/careers",
    "West Monroe": "https://www.westmonroe.com/careers",
    "Protiviti": "https://www.protiviti.com/us-en/careers",
    "Grant Thornton": "https://www.grantthornton.com/careers",
    "RSM": "https://rsmus.com/careers.html",
    "Roland Berger": "https://www.rolandberger.com/en/Careers/",
    "Simon-Kucher": "https://www.simon-kucher.com/en/careers",
    "Gartner": "https://jobs.gartner.com/",
    "Mercer": "https://www.mercer.com/en-us/careers/",
    "Analysis Group": "https://www.analysisgroup.com/careers/",
    "Cornerstone Research": "https://www.cornerstone.com/careers/",
    "Altman Solon": "https://www.altmansolon.com/careers",
    "Putnam": "https://www.putassoc.com/careers/",
    "North Highland": "https://www.northhighland.com/careers",
    "PA Consulting": "https://www.paconsulting.com/careers",
    "Sia Partners": "https://www.sia-partners.com/en/careers",
    "Monitor Deloitte / Deloitte US jobs": "https://apply.deloitte.com/careers/SearchJobs",
}

FINGERPRINTS = {
    "Workday": r"myworkdayjobs\.com|\bwd\d+\.myworkday",
    "SmartRecruiters": r"smartrecruiters\.com",
    "iCIMS": r"icims\.com",
    "Taleo/Oracle": r"taleo\.net|oraclecloud\.com/hcmUI|\.oraclecloud\.com",
    "SuccessFactors": r"successfactors\.(com|eu)|jobs\.sap\.com",
    "Avature": r"avature\.net",
    "Phenom": r"phenompeople\.com|phenom\.com|cdn\.phenompeople",
    "Eightfold": r"eightfold\.ai",
    "Yello/RecSolu": r"recsolu\.com|yello",
    "Greenhouse": r"greenhouse\.io",
    "Lever": r"lever\.co",
    "Ashby": r"ashbyhq\.com",
    "Jobvite": r"jobvite\.com",
    "Workable": r"workable\.com",
    "BambooHR": r"bamboohr\.com",
    "Dayforce/Ceridian": r"dayforcehcm\.com|ceridian",
    "ADP": r"workforcenow\.adp\.com|recruiting\.adp\.com",
    "UKG": r"ultipro\.com|ukg\.com",
    "Paycom/Paylocity": r"paylocity\.com|paycomonline",
    "TalentBrew/Radancy": r"tmpwebeng|radancy|talentbrew",
}


def survey(item):
    name, url = item
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html"})
        with urllib.request.urlopen(req, timeout=25) as r:
            html = r.read(600000).decode("utf-8", "replace")
            final = r.geturl()
            status = r.status
    except Exception as e:  # noqa: BLE001
        return name, url, f"ERR {type(e).__name__}: {str(e)[:50]}", []
    hits = [k for k, pat in FINGERPRINTS.items() if re.search(pat, html, re.I)]
    # outbound hosts that look like job systems
    hosts = sorted(set(re.findall(r"https?://([a-z0-9.-]*(?:myworkdayjobs|smartrecruiters|icims|taleo|oraclecloud|avature|recsolu|successfactors|eightfold|phenom|jobvite)[a-z0-9.-]*)", html, re.I)))[:3]
    return name, final, f"{status}", hits + (["hosts:" + ",".join(hosts)] if hosts else [])


if __name__ == "__main__":
    with ThreadPoolExecutor(max_workers=8) as ex:
        for name, final, status, hits in ex.map(survey, FIRMS.items()):
            print(f"{name:<34} {status:<28} {', '.join(hits) or '-':<60} {final[:70]}")
