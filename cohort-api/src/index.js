// Cohort API: the cohort's only database (Cloudflare D1), behind a thin Worker.
// Every route except /v1/health needs "Authorization: Bearer <API_TOKEN>". There is no "run any SQL" route:
// each route reads or writes fixed tables and columns.
//
//   GET    /v1/health            -> {ok: true}
//   GET    /v1/snapshot          -> everything the board's company views need, in one call, including shared contacts
//   GET    /v1/people            -> classmates, every column
//   GET    /v1/positions         -> classmates' own jobs, every column (with locations)
//   GET    /v1/companies         -> the company registry {companies, aliases} (uploads resolve names against it)
//   GET    /v1/contacts          -> contacts at some companies (?company=norm, repeatable, up to 30), with names
//   GET    /v1/contacts/all      -> every contact, paged (?limit=, ?offset=) -> {contacts, next}
//   GET    /v1/log               -> the activity log, newest first (?limit=, up to 2000)
//   POST   /v1/log               -> add log entries {rows: [...]}; ids already there are left alone
//   POST   /v1/import            -> one classmate's whole upload {person_id, people, contacts, positions, education,
//                                    skills, company_counts, companies, aliases}: replaces their rows in one transaction
//   POST   /v1/people/:id/link   -> set a classmate's own LinkedIn link {profile_url, self_key}
//   DELETE /v1/people/:id        -> remove a classmate and every row from their upload
//   GET    /v1/inbox             -> Muse's deliveries {inbox: muse_inbox rows, manual: manual_connections noted "Muse..."}
//   POST   /v1/inbox/apply       -> the board's merge of them, in one transaction {upsert, delete, log, clear_inbox, clear_manual}
//   GET    /v1/research/done     -> company research Muse finished {rows: [{id, name, result}]} (muse/COMPANY_RESEARCH.md)
//   POST   /v1/research/mark     -> after merging them {merged: [ids], needs_fix: [{id, error}], log: [rows]}, one transaction
//   GET    /v1/jobs/version      -> the current jobs build {build_id, generated, pushed_at, jobs}; ?kind=all for every posting
//   GET    /v1/jobs              -> the current build's roles, shaped like the page's window.BOARD_DATA; ?kind=all likewise
//   POST   /v1/manual            -> add a hand-entered connection {company, classmate, contact, title, note}
//   DELETE /v1/manual/:id        -> remove one
//
// Matching Muse's findings to contacts needs the cohort's fingerprint secret, which never leaves the board's computer,
// so the board works out the changes (cohort-board/inbox.py) and /v1/inbox/apply only writes them.

const LIMITS = { company: 200, classmate: 80, contact: 80, title: 120, note: 300 };
const PID = /^[a-z0-9-]{1,60}$/;

// The columns each writable table takes. Request rows are objects; anything else in them is ignored.
const COLS = {
  people: ["person_id", "display_name", "consent_scopes", "consent_at", "updated_at", "self_key", "profile_url",
           "first_name", "last_name", "headline", "industry", "geo_location", "export_date"],
  contacts: ["contact_key", "connector_id", "company_norm", "title_bucket", "snapshot_date", "connected_year",
             "full_name", "position", "profile_url", "location"],
  positions: ["person_id", "company_raw", "company_norm", "title", "title_bucket", "started_on", "finished_on",
              "is_current", "location"],
  education: ["person_id", "school_raw", "school_norm", "degree", "start_date", "end_date"],
  skills: ["person_id", "skill"],
  company_counts: ["connector_id", "company_norm", "count", "top_title_bucket", "snapshot_date"],
  companies: ["company_norm", "display_name", "parent_norm"],
  aliases: ["alias", "company_norm"],
  activity_log: ["id", "at", "source", "action", "person", "summary", "details"],
};
// Whose rows they are, for an upload's tables.
const OWNER = { contacts: "connector_id", positions: "person_id", education: "person_id", skills: "person_id",
                company_counts: "connector_id" };
