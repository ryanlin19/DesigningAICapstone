// Run the page's own resume matcher on every resume in resumes_private/text/ and write tune_out/matches.json.
//   node pipeline/tune/run_match.js [--site site|public] [--top 15]
// It loads the matching code straight out of index.html, so what is tuned here is what ships.
const fs = require("fs"), path = require("path"), vm = require("vm");
const ROOT = path.resolve(__dirname, "..", "..");
const arg = (n, d) => { const i = process.argv.indexOf("--" + n); return i > 0 ? process.argv[i + 1] : d; };
const SITE = path.join(ROOT, arg("site", "site")), TOP = +arg("top", 15);

const html = fs.readFileSync(path.join(SITE, "index.html"), "utf8");
const a = html.indexOf("var MI = null, profile = null"), b = html.indexOf("function fitClass");
if (a < 0 || b < 0) throw new Error("could not find the matching code in index.html");
const block = html.slice(a, b);
const api = new Function(block + "\nreturn {analyzeResume, fitOf, normText, vocabRegex, termsIn," +
  " setMI(m){MI=m;MI._sk=vocabRegex(m.skills);MI._in=vocabRegex(m.inds);}," +
  " setProfile(p){profile=p;fitCache={};}};")();

const load = (file, key) => { const c = { window: {} }; vm.createContext(c); vm.runInContext(fs.readFileSync(path.join(SITE, file), "utf8"), c); return c.window[key]; };
const MI = load("match_index.js", "MATCH_INDEX"), D = load("data.js", "BOARD_DATA");
api.setMI(MI);
const jobs = D.jobs.map(j => Object.assign({ url: (j.locations[0] || {}).url }, j));

const dir = path.join(ROOT, "resumes_private", "text");
if (!fs.existsSync(dir)) { console.error("run pipeline/tune/extract.py first"); process.exit(1); }
const out = [];
fs.readdirSync(dir).filter(f => f.endsWith(".txt")).sort().forEach((f, n) => {
  const text = fs.readFileSync(path.join(dir, f), "utf8");
  const p = api.analyzeResume(text);
  api.setProfile(p);
  const scored = jobs.map(j => { const r = api.fitOf(j); return r ? { j, pct: r.pct, why: r.why } : null; })
    .filter(Boolean).sort((x, y) => y.pct - x.pct);
  const cats = {};
  scored.slice(0, 50).forEach(x => { cats[x.j.category] = (cats[x.j.category] || 0) + 1; });
  out.push({
    id: "r" + String(n + 1).padStart(3, "0"), file: f, chars: text.length,
    skills: Object.keys(p.skills).map(i => MI.skills[i].l), inds: Object.keys(p.inds).map(i => MI.inds[i].l),
    years: p.years, fns: Object.keys(p.fns), top50_categories: cats,
    scores: { max: scored[0] ? scored[0].pct : 0, p50: scored[Math.floor(scored.length / 2)] ? scored[Math.floor(scored.length / 2)].pct : 0 },
    top: scored.slice(0, TOP).map(x => ({ pct: x.pct, company: x.j.company, title: x.j.title, category: x.j.category, seniority: x.j.seniority, min_years: x.j.min_years, why: x.why.join(" | ") }))
  });
});
fs.mkdirSync(path.join(ROOT, "tune_out"), { recursive: true });
fs.writeFileSync(path.join(ROOT, "tune_out", "matches.json"), JSON.stringify(out, null, 1));
console.log(out.length + " resumes scored against " + jobs.length + " roles -> tune_out/matches.json");
