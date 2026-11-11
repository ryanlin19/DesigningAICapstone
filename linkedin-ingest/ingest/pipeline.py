"""Ingest one LinkedIn data export into the database.

Steps (D = deterministic code, AI = model judgment):
  D  open the export and read only the allowed files (five, plus one column of Invitations.csv for
     the owner's own profile link)
  D  check consent scopes
  D  parse the person's own profile, positions, education, skills
  D  read connections: company, title, name and profile link (emails are never kept)
  D  turn each contact's profile link into a keyed fingerprint (contact_keys.py) that matches them across exports
  D  normalize company names; exact, alias and compressed-key lookup in the registry
  D  retrieve registry candidates for names with no exact match
  AI decide same / subsidiary / different, only when candidates exist
  D  bucket job titles with rules
  AI bucket titles the rules left as 'other', with the company as context (batched, cached)
  D  aggregate connections to (company, count, top bucket) and write
  D  write one row per contact (key, company, bucket, year connected) for dedup and shared contacts
"""
import csv
import io
import json
import re
import uuid
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

from . import ai_tasks, contact_keys, registry, rules
from .config import MODELS, TITLE_BATCH_SIZE
from .db import now, queue_review
from .llm import LLMError

ALLOWED_FILES = {"Profile.csv", "Positions.csv", "Education.csv", "Skills.csv", "Connections.csv",
                 "Invitations.csv"}   # only for the person's own profile link; see own_profile_url()
VALID_SCOPES = {"profile", "connections"}


def own_profile_url(invitations_text):
    """The export owner's own profile link: the sender link on invitations they sent.

    LinkedIn's Profile.csv has no link, but every OUTGOING row of Invitations.csv names the owner as
    the inviter. Only that one column of outgoing rows is read; names, messages and the other side
    of each invitation are ignored and nothing from this file is stored except the owner's link.
    Returns None when there are no sent invitations (or the basic export, which lacks the file).
    """
    try:
        rows = parse_csv(invitations_text)
    except Exception:
        return None
    links = Counter(contact_keys.canonical_profile_url(r.get("inviterProfileUrl")) for r in rows
                    if (r.get("Direction") or "").strip().upper() == "OUTGOING")
    links.pop(None, None)
    return links.most_common(1)[0][0] if links else None


def read_export(path):
    """Return ({filename: text} for allowed files only, number of files left unopened)."""
    path = Path(path)
    if zipfile.is_zipfile(path):
        files, skipped = {}, 0
        with zipfile.ZipFile(path) as z:
            for info in z.infolist():
                base = info.filename.split("/")[-1]
                if base in ALLOWED_FILES and "/" not in info.filename.strip("/"):
                    files[base] = z.read(info).decode("utf-8-sig")
                elif not info.is_dir():
                    skipped += 1
        return files, skipped
    if path.name == "Connections.csv" or path.suffix == ".csv":
        return {"Connections.csv": path.read_text(encoding="utf-8-sig")}, 0
    raise ValueError(f"{path}: not a LinkedIn export zip or Connections.csv")


def snapshot_from_filename(path):
    m = re.search(r"(\d{2})-(\d{2})-(\d{4})", Path(path).name)
    return f"{m.group(3)}-{m.group(1)}-{m.group(2)}" if m else None


def parse_csv(text, header_start=None):
    lines = text.splitlines()
    if header_start:
        idx = next((i for i, l in enumerate(lines) if l.startswith(header_start)), None)
        if idx is None:
            raise ValueError(f"header starting {header_start!r} not found")
        lines = lines[idx:]
    return list(csv.DictReader(io.StringIO("\n".join(lines))))


def connection_rows(text):
    """One dict per connection: company, title, name, profile link and date (for the contact key and the
    cohort's relationship graph). Email is never read."""
    return [{"company": (r.get("Company") or "").strip(), "title": (r.get("Position") or "").strip(),
             "url": r.get("URL"), "first": r.get("First Name"), "last": r.get("Last Name"),
             "connected_on": r.get("Connected On")}
            for r in parse_csv(text, "First Name,")]