const CHUNK = 250;              // rows per INSERT: each is one bound parameter holding a JSON array (D1 allows 100 per query)
const MAX_ROWS = 60000;

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    try {
      if (url.pathname === "/v1/health") return json({ ok: true });
      if (!(await authorized(request, env))) return json({ error: "unauthorized" }, 401);
      const db = env.DB, method = request.method, path = url.pathname;

      if (method === "GET" && path === "/v1/snapshot") return json(await snapshot(db));
      if (method === "GET" && path === "/v1/people") return json({ people: (await db.prepare("SELECT * FROM people ORDER BY person_id").all()).results });
      if (method === "GET" && path === "/v1/positions") return json({ positions: (await db.prepare("SELECT * FROM positions").all()).results });
      if (method === "GET" && path === "/v1/companies") {
        const [c, a] = await db.batch([db.prepare("SELECT company_norm, display_name, parent_norm FROM companies"),
                                       db.prepare("SELECT alias, company_norm FROM aliases")]);
        return json({ companies: c.results, aliases: a.results });
      }
      if (method === "GET" && path === "/v1/contacts") {
        const norms = url.searchParams.getAll("company").map((c) => c.slice(0, 200)).filter(Boolean).slice(0, 30);
        if (!norms.length) return json({ error: "company required" }, 400);
        const rows = await db.prepare(
          `SELECT ${COLS.contacts.join(", ")} FROM contacts WHERE company_norm IN (${norms.map(() => "?").join(",")}) LIMIT 5000`)
          .bind(...norms).all();
        return json({ contacts: rows.results });
      }
      if (method === "GET" && path === "/v1/contacts/all") {
        const limit = Math.min(10000, Math.max(1, int(url.searchParams.get("limit"), 5000)));
        const offset = Math.max(0, int(url.searchParams.get("offset"), 0));
        const rows = (await db.prepare(`SELECT ${COLS.contacts.join(", ")} FROM contacts ORDER BY connector_id, contact_key LIMIT ? OFFSET ?`)
          .bind(limit, offset).all()).results;
        return json({ contacts: rows, next: rows.length === limit ? offset + limit : null });
      }
      if (method === "GET" && path === "/v1/log") {
        const limit = Math.min(2000, Math.max(1, int(url.searchParams.get("limit"), 300)));
        return json({ entries: (await db.prepare("SELECT * FROM activity_log ORDER BY at DESC, id LIMIT ?").bind(limit).all()).results });
      }
      if (method === "POST" && path === "/v1/log") {
        const b = await body(request);
        const rows = Array.isArray(b && b.rows) ? b.rows : null;
        const bad = !rows || rows.length > 1000 || rows.some((r) => !r || !r.id || !r.at || !r.source || !r.action || !r.summary);
        if (bad) return json({ error: "rows: [{id, at, source, action, summary, ...}] required" }, 400);
        if (rows.length) await db.batch(insertRows(db, "activity_log", rows, "OR IGNORE"));
        return json({ added: rows.length });
      }
      if (method === "POST" && path === "/v1/import") return importPerson(request, db);
      if (method === "GET" && path === "/v1/inbox") {
        const [inbox, manual] = await db.batch([
          db.prepare("SELECT * FROM muse_inbox ORDER BY found_at, id"),
          db.prepare("SELECT * FROM manual_connections WHERE note LIKE 'Muse%' ORDER BY added_at, id"),
        ]);
        return json({ inbox: inbox.results, manual: manual.results });
      }
      if (method === "POST" && path === "/v1/inbox/apply") return applyInbox(request, db);
      if (method === "GET" && path === "/v1/research/done") {
        return json({ rows: (await db.prepare("SELECT id, name, result FROM company_research WHERE status = 'done' ORDER BY researched_at, id LIMIT 2000").all()).results });
      }
      if (method === "POST" && path === "/v1/research/mark") return markResearch(request, db);
      let m = path.match(/^\/v1\/people\/([a-z0-9-]{1,60})\/link$/);
      if (method === "POST" && m) {
        const b = await body(request);
        const link = String((b && b.profile_url) || ""), key = String((b && b.self_key) || "");
        if (!/^https:\/\/www\.linkedin\.com\/in\/[^\s]{1,200}$/.test(link) || !/^[0-9a-f]{16,64}$/.test(key)) {
          return json({ error: "profile_url and self_key required" }, 400);
        }
        const r = await db.prepare("UPDATE people SET profile_url = ?, self_key = ? WHERE person_id = ?").bind(link, key, m[1]).run();
        return r.meta.changes ? json({ profile_url: link }) : json({ error: "not found" }, 404);
      }
      m = path.match(/^\/v1\/people\/([a-z0-9-]{1,60})$/);
      if (method === "DELETE" && m) {
        const res = await db.batch(deletePerson(db, m[1]));
        const removed = Object.fromEntries(["contacts", "company_counts", "positions", "education", "skills", "people"]
          .map((t, i) => [t, res[i].meta.changes]));
        return removed.people ? json({ removed }) : json({ error: "not found", removed }, 404);
      }
      const kind = url.searchParams.get("kind") === "all" ? "all" : "board";
      if (method === "GET" && path === "/v1/jobs/version") {
        const b = await currentBuild(db, kind);
        return b ? json(b) : json({ error: "no jobs loaded" }, 404);
      }
      if (method === "GET" && path === "/v1/jobs") {
        const limit = Math.min(10000, int(url.searchParams.get("limit"), 0));
        const offset = Math.max(0, int(url.searchParams.get("offset"), 0));
        return boardData(db, kind, limit, offset);
      }
      if (method === "POST" && path === "/v1/manual") return addManual(request, db);
      m = path.match(/^\/v1\/manual\/([0-9a-f]{12})$/);
      if (method === "DELETE" && m) {
        const r = await db.prepare("DELETE FROM manual_connections WHERE id = ?").bind(m[1]).run();
        return r.meta.changes ? new Response(null, { status: 204 }) : json({ error: "not found" }, 404);
      }
      return json({ error: "not found" }, 404);
    } catch (e) {
      console.error(e);
      return json({ error: "server error" }, 500);
    }
  },
};

