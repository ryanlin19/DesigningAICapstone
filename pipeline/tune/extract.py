"""Turn resumes (PDF, Word, text) into anonymous plain text for tuning the resume matcher.

    python pipeline/tune/extract.py                 # reads resumes_private/, writes resumes_private/text/rNNN.txt
    python pipeline/tune/extract.py --remove-originals   # then moves the original files to the Recycle Bin

What it does, in order:
  1. Skips files that are marked as edited copies (names with "vRxL", "vRL", "RxLedits", ...).
  2. Keeps one resume per person (a folder is one person; a Word and PDF of the same resume count once).
  3. Anonymizes: removes the person's name (taken from the file name and the top line), emails, phone numbers,
     web links and street addresses.
  4. Writes the text under a random id. No file name, name or id-to-name list is stored anywhere.

Employer and school names stay, because they carry the industry. Both folders are git-ignored.
"""
import random
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "resumes_private"
OUT = SRC / "text"

EDITED = re.compile(r"(?i)(?:[_ \-.(]|^)v?r(?:x)?l(?:[ _\-.]?edits?|[ _\-.)]|$)|edits?\b")
NOT_A_NAME = set("""resume resumes cv cover letter cornell johnson mba consulting full time summer internship ft recruiting
wip new copy working final draft jcc mckinsey bain bcg vf vb v1 v2 docx pdf edits edit rxl rl the and of
version vrxl vrxledits template""".split())


def pdf_text(path):
    from pypdf import PdfReader
    return "\n".join((p.extract_text() or "") for p in PdfReader(str(path)).pages)


def docx_text(path):
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml").decode("utf-8", "ignore")
    xml = re.sub(r"</w:p>", "\n", xml)
    xml = re.sub(r"<w:tab/>", "\t", xml)
    text = re.sub(r"<[^>]+>", "", xml)
    for a, b in (("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'), ("&apos;", "'")):
        text = text.replace(a, b)
    return text


def read(path):
    ext = path.suffix.lower()
    if ext == ".pdf":
        return pdf_text(path)
    if ext == ".docx":
        return docx_text(path)
    return path.read_text("utf-8", "ignore")


EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
PHONE = re.compile(r"(?:\+?\d[\d\-.\s()]{8,}\d)")
URL = re.compile(r"(?i)(?:https?://|www\.|linkedin\.com|github\.com)\S*")
STREET = re.compile(r"(?i)\b\d{1,5}\s+[\w.\s]{2,30}\b(?:street|st|avenue|ave|road|rd|drive|dr|blvd|boulevard|lane|ln|way|apt|unit)\b\.?[^\n]*")
ZIPCODE = re.compile(r"\b\d{5}(?:-\d{4})?\b")


def name_tokens(path, text):
    """Words that make up the person's name: from the file/folder name and from the top line of the resume."""
    words = set()
    for part in (path.stem, path.parent.name if path.parent != SRC else ""):
        for w in re.findall(r"[A-Za-z]+", part):
            if w.lower() not in NOT_A_NAME and len(w) >= 2:
                words.add(w.lower())
    for line in [l.strip() for l in text.splitlines() if l.strip()][:3]:
        ws = re.findall(r"[A-Za-z][A-Za-z'\-]+", line)
        if 1 <= len(ws) <= 4 and len(ws) == len(line.replace(",", " ").split()) and all(w.lower() not in NOT_A_NAME for w in ws):
            words.update(w.lower() for w in ws if len(w) >= 2)
            break
    return words


def anonymize(text, names):
    lines = []
    for line in text.splitlines():
        line = EMAIL.sub(" ", line)
        line = URL.sub(" ", line)
        line = PHONE.sub(" ", line)
        line = STREET.sub(" ", line)
        if re.search(r"\b[A-Z]{2}\s+\d{5}\b", line):
            line = ZIPCODE.sub(" ", line)
        lines.append(line)
    text = "\n".join(lines)
    if names:
        text = re.sub(r"(?i)(?<![A-Za-z])(" + "|".join(sorted(map(re.escape, names), key=len, reverse=True)) + r")(?![A-Za-z])", " ", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"


def leaks(text, names):
    found = []
    if EMAIL.search(text):
        found.append("email")
    if URL.search(text):
        found.append("link")
    if PHONE.search(text):
        found.append("phone")
    low = text.lower()
    for n in names:
        if re.search(r"(?<![a-z])" + re.escape(n) + r"(?![a-z])", low):
            found.append("name")
            break
    return found


def main():
    remove = "--remove-originals" in sys.argv
    files = [f for f in sorted(SRC.rglob("*")) if f.is_file() and OUT not in f.parents and f.suffix.lower() in (".pdf", ".docx", ".txt")]
    edited = [f for f in files if EDITED.search(f.stem)]
    originals = [f for f in files if f not in edited]
    per_person = {}
    for f in originals:                          # one person per folder; loose files are their own person
        key = f.parent if f.parent != SRC else f
        per_person.setdefault(key, []).append(f)
    chosen, dups = [], 0
    for key, group in per_person.items():
        group.sort(key=lambda p: (p.suffix.lower() != ".docx", p.name))
        chosen.append(group[0])
        dups += len(group) - 1
    random.shuffle(chosen)
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("*.txt"):
        old.unlink()
    kept = bad = 0
    leaked = []
    for f in chosen:
        try:
            raw = read(f)
        except Exception as e:  # noqa: BLE001
            print(f"unreadable, skipped: {e.__class__.__name__}")
            bad += 1
            continue
        if len(raw.strip()) < 300 or re.search(r"(?i)dear (hiring|sir|madam)|cover letter", raw[:400]):
            bad += 1
            print("skipped one file: almost no text or a cover letter")
            continue
        names = name_tokens(f, raw)
        text = anonymize(raw, names)
        left = leaks(text, names)
        if left:
            leaked.append(left)
        kept += 1
        (OUT / f"r{kept:03d}.txt").write_text(text, encoding="utf-8")
    print(f"{len(files)} files found: {len(edited)} edited copies skipped, {dups} duplicate formats skipped, "
          f"{bad} unusable, {kept} resumes anonymized -> {OUT}")
    print(f"leak scan of the anonymized text: {len(leaked)} resumes with something left" + (f" {leaked}" if leaked else ""))
    if remove and not leaked:
        import subprocess
        ps = ("Add-Type -AssemblyName Microsoft.VisualBasic;"
              "Get-ChildItem -LiteralPath '%s' -Recurse -File | Where-Object { $_.FullName -notlike '%s*' } | ForEach-Object {"
              "[Microsoft.VisualBasic.FileIO.FileSystem]::DeleteFile($_.FullName,'OnlyErrorDialogs','SendToRecycleBin') };"
              "Get-ChildItem -LiteralPath '%s' -Directory | Where-Object { $_.Name -ne 'text' } | Remove-Item -Recurse -Force"
              % (SRC, OUT, SRC))
        subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True)
        print("original files moved to the Recycle Bin")
    elif remove:
        print("originals NOT removed: fix the leaks first")


if __name__ == "__main__":
    main()
