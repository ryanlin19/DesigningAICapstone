// The hosted cohort board: one Worker in front of one container running cohort-board/serve.py unchanged.
// The board keeps its files on the container's disk; this Worker stores them in R2 (/__state/<name>) so they
// survive restarts and redeploys (cohort-board/state.py pulls them at start and pushes after every change).
import { Container, getContainer } from "@cloudflare/containers";

export class Board extends Container {
  defaultPort = 8765;
  sleepAfter = "20m";           // stops when nobody has used it for 20 minutes; the next visit starts it again

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
      COHORT_API_URL: "",       // the board's own files are the database here
    };
  }
}

const NAME = /^[A-Za-z0-9_.-]{1,100}$/;

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname.startsWith("/__state/")) return state(request, env, url.pathname.slice("/__state/".length));
    return getContainer(env.BOARD).fetch(request);          // a single instance: one board, one set of files
  },
};

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