async function authorized(request, env) {
  const expected = env.API_TOKEN || "";
  const got = (request.headers.get("Authorization") || "").replace(/^Bearer\s+/i, "");
  if (!expected || got.length !== expected.length) return false;
  const enc = new TextEncoder();
  return crypto.subtle.timingSafeEqual(enc.encode(got), enc.encode(expected));
}

function int(v, dflt) {
  const n = parseInt(v || "", 10);
  return Number.isFinite(n) ? n : dflt;
}

async function body(request) {
  try { return await request.json(); } catch { return null; }
}

// INSERTs for many rows: each statement binds one JSON array and reads it with json_each, so a statement never needs
// more than one bound parameter however many columns the table has. `verb` is "" or "OR IGNORE"; `conflict` an ON
// CONFLICT clause (needs the "WHERE true" SQLite asks for when an upsert reads from a SELECT).
function insertRows(db, table, rows, verb = "", conflict = "") {
  const cols = COLS[table];
  const pick = cols.map((c) => `json_extract(value, '$.${c}')`).join(", ");
  const out = [];
  for (let i = 0; i < rows.length; i += CHUNK) {
    const part = rows.slice(i, i + CHUNK).map((r) => Object.fromEntries(cols.map((c) => [c, r[c] === undefined ? null : r[c]])));
    out.push(db.prepare(`INSERT ${verb} INTO ${table} (${cols.join(", ")}) SELECT ${pick} FROM json_each(?) WHERE true ${conflict}`)
      .bind(JSON.stringify(part)));
  }
  return out;
}

function deletePerson(db, pid) {
  return [["contacts", "connector_id"], ["company_counts", "connector_id"], ["positions", "person_id"],
          ["education", "person_id"], ["skills", "person_id"], ["people", "person_id"]]
    .map(([t, c]) => db.prepare(`DELETE FROM ${t} WHERE ${c} = ?`).bind(pid));
}

