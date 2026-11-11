"""Contact keys: the same person gets the same key in every classmate's export.

A key is an HMAC-SHA256 of the contact's LinkedIn profile handle (the part after /in/), made with a
secret that only the ingest knows. The key lets the database count a person once however many
classmates know them, and find people known by several classmates, without storing who they are.
Without the secret, a key cannot be turned back into a person or checked against a known profile.

The secret must stay the same for the whole cohort: every export loaded with a different secret
produces keys that match nothing. Keep a copy somewhere safe (a password manager), and move it
with the database if the project moves.

    python -m ingest.contact_keys new      # create the secret once, in linkedin-ingest/.contact_key
"""
import hashlib
import hmac
import os
import re
import secrets
import sys
from pathlib import Path
from urllib.parse import unquote

KEY_FILE = Path(__file__).resolve().parents[1] / ".contact_key"
ENV_VAR = "COHORT_CONTACT_KEY"
_HANDLE = re.compile(r"linkedin\.com/in/([^/?#\s]+)", re.I)


def load_secret():
    """The secret as bytes, or None if none is set up."""
    raw = os.environ.get(ENV_VAR) or (KEY_FILE.read_text(encoding="utf-8").strip() if KEY_FILE.exists() else "")
    return raw.encode("utf-8") if raw else None


def profile_handle(url):
    """'https://www.linkedin.com/in/Jane-Doe-123/?x=1' -> 'jane-doe-123'. None if not a profile link."""
    m = _HANDLE.search(url or "")
    return unquote(m.group(1)).strip().lower() if m else None


def canonical_profile_url(url):
    """A classmate's own link in one standard form, or None."""
    handle = profile_handle(url)
    return f"https://www.linkedin.com/in/{handle}/" if handle else None


def contact_key(secret, url=None, first=None, last=None, company_norm=None):
    """Key for one contact. Uses the profile handle; falls back to name + company when the
    export has no link (weaker: two people with the same name at one company would collide).
    Returns None when there is nothing to key on."""
    handle = profile_handle(url)
    if handle:
        basis = "in:" + handle
    else:
        name = re.sub(r"\s+", " ", f"{first or ''} {last or ''}").strip().lower()
        if not name:
            return None
        basis = f"name:{name}|{company_norm or ''}"
    return hmac.new(secret, basis.encode("utf-8"), hashlib.sha256).hexdigest()[:32]


def connected_year(text):
    """'03 Feb 2025' -> 2025."""
    m = re.search(r"\b(19|20)\d{2}\b", text or "")
    return int(m.group(0)) if m else None


def new_secret(path=KEY_FILE):
    if path.exists():
        sys.exit(f"{path} already exists. Replacing it would break matching with every export already loaded.")
    path.write_text(secrets.token_hex(32) + "\n", encoding="utf-8")
    os.chmod(path, 0o600)
    print(f"Created {path}. Back it up somewhere safe; it is not in git.")


if __name__ == "__main__":
    if sys.argv[1:] == ["new"]:
        new_secret()
    else:
        sys.exit(__doc__)
