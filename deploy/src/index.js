// The hosted cohort board: one Worker in front of one container running cohort-board/serve.py unchanged.
// Classmates and contacts live in the cohort database (the cohort-api Worker + D1, cohort-api/), which the board reaches
// with COHORT_API_URL and COHORT_API_TOKEN. Its other files (job lists, company directory, logins) stay on the
// container's disk; this Worker stores them in R2 (/__state/<name>) so they survive restarts and redeploys
// (cohort-board/state.py pulls them at start and pushes after every change).
//
// Scheduled work (wrangler.jsonc "triggers"), what the board did on a computer with its own timers:
//   every 15 minutes  if the cohort database has Muse findings or finished company research waiting (GET /v1/pending),
//                     wake the container and merge them (POST /__task/merge). Nothing waiting: the container stays asleep.
//   daily             the job refresh that used to run on Ryan's PC (POST /__task/refresh; cohort-board/tasks.py).
// The container sleeps after 10 idle minutes, but not while a task is running (onActivityExpired asks it).
import { Container, getContainer } from "@cloudflare/containers";

const DAILY = "0 9 * * *";      // 09:00 UTC = early morning in the US; must match wrangler.jsonc

export class Board extends Container {
  defaultPort = 8765;
  sleepAfter = "10m";           // stops when nobody has used it for 10 minutes; the next visit starts it again

  constructor(ctx, env) {
    super(ctx, env);
    this.envVars = {
      COHORT_HOST: "0.0.0.0",
      COHORT_PORT: "8765",
      COHORT_PASSWORD: env.BOARD_PASSWORD || "",
      COHORT_CONTACT_KEY: env.CONTACT_KEY || "",
      COHORT_STATE_URL: env.PUBLIC_URL || "",
      COHORT_STATE_TOKEN: env.STATE_TOKEN || "",
      ANTHROPIC_API_KEY: env.ANTHROPIC_API_KEY || "",
      COHORT_API_URL: env.COHORT_API_URL || "",       // the cohort database (cohort-api Worker on this account)
      COHORT_API_TOKEN: env.COHORT_API_TOKEN || "",
    };
  }

  // Idle: sleep, unless the daily refresh (or another task) is still running.
  async onActivityExpired() {
    try {
      const r = await this.containerFetch(new Request("http://board/__task/busy", {
        method: "POST", headers: { "X-Task-Token": this.env.STATE_TOKEN || "" } }), this.defaultPort);
      if (r.ok && (await r.json()).busy) {
        this.renewActivityTimeout();
        return;
      }
    } catch (e) {
      console.error("busy check failed", e);
    }
    await this.stop();
  }
}

const NAME = /^[A-Za-z0-9_.-]{1,100}$/;

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname.startsWith("/__state/")) return state(request, env, url.pathname.slice("/__state/".length));
    if (url.pathname.startsWith("/__task/")) return new Response("not found", { status: 404 });   // only the schedule runs tasks
    return getContainer(env.BOARD).fetch(request);          // a single instance: one board, one set of files
  },

  async scheduled(event, env, ctx) {
    ctx.waitUntil(event.cron === DAILY ? task(env, "refresh") : mergeIfWaiting(env));
  },
};

async function task(env, name) {
  const r = await getContainer(env.BOARD).fetch(new Request(`https://board/__task/${name}`, {
    method: "POST", headers: { "X-Task-Token": env.STATE_TOKEN || "" } }));
  const text = await r.text();
  console.log(`task ${name}: ${r.status} ${text.slice(0, 500)}`);
}

async function mergeIfWaiting(env) {
  const r = await fetch(`${env.COHORT_API_URL}/v1/pending`, { headers: { Authorization: `Bearer ${env.COHORT_API_TOKEN}` } });
  if (!r.ok) {
    console.error(`pending check failed: ${r.status}`);
    return;
  }
  const p = await r.json();
  if (p.muse_inbox + p.muse_manual + p.research_done > 0) await task(env, "merge");
}

async function state(request, env, name) {
  if (!(await authorized(request, env))) return new Response("unauthorized", { status: 401 });
  if (!NAME.test(name)) return new Response("bad name", { status: 400 });
  if (request.method === "GET") {
    const obj = await env.STATE.get(name);
    if (!obj) return new Response("not found", { status: 404 });
    return new Response(obj.body, { headers: { "Content-Type": "application/octet-stream", ETag: obj.httpEtag } });
  }
  if (request.method === "PUT") {
    await env.STATE.put(name, request.body);
    return new Response(null, { status: 204 });
  }
  if (request.method === "DELETE") {
    await env.STATE.delete(name);
    return new Response(null, { status: 204 });
  }
  return new Response("method not allowed", { status: 405 });
}

async function authorized(request, env) {
  const expected = env.STATE_TOKEN || "";
  const got = (request.headers.get("Authorization") || "").replace(/^Bearer\s+/i, "");
  if (!expected || got.length !== expected.length) return false;
  const enc = new TextEncoder();
  return crypto.subtle.timingSafeEqual(enc.encode(got), enc.encode(expected));
}