// One classmate's upload, replacing everything from their previous one. The company registry is shared by everyone,
// so it is merged rather than replaced. Runs as one batch: D1 applies it as a single transaction.
async function importPerson(request, db) {
  const b = await body(request);
  const pid = b && b.person_id;
  if (!PID.test(pid || "")) return json({ error: "person_id required" }, 400);
  const person = Array.isArray(b.people) && b.people.length === 1 ? b.people[0] : null;
  if (!person || person.person_id !== pid || !person.display_name || !person.consent_scopes || !person.consent_at || !person.updated_at) {
    return json({ error: "people: one row for person_id with display_name, consent_scopes, consent_at, updated_at" }, 400);
  }
  const rows = {};
  for (const t of [...Object.keys(OWNER), "companies", "aliases"]) {
    const list = b[t] === undefined ? [] : b[t];
    if (!Array.isArray(list) || list.length > MAX_ROWS) return json({ error: `${t} must be a list (up to ${MAX_ROWS})` }, 400);
    if (OWNER[t] && list.some((r) => !r || r[OWNER[t]] !== pid)) return json({ error: `every ${t} row must belong to ${pid}` }, 400);
    rows[t] = list;
  }
  if (rows.contacts.some((r) => !r.contact_key || !r.company_norm || !r.title_bucket)) {
    return json({ error: "contacts need contact_key, company_norm, title_bucket" }, 400);
  }
  if (rows.companies.some((r) => !r || !r.company_norm) || rows.aliases.some((r) => !r || !r.alias || !r.company_norm)) {
    return json({ error: "companies need company_norm; aliases need alias and company_norm" }, 400);
  }
  const stmts = [
    ...deletePerson(db, pid),
    ...insertRows(db, "people", [person]),
    ...insertRows(db, "contacts", rows.contacts, "OR IGNORE"),
    ...insertRows(db, "positions", rows.positions),
    ...insertRows(db, "education", rows.education),
    ...insertRows(db, "skills", rows.skills),
    ...insertRows(db, "company_counts", rows.company_counts, "OR IGNORE"),
    ...insertRows(db, "companies", rows.companies, "", "ON CONFLICT (company_norm) DO UPDATE SET " +
                  "display_name = COALESCE(excluded.display_name, companies.display_name), " +
                  "parent_norm = COALESCE(excluded.parent_norm, companies.parent_norm)"),
    ...insertRows(db, "aliases", rows.aliases, "OR IGNORE"),
  ];
  await db.batch(stmts);
  const counts = Object.fromEntries(Object.entries(rows).map(([t, l]) => [t, l.length]));
  return json({ person_id: pid, rows: counts });
}

// Muse's findings, as the board merged them: contact rows to add or change (whole rows, keyed by contact and
// classmate), contact rows to remove, log entries, and the delivered rows to clear. One transaction.
async function applyInbox(request, db) {
  const b = await body(request);
  if (!b) return json({ error: "bad JSON" }, 400);
  const list = (k) => (b[k] === undefined ? [] : b[k]);
  const upsert = list("upsert"), del = list("delete"), log = list("log"), inbox = list("clear_inbox"), manual = list("clear_manual");
  if (![upsert, del, log, inbox, manual].every((l) => Array.isArray(l) && l.length <= 5000)) {
    return json({ error: "upsert, delete, log, clear_inbox, clear_manual must be lists" }, 400);
  }
  if (upsert.some((r) => !r || !r.contact_key || !PID.test(r.connector_id || "") || !r.company_norm || !r.title_bucket) ||
      del.some((r) => !r || !r.contact_key || !r.connector_id) ||
      log.some((r) => !r || !r.id || !r.at || !r.source || !r.action || !r.summary)) {
    return json({ error: "incomplete rows" }, 400);
  }
  const set = COLS.contacts.filter((c) => c !== "contact_key" && c !== "connector_id").map((c) => `${c} = excluded.${c}`).join(", ");
  const stmts = [
    ...insertRows(db, "contacts", upsert, "", `ON CONFLICT (contact_key, connector_id) DO UPDATE SET ${set}`),
    ...(del.length ? [db.prepare(`DELETE FROM contacts WHERE (contact_key, connector_id) IN
                                   (SELECT json_extract(value, '$.contact_key'), json_extract(value, '$.connector_id') FROM json_each(?))`)
                       .bind(JSON.stringify(del.map((r) => ({ contact_key: r.contact_key, connector_id: r.connector_id }))))] : []),
    ...insertRows(db, "activity_log", log, "OR IGNORE"),
    ...(inbox.length ? [db.prepare("DELETE FROM muse_inbox WHERE id IN (SELECT value FROM json_each(?))").bind(JSON.stringify(inbox.map(String)))] : []),
    ...(manual.length ? [db.prepare("DELETE FROM manual_connections WHERE note LIKE 'Muse%' AND id IN (SELECT value FROM json_each(?))")
                         .bind(JSON.stringify(manual.map(String)))] : []),
  ];
  if (stmts.length) await db.batch(stmts);
  return json({ upserted: upsert.length, deleted: del.length, logged: log.length, cleared: inbox.length + manual.length });
}

