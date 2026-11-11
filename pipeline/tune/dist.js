// How spread out are the scores? Prints, per resume, how many of the roles score 90+, 75+ and 55+.   node pipeline/tune/dist.js
const fs = require("fs"), path = require("path"), vm = require("vm");
const ROOT = path.resolve(__dirname, "..", "..");
const html = fs.readFileSync(path.join(ROOT, "site", "index.html"), "utf8");
const a = html.indexOf("var MI = null, profile = null"), b = html.indexOf("function fitClass");
const api = new Function(html.slice(a, b) + "\nreturn {analyzeResume, fitOf, setMI(m){MI=m;MI._sk=vocabRegex(m.skills);MI._in=vocabRegex(m.inds);}, setProfile(p){profile=p;fitCache={};}};")();
const load = (f, k) => { const c = { window: {} }; vm.createContext(c); vm.runInContext(fs.readFileSync(path.join(ROOT, "site", f), "utf8"), c); return c.window[k]; };
api.setMI(load("match_index.js", "MATCH_INDEX"));
const jobs = load("data.js", "BOARD_DATA").jobs.map(j => Object.assign({ url: (j.locations[0] || {}).url }, j));
const dir = path.join(ROOT, "resumes_private", "text"); const rows = [];
fs.readdirSync(dir).sort().forEach(f => {
  api.setProfile(api.analyzeResume(fs.readFileSync(path.join(dir, f), "utf8")));
  const s = jobs.map(j => (api.fitOf(j) || { pct: 0 }).pct);
  rows.push([f.slice(0, 4), s.filter(x => x >= 90).length, s.filter(x => x >= 75).length, s.filter(x => x >= 55).length]);
});
console.log("resume  >=90  >=75  >=55   (of " + jobs.length + " roles)");
rows.forEach(r => console.log(r.join("\t")));
const m = i => rows.map(r => r[i]).sort((x, y) => x - y)[Math.floor(rows.length / 2)];
console.log("median\t" + m(1) + "\t" + m(2) + "\t" + m(3));
