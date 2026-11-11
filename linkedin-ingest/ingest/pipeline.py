"""Ingest one LinkedIn data export into the database.

Steps (D = deterministic code, AI = model judgment):
  D  open the export and read only the five allowed files
  D  check consent scopes
  D  parse the person's own profile, positions, education, skills
  D  read connections keeping only (company, title); names are never kept
  D  normalize company names; exact, alias and compressed-key lookup in the registry
  D  retrieve registry candidates for names with no exact match
  AI decide same / subsidiary / different, only when candidates exist
  D  bucket job titles with rules
  AI bucket titles the rules left as 'other', with the company as context (batched, cached)
  D  aggregate connections to (company, count, top bucket) and write
"""
import csv
import io
import json
import re
import uuid
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

from . import ai_tasks, registry, rules
from .config import MODELS, TITLE_BATCH_SIZE
from .db import now, queue_review
from .llm import LLMError

ALLOWED_FILES = {"Profile.csv", "Positions.csv", "Education.csv", "Skills.csv", "Connections.csv"}
VALID_SCOPES = {"profile", "connections"}


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


def connection_pairs(text):
    """(company_raw, title) for each connection. Name, URL and email columns are dropped here."""
    return [((r.get("Company") or "").strip(), (r.get("Position") or "").strip())
            for r in parse_csv(text, "First Name,")]


class Ingestor:
    def __init__(self, con, ai_model=None, caller=None):
        if ai_model and ai_model not in MODELS:
            raise ValueError(f"ai_model must be one of {sorted(MODELS)} or None")
        self.con = con
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
    def ingest(self, path, person_id, scopes, snapshot=None):
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
            con.execute("INSERT INTO positions VALUES (?,?,?,?,?,?,?,?)",
                        (pid, p.get("Company Name"), c, p.get("Title"), b, p.get("Started On"),
                         p.get("Finished On"), int(not (p.get("Finished On") or "").strip())))
        edu = parse_csv(files.get("Education.csv", ""))
        for e in edu:
            con.execute("INSERT INTO education VALUES (?,?,?,?,?,?)",
                        (pid, e.get("School Name"), self.resolve_company(e.get("School Name")),
                         e.get("Degree Name"), e.get("Start Date"), e.get("End Date")))
        skills = [s.get("Name") for s in parse_csv(files.get("Skills.csv", "")) if s.get("Name")]
        con.executemany("INSERT INTO skills VALUES (?,?)", [(pid, s) for s in skills])
        return {"positions": len(positions), "education": len(edu), "skills": len(skills)}

    def _ingest_connections(self, text, pid, snapshot):
        pairs = connection_pairs(text)
        comps = [self.resolve_company(c) for c, _ in pairs]
        kept = [(t, c) for (_, t), c in zip(pairs, comps) if c]
        buckets = self.bucket_titles(kept)
        counts, by_bucket = Counter(), defaultdict(Counter)
        for (t, c), b in zip(kept, buckets):
            counts[c] += 1
            by_bucket[c][b] += 1
        self.con.execute("DELETE FROM derived_connections WHERE connector_id=?", (pid,))
        for c, n in counts.items():
            named = [k for k, _ in by_bucket[c].most_common() if k != "other"]
            self.con.execute("INSERT INTO derived_connections VALUES (?,?,?,?,?)",
                             (pid, c, n, named[0] if named else "other", snapshot))
        return {"connections": len(pairs), "connections_without_company": len(pairs) - len(kept),
                "companies": len(counts)}
