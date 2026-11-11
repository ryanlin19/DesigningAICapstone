// Cohort connections API: a thin layer over one SQL database (Cloudflare D1).
// Every route except /v1/health needs "Authorization: Bearer <API_TOKEN>".
// Bulk loading is not done here: cohort-api/sync.py loads exports with `wrangler d1 execute`.
//
//   GET    /v1/health          -> {ok: true}
//   GET    /v1/snapshot        -> everything the board needs, in one call, including shared contacts
//   GET    /v1/jobs/version    -> the current jobs build {build_id, generated, pushed_at, jobs}; ?kind=all for every posting
//   GET    /v1/jobs            -> the current build's roles, shaped like the page's window.BOARD_DATA; ?kind=all likewise
//   POST   /v1/manual          -> add a hand-entered connection {company, classmate, contact, title, note}
//   DELETE /v1/manual/:id      -> remove one

const LIMITS = { company: 200, classmate: 80, contact: 80, title: 120, note: 300 };

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    try {
      if (url.pathname === "/v1/health") return json({ ok: true });
      if (!(await authorized(request, env))) return json({ error: "unauthorized" }, 401);

      if (request.method === "GET" && url.pathname === "/v1/snapshot") return json(await snapshot(env.DB));
      const kind = url.searchParams.get("kind") === "all" ? "all" : "board";
      if (request.method === "GET" && url.pathname === "/v1/jobs/version") {
        const b = await currentBuild(env.DB, kind);
        return b ? json(b) : json({ error: "no jobs loaded" }, 404);
      }
      if (request.method === "GET" && url.pathname === "/v1/jobs") {
        const limit = Math.min(10000, parseInt(url.searchParams.get("limit") || "0", 10) || 0);
        const offset = Math.max(0, parseInt(url.searchParams.get("offset") || "0", 10) || 0);
        return boardData(env.DB, kind, limit, offset);
      }
      if (request.method === "POST" && url.pathname === "/v1/manual") return addManual(request, env.DB);
      const m = url.pathname.match(/^\/v1\/manual\/([0-9a-f]{12})$/);
      if (request.method === "DELETE" && m) {
        const r = await env.DB.prepare("DELETE FROM manual_connections WHERE id = ?").bind(m[1]).run();
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
  let d;
  try { d = await request.json(); } catch { return json({ error: "bad JSON" }, 400); }
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
