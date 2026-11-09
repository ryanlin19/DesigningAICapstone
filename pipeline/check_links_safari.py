"""Check every distinct host of the apply links against what Safari (macOS/iOS) requires, and open a sample of the links
with a Safari user agent. This cannot launch Safari; it tests what Safari would meet on the wire:
  - the secure connection: TLS 1.2 or newer, a forward-secret cipher, a certificate Apple trusts (valid chain, matching name,
    not expired, lifetime of at most 398 days for certificates issued after Sept 2020);
  - the link itself: the final address after redirects must be https and answer with a normal page.
Usage: python pipeline/check_links_safari.py [links per host, default 3]
"""
import collections
import datetime
import json
import random
import socket
import ssl
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SAFARI_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) "
             "Version/17.6 Safari/605.1.15")
PER_HOST = int(sys.argv[1]) if len(sys.argv) > 1 else 3

text = (ROOT / "public" / "data.js").read_text(encoding="utf-8")
jobs = json.loads(text[len("window.BOARD_DATA = "):].rstrip().rstrip(";"))["jobs"]
by_host = collections.defaultdict(set)
for j in jobs:
    for loc in j["locations"]:
        by_host[loc["url"].split("/")[2]].add(loc["url"])
random.seed(7)


def tls_check(host):
    ctx = ssl.create_default_context()
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    try:
        with socket.create_connection((host, 443), timeout=15) as raw:
            with ctx.wrap_socket(raw, server_hostname=host) as s:
                cert = s.getpeercert()
                cipher = s.cipher()[0]
                nb = datetime.datetime.strptime(cert["notBefore"], "%b %d %H:%M:%S %Y %Z")
                na = datetime.datetime.strptime(cert["notAfter"], "%b %d %H:%M:%S %Y %Z")
                issues = []
                if "ECDHE" not in cipher and not s.version() == "TLSv1.3":
                    issues.append("cipher without forward secrecy: " + cipher)
                if nb > datetime.datetime(2020, 9, 1) and (na - nb).days > 398:
                    issues.append(f"certificate lifetime {(na - nb).days} days (Apple limit 398)")
                if (na - datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)).days < 14:
                    issues.append(f"certificate expires {na:%Y-%m-%d}")
                return s.version(), issues
    except Exception as e:
        return None, [f"{type(e).__name__}: {str(e)[:90]}"]


def open_link(url):
    req = urllib.request.Request(url, headers={"User-Agent": SAFARI_UA, "Accept": "text/html,application/xhtml+xml"})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            r.read(2000)
            return r.status, r.geturl()
    except urllib.error.HTTPError as e:
        return e.code, url
    except Exception as e:
        return type(e).__name__, url


hosts = sorted(by_host)
with ThreadPoolExecutor(8) as ex:
    tls = dict(zip(hosts, ex.map(tls_check, hosts)))
    sample = {h: random.sample(sorted(by_host[h]), min(PER_HOST, len(by_host[h]))) for h in hosts}
    flat = [(h, u) for h in hosts for u in sample[h]]
    results = list(ex.map(lambda hu: (hu[0], hu[1], open_link(hu[1])), flat))

print(f"{len(hosts)} hosts, {len(flat)} sample links opened with a Safari user agent\n")
bad_tls = {h: v for h, v in tls.items() if v[1]}
print("TLS / certificate problems:", len(bad_tls))
for h, (ver, issues) in bad_tls.items():
    print(f"  {h}: {'; '.join(issues)}")
print("TLS versions seen:", dict(collections.Counter(v[0] for v in tls.values())))
bad = [(h, u, r) for h, u, r in results if not (isinstance(r[0], int) and r[0] == 200 and r[1].startswith("https://"))]
print(f"\nLinks that did not open cleanly: {len(bad)} of {len(flat)}")
for h, u, (st, final) in bad:
    print(f"  {st}  {u[:100]}" + ("" if final == u else f"  -> {final[:60]}"))
