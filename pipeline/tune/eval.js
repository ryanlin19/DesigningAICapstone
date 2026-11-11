// Score the matcher against hand-written cases (resumes_private/cases.json):   node pipeline/tune/eval.js [--site site]
// A role counts as a fit if its category is in fit_categories or its title matches fit_title (and is not in bad_categories).
// Reports, per resume, how many of the top 10 / top 20 roles are fits, and how many roles score 75+.
const fs = require("fs"), path = require("path");
const { ROOT, load, resumes } = require("./lib");
const i = process.argv.indexOf("--site"), { api, jobs } = load(i > 0 ? process.argv[i + 1] : "site");
const cases = JSON.parse(fs.readFileSync(path.join(ROOT, "resumes_private", "cases.json"), "utf8"));
let sum10 = 0, sum20 = 0, n = 0;
resumes().filter(r => cases[r.id]).forEach(r => {
  const c = cases[r.id], p = api.analyzeResume(r.text); api.setProfile(p);
  const fitRe = c.fit_title ? new RegExp(c.fit_title, "i") : null, bad = c.bad_categories || [];
  const isFit = j => !bad.includes(j.category) && ((c.fit_categories || []).includes(j.category) || (fitRe && fitRe.test(j.title)));
  const scored = jobs.map(j => { const f = api.fitOf(j); return f ? { j, pct: f.pct } : null; }).filter(Boolean).sort((a, b) => b.pct - a.pct);
  const f10 = scored.slice(0, 10).filter(x => isFit(x.j)).length, f20 = scored.slice(0, 20).filter(x => isFit(x.j)).length;
  const base = jobs.filter(isFit).length / jobs.length;
  sum10 += f10; sum20 += f20; n++;
  console.log(r.id + "  top10 fits " + f10 + "/10, top20 fits " + f20 + "/20 | chance would be " + Math.round(base * 10) + "/10 | roles 75+: " + scored.filter(x => x.pct >= 75).length +
    " | years " + p.years + " | role types: " + (Object.keys(p.fns).join(", ") || "none"));
});
if (n) console.log("average: top10 " + (sum10 / n).toFixed(1) + "/10, top20 " + (sum20 / n).toFixed(1) + "/20");
