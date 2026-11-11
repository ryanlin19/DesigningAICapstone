// Shared loader for the tuning scripts: the page's own matching code, the role data and the match index.
const fs = require("fs"), path = require("path"), vm = require("vm");
const ROOT = path.resolve(__dirname, "..", "..");
exports.ROOT = ROOT;
exports.load = function (site) {
  site = site || "site";
  const html = fs.readFileSync(path.join(ROOT, site, "index.html"), "utf8");
  const a = html.indexOf("var MI = null, profile = null"), b = html.indexOf("function fitClass");
  if (a < 0 || b < 0) throw new Error("could not find the matching code in index.html");
  const api = new Function(html.slice(a, b) + "\nreturn {analyzeResume, fitOf, normText," +
    " setMI(m){MI=m;MI._sk=vocabRegex(m.skills);MI._in=vocabRegex(m.inds);}, setProfile(p){profile=p;fitCache={};}};")();
  const get = (f, k) => { const c = { window: {} }; vm.createContext(c); vm.runInContext(fs.readFileSync(path.join(ROOT, site, f), "utf8"), c); return c.window[k]; };
  const MI = get("match_index.js", "MATCH_INDEX");
  api.setMI(MI);
  const jobs = get("data.js", "BOARD_DATA").jobs.map(j => Object.assign({ url: (j.locations[0] || {}).url }, j));
  return { api, MI, jobs };
};
exports.resumes = function () {
  const dir = path.join(ROOT, "resumes_private", "text");
  return fs.readdirSync(dir).filter(f => f.endsWith(".txt")).sort().map(f => ({ id: f.slice(0, -4), text: fs.readFileSync(path.join(dir, f), "utf8") }));
};