class Ingestor:
    def __init__(self, con, ai_model=None, caller=None, contact_secret=None):
        if ai_model and ai_model not in MODELS:
            raise ValueError(f"ai_model must be one of {sorted(MODELS)} or None")
        self.con = con
        self.contact_secret = contact_secret  # bytes; None means no per-contact rows (counts only)
        self.model = MODELS[ai_model] if ai_model else None
        self.caller = caller  # injected in tests; None means the real API
        self.run_id = uuid.uuid4().hex[:12]
        self.memo = {}
        self.stats = Counter()

    def _ai_kwargs(self):
        kw = {"con": self.con, "run_id": self.run_id}
        if self.caller:
            kw["caller"] = self.caller
        return kw

    # ---- companies -------------------------------------------------------
    def resolve_company(self, raw):
        if raw in self.memo:
            return self.memo[raw]
        norm = rules.normalize_company(raw)
        result = None
        if norm:
            hit = registry.lookup(self.con, norm)
            if hit:
                self.stats["company_exact"] += 1
                result = hit
            else:
                result = self._resolve_new(norm, raw)
        self.memo[raw] = result
        return result

    def _resolve_new(self, norm, raw):
        cands = registry.retrieve(self.con, norm)
        if not cands:
            self.stats["company_new_no_candidates"] += 1
            registry.add_company(self.con, norm, raw, "export")
            return norm
        if not self.model:
            self.stats["company_queued_for_review"] += 1
            registry.add_company(self.con, norm, raw, "export")
            queue_review(self.con, "company_match", {"name": norm, "candidates": cands}, "AI off")
            return norm
        try:
            res, _ = ai_tasks.resolve_company(norm, cands, self.model, **self._ai_kwargs())
        except LLMError as e:
            self.stats["company_ai_failed"] += 1
            registry.add_company(self.con, norm, raw, "export")
            queue_review(self.con, "company_match", {"name": norm, "candidates": cands}, f"AI error: {e}")
            return norm
        self.stats[f"company_ai_{res['decision']}"] += 1
        if res["decision"] == "same":
            registry.add_alias(self.con, norm, res["match"], "ai")
            return res["match"]
        parent = res["match"] if res["decision"] == "subsidiary" else None
        registry.add_company(self.con, norm, raw, "ai" if parent else "export", parent=parent)
        return norm

    # ---- titles ----------------------------------------------------------
    def bucket_titles(self, pairs):
        """pairs: list of (title, company_norm). Returns list of buckets, same order."""
        out, pending = [], {}
        for title, comp in pairs:
            b = rules.title_bucket(title)
            if b == "other" and title:
                key = (rules.norm_title(title), comp or "")
                row = self.con.execute("SELECT bucket FROM title_cache WHERE title_norm=? AND company_norm=?",
                                       key).fetchone()
                if row:
                    b = row["bucket"]
                    self.stats["title_cache_hit"] += 1
                else:
                    pending.setdefault(key, title)
                    b = None
            else:
                self.stats["title_rule"] += 1
            out.append(b)

        if pending and self.model:
            keys = list(pending)
            for i in range(0, len(keys), TITLE_BATCH_SIZE):
                chunk = keys[i:i + TITLE_BATCH_SIZE]
                try:
                    buckets, _ = ai_tasks.classify_titles([(pending[k], k[1]) for k in chunk], self.model,
                                                          **self._ai_kwargs())
                except LLMError:
                    self.stats["title_ai_failed"] += len(chunk)
                    continue
                for k, b in zip(chunk, buckets):
                    self.con.execute("INSERT OR REPLACE INTO title_cache VALUES (?,?,?,?)", (*k, b, self.model))
                self.stats["title_ai"] += len(chunk)
        resolved = {}
        for k in pending:
            row = self.con.execute("SELECT bucket FROM title_cache WHERE title_norm=? AND company_norm=?",
                                   k).fetchone()
            resolved[k] = row["bucket"] if row else "other"
        if pending and not self.model:
            self.stats["title_left_other_ai_off"] += len(pending)
        return [b if b is not None else resolved[(rules.norm_title(t), c or "")]
                for b, (t, c) in zip(out, pairs)]

    # ---- whole export ----------------------------------------------------
    def ingest(self, path, person_id, scopes, snapshot=None, profile_url=None):
        scopes = {s.strip() for s in scopes.split(",")} if isinstance(scopes, str) else set(scopes)
        if not scopes or not scopes <= VALID_SCOPES:
            raise ValueError(f"consent scopes must be a non-empty subset of {sorted(VALID_SCOPES)}")
        snapshot = snapshot or snapshot_from_filename(path) or now()[:10]
        files, skipped = read_export(path)
        started = now()
        con = self.con
        summary = {"person_id": person_id, "files_read": sorted(files), "files_left_unopened": skipped,
                   "snapshot_date": snapshot}

        prof = parse_csv(files["Profile.csv"])[0] if "Profile.csv" in files and "profile" in scopes else {}
        con.execute(
            "INSERT INTO people(person_id, first_name, last_name, headline, industry, geo_location,"
            " consent_scopes, consent_at, export_date, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)"
            " ON CONFLICT(person_id) DO UPDATE SET first_name=excluded.first_name, last_name=excluded.last_name,"
            " headline=excluded.headline, industry=excluded.industry, geo_location=excluded.geo_location,"
            " consent_scopes=excluded.consent_scopes, consent_at=excluded.consent_at,"
            " export_date=excluded.export_date, updated_at=excluded.updated_at",
            (person_id, prof.get("First Name"), prof.get("Last Name"), prof.get("Headline"),
             prof.get("Industry"), prof.get("Geo Location"), ",".join(sorted(scopes)), now(), snapshot, now()))
        # The classmate's own link and key: the key keeps classmates out of each other's shared contacts and
        # shows who is already connected; the link (theirs only, given with consent) lets classmates connect.
        # A link typed in wins; otherwise it comes from invitations they sent, when the export has them.
        if profile_url:
            summary["profile_url_source"] = "given"
        elif "Invitations.csv" in files:
            profile_url = own_profile_url(files["Invitations.csv"])
            if profile_url:
                summary["profile_url_source"] = "Invitations.csv"
        if profile_url:
            summary["profile_url"] = contact_keys.canonical_profile_url(profile_url)
        if profile_url and self.contact_secret:
            con.execute("UPDATE people SET self_key=?, profile_url=? WHERE person_id=?",
                        (contact_keys.contact_key(self.contact_secret, profile_url),
                         contact_keys.canonical_profile_url(profile_url), person_id))

        if "profile" in scopes:
            summary.update(self._ingest_profile(files, person_id))
        if "connections" in scopes:
            if "Connections.csv" in files:
                summary.update(self._ingest_connections(files["Connections.csv"], person_id, snapshot))
            else:
                summary["connections"] = "none in export"

        summary["steps"] = dict(self.stats)
        con.execute("INSERT INTO ingest_runs VALUES (?,?,?,?,?,?,?)",
                    (self.run_id, person_id, Path(path).name, self.model, started, now(), json.dumps(summary)))
        con.commit()
        return summary

    def _ingest_profile(self, files, pid):
        con = self.con
        for t in ("positions", "education", "skills"):
            con.execute(f"DELETE FROM {t} WHERE person_id=?", (pid,))
        positions = parse_csv(files.get("Positions.csv", ""))
        comps = [self.resolve_company(p.get("Company Name")) for p in positions]
        buckets = self.bucket_titles([(p.get("Title", ""), c) for p, c in zip(positions, comps)])
        for p, c, b in zip(positions, comps, buckets):
            con.execute("INSERT INTO positions (person_id, company_raw, company_norm, title, title_bucket, started_on, "
                        "finished_on, is_current, location) VALUES (?,?,?,?,?,?,?,?,?)",
                        (pid, p.get("Company Name"), c, p.get("Title"), b, p.get("Started On"),
                         p.get("Finished On"), int(not (p.get("Finished On") or "").strip()), (p.get("Location") or "").strip() or None))
        edu = parse_csv(files.get("Education.csv", ""))
        for e in edu:
            con.execute("INSERT INTO education VALUES (?,?,?,?,?,?)",
                        (pid, e.get("School Name"), self.resolve_company(e.get("School Name")),
                         e.get("Degree Name"), e.get("Start Date"), e.get("End Date")))
        skills = [s.get("Name") for s in parse_csv(files.get("Skills.csv", "")) if s.get("Name")]
        con.executemany("INSERT INTO skills VALUES (?,?)", [(pid, s) for s in skills])
        return {"positions": len(positions), "education": len(edu), "skills": len(skills)}

    def _ingest_connections(self, text, pid, snapshot):
        rows = connection_rows(text)
        comps = [self.resolve_company(r["company"]) for r in rows]
        kept = [(r, c) for r, c in zip(rows, comps) if c]
        buckets = self.bucket_titles([(r["title"], c) for r, c in kept])
        counts, by_bucket = Counter(), defaultdict(Counter)
        for (_, c), b in zip(kept, buckets):
            counts[c] += 1
            by_bucket[c][b] += 1
        self.con.execute("DELETE FROM derived_connections WHERE connector_id=?", (pid,))
        for c, n in counts.items():
            named = [k for k, _ in by_bucket[c].most_common() if k != "other"]
            self.con.execute("INSERT INTO derived_connections VALUES (?,?,?,?,?)",
                             (pid, c, n, named[0] if named else "other", snapshot))
        summary = {"connections": len(rows), "connections_without_company": len(rows) - len(kept),
                   "companies": len(counts)}
        # One keyed row per contact: lets the database deduplicate and find contacts shared by classmates.
        self.con.execute("DELETE FROM contacts WHERE connector_id=?", (pid,))
        if self.contact_secret:
            keyed = 0
            for (r, c), b in zip(kept, buckets):
                key = contact_keys.contact_key(self.contact_secret, r["url"], r["first"], r["last"], c)
                if key:
                    name = " ".join(x.strip() for x in (r["first"] or "", r["last"] or "") if x and x.strip()) or None
                    cur = self.con.execute(
                        "INSERT OR IGNORE INTO contacts (contact_key, connector_id, company_norm, title_bucket, connected_year, "
                        "snapshot_date, full_name, position, profile_url) VALUES (?,?,?,?,?,?,?,?,?)",
                        (key, pid, c, b, contact_keys.connected_year(r["connected_on"]), snapshot, name,
                         r["title"] or None, contact_keys.canonical_profile_url(r["url"])))
                    keyed += cur.rowcount
            summary["contacts_keyed"] = keyed
        else:
            summary["contacts_keyed"] = "off (no contact key set up)"
        return summary