// Company research merged into the directory ('merged') or sent back to Muse ('needs_fix' with the reason), plus log rows.
async function markResearch(request, db) {
  const b = await body(request);
  const merged = b && Array.isArray(b.merged) ? b.merged.map(String) : null;
  const fix = b && Array.isArray(b.needs_fix) ? b.needs_fix : null;
  const log = b && b.log !== undefined ? b.log : [];
  if (!merged || !fix || !Array.isArray(log) || merged.length > 5000 || fix.length > 5000 ||
      fix.some((r) => !r || !r.id || !r.error) || log.some((r) => !r || !r.id || !r.at || !r.source || !r.action || !r.summary)) {
    return json({ error: "merged: [ids], needs_fix: [{id, error}], log: [rows] required" }, 400);
  }
  const now = new Date().toISOString().slice(0, 19) + "Z";
  const stmts = [];
  if (merged.length) stmts.push(db.prepare("UPDATE company_research SET status = 'merged', error = NULL WHERE status = 'done' AND id IN (SELECT value FROM json_each(?))")
    .bind(JSON.stringify(merged)));
  for (const r of fix) stmts.push(db.prepare("UPDATE company_research SET status = 'needs_fix', error = ?, researched_at = COALESCE(researched_at, ?) WHERE id = ?")
    .bind(String(r.error).slice(0, 500), now, String(r.id)));
  stmts.push(...insertRows(db, "activity_log", log, "OR IGNORE"));
  if (stmts.length) await db.batch(stmts);
  return json({ merged: merged.length, needs_fix: fix.length });
}

async function snapshot(db) {
  const [people, companies, aliases, counts, buckets, uniqueByCompany, uniqueByRoot, manual, shared, sharedLinks, knows, positions] = await db.batch([
    db.prepare(`SELECT person_id, display_name, updated_at, profile_url,
                CASE WHEN self_key IS NULL THEN 0 ELSE 1 END AS has_self_key FROM people`),
    db.prepare("SELECT company_norm, parent_norm FROM companies WHERE parent_norm IS NOT NULL"),
    db.prepare("SELECT alias, company_norm FROM aliases"),
    db.prepare("SELECT connector_id, company_norm, count, top_title_bucket FROM company_counts"),
    // per classmate, company and job type: lets the board say "mostly consulting" only when it is true
    db.prepare("SELECT connector_id, company_norm, title_bucket, COUNT(*) AS n FROM contacts GROUP BY 1, 2, 3"),
    // unique people per company, and per parent company with its units rolled in
    db.prepare("SELECT company_norm, COUNT(DISTINCT contact_key) AS n FROM contacts GROUP BY 1"),
    db.prepare(`SELECT COALESCE(c.parent_norm, k.company_norm) AS company_norm, COUNT(DISTINCT k.contact_key) AS n
                FROM contacts k LEFT JOIN companies c ON c.company_norm = k.company_norm GROUP BY 1`),
    db.prepare("SELECT id, company, classmate, contact, title, note, added_at FROM manual_connections ORDER BY added_at"),
    // deep connections: people known by 2+ classmates, and which classmates know them
    db.prepare(`SELECT s.contact_key, s.company_norm, c.display_name, s.title_bucket, s.depth, s.first_connected_year
                FROM shared_contacts s LEFT JOIN companies c ON c.company_norm = s.company_norm
                ORDER BY s.depth DESC, s.first_connected_year`),
    db.prepare(`SELECT k.contact_key, k.connector_id, k.connected_year
                FROM contacts k JOIN shared_contacts s ON s.contact_key = k.contact_key`),
    // which classmates already have each other as LinkedIn connections (by key, no names)
    db.prepare(`SELECT p.person_id AS classmate, k.connector_id AS knower
                FROM people p JOIN contacts k ON k.contact_key = p.self_key WHERE p.self_key IS NOT NULL`),
    // classmates' own work history, for "Classmate worked here"
    db.prepare("SELECT person_id, company_norm, title, title_bucket, started_on, finished_on, is_current FROM positions"),
  ]);
  return {
    people: people.results, parents: companies.results, aliases: aliases.results, counts: counts.results,
    contact_buckets: buckets.results, unique_by_company: uniqueByCompany.results, unique_by_root: uniqueByRoot.results,
    manual: manual.results, shared: shared.results, shared_links: sharedLinks.results, knows: knows.results,
    positions: positions.results,
  };
}

// ---- the job board's roles (cohort-api/push_jobs.py loads them; one version per build) ----
async function currentBuild(db, kind) {
  return db.prepare(`SELECT build_id, generated, pushed_at, jobs, kind FROM job_builds WHERE complete = 1 AND kind = ?
                     ORDER BY pushed_at DESC LIMIT 1`).bind(kind).first();
}

// The newest complete build of one kind, in the shape the page expects (window.BOARD_DATA for "board").
// Rows already hold JSON text, so the response is stitched together without parsing every role.
// limit/offset page through a large build (the "all" set): pages share the build_id so a caller can check
// it didn't change mid-way; the build's other keys come with every page.
async function boardData(db, kind, limit = 0, offset = 0) {
  const b = await currentBuild(db, kind);
  if (!b) return json({ error: "no jobs loaded" }, 404);
  const jobsQuery = limit
    ? db.prepare("SELECT data FROM jobs WHERE build_id = ? AND seq >= ? ORDER BY seq LIMIT ?").bind(b.build_id, offset, limit)
    : db.prepare("SELECT data FROM jobs WHERE build_id = ? ORDER BY seq").bind(b.build_id);
  const [rows, meta] = await db.batch([
    jobsQuery,
    db.prepare("SELECT key, value FROM job_build_meta WHERE build_id = ? ORDER BY key, part").bind(b.build_id),
  ]);
  const values = {};
  for (const m of meta.results) values[m.key] = (values[m.key] || "") + m.value;
  const parts = Object.keys(values).map((k) => JSON.stringify(k) + ":" + values[k]);
  parts.push('"build_id":' + JSON.stringify(b.build_id));
  parts.push('"jobs":[' + rows.results.map((r) => r.data).join(",") + "]");
  return new Response("{" + parts.join(",") + "}", {
    headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" },
  });
}

async function addManual(request, db) {
  const d = await body(request);
  if (!d) return json({ error: "bad JSON" }, 400);
  const clean = (k) => String((d && d[k]) || "").replace(/\s+/g, " ").trim().slice(0, LIMITS[k]);
  const entry = {
    id: crypto.randomUUID().replace(/-/g, "").slice(0, 12),
    company: clean("company"), classmate: clean("classmate"), contact: clean("contact"),
    title: clean("title"), note: clean("note"), added_at: new Date().toISOString().slice(0, 19) + "+00:00",
  };
  if (!entry.company || !entry.classmate || !(entry.contact || entry.title)) {
    return json({ error: "company, classmate, and a contact name or role are required" }, 400);
  }
  await db.prepare("INSERT INTO manual_connections (id, company, classmate, contact, title, note, added_at) VALUES (?,?,?,?,?,?,?)")
    .bind(entry.id, entry.company, entry.classmate, entry.contact, entry.title, entry.note, entry.added_at).run();
  return json(entry, 201);
}

function json(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status, headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" },
  });
}
