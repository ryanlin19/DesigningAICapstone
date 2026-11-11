// "Your search": the panel down the left side of every tab, plus the Fit row at the top right. Together they hold the
// filters that follow you everywhere (functions, fit, sponsorship, location) and "Revert to everything".
// Everything starts on every job. "What you are" (resume or filled in) only scores fit; "What you want" filters by
// function (7 groups of the job categories). A resume upload fills "What you want" with the same functions.
// Pages read them through window.Global:
//   Global.state()            -> {visa: "any"|"not_no"|"likely", regions: [...], buckets: [...]}
//   Global.setFitCounts(c)    -> show {bucket: n} counts in the Fit row
//   Global.profile()          -> "What you are" (from a resume or filled in by hand) once it has a field or a skill, else null
//   Global.want()             -> "What you want": {categories, levels, verticals, companies, avoid, salary_min}
//   Global.passes(job)        -> sponsorship + location check, for pages that filter in the browser
//   Global.bucket(job)        -> fit bucket for a job with {bcat, blevel, min_years}, or null without a resume
//   Global.onChange(fn)       -> called after any change in the panel
//   Global.onRevert(fn)       -> what "Revert to everything" also resets on this page
(function () {
  var KEY = "cohort.global", PROFILE = "cohort.profile", WANT = "cohort.want", PAGE_FILTERS = "cohort.findFilters";
  var LEVELS = ["Internship", "Entry", "Mid", "Senior", "Executive"];
  var EMPTY_WANT = { categories: [], levels: [], verticals: [], companies: [], avoid: [], salary_min: 0 };
  function want() { var w = Object.assign({}, EMPTY_WANT, load(WANT, {})); return w; }
  var meta = null;                                 // skill names and verticals, from /api/find/meta
  var pathData = null, pathSeq = 0, pathTimer = null;
  var PDFJS = "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.min.js";
  var PDFJS_WORKER = "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js";
  var MAMMOTH = "https://cdnjs.cloudflare.com/ajax/libs/mammoth/1.6.0/mammoth.browser.min.js";
  // The sidebar shows 7 functions; each covers one or more of the job categories above (plus "Other").
  var FUNCTIONS = [
    ["Consulting", ["Consulting"]],
    ["Strategy & Ops", ["Strategy & Operations", "Operations & Supply Chain"]],
    ["Finance", ["Finance"]],
    ["Marketing & Sales", ["Marketing & Growth", "Sales & Business Development"]],
    ["Product & Tech", ["Product", "Technology & Engineering"]],
    ["Data & Analytics", ["Data & Analytics"]],
    ["People, Legal & Other", ["People & HR", "Legal & Policy", "Other"]]
  ];
  var ALL_CATS = [].concat.apply([], FUNCTIONS.map(function (f) { return f[1]; }));
  function catsOf(names) { return [].concat.apply([], FUNCTIONS.filter(function (f) { return names.indexOf(f[0]) >= 0; }).map(function (f) { return f[1]; })); }
  // functions touched by a list of categories (a resume's "Product" lights up "Product & Tech")
  function functionsOf(cats) { return FUNCTIONS.filter(function (f) { return f[1].some(function (c) { return cats.indexOf(c) >= 0; }); }).map(function (f) { return f[0]; }); }
  function normCats(cats) { return cats.length >= ALL_CATS.length ? [] : cats; }   // every function picked = no filter
  var VISA = [["any", "Any", "Show every role"], ["not_no", "Not “no”", "Hide roles that say they won't sponsor"],
              ["likely", "Likely", "Only roles likely to sponsor a visa"]];

  function load(k, d) { try { var v = localStorage.getItem(k); return v ? JSON.parse(v) : d; } catch (e) { return d; } }
  function save(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* private mode */ } }
  function el(tag, attrs, kids) {
    var n = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      if (k === "class") n.className = attrs[k]; else if (k === "text") n.textContent = attrs[k]; else n.setAttribute(k, attrs[k]);
    });
    (kids || []).forEach(function (c) { if (c != null) n.appendChild(typeof c === "string" ? document.createTextNode(c) : c); });
    return n;
  }
  function fmtN(n) { return Math.round(n || 0).toLocaleString("en-US"); }
  // a profile counts once it says something: a field or a skill (a hand-filled one starts empty)
  function usable(p) { return p && ((p.categories || []).length || (p.skills || []).length) ? p : null; }

  // ---------- state (moved over from the old per-page filters the first time) ----------
  var DEFAULT_BUCKETS = ["ready", "reach", "overqualified", "pivot"];   // every job until you narrow it
  var BUCKETS = [["ready", "Ready", "Your field, your level"], ["reach", "Reach", "Asks more experience, or a neighbouring field"],
                 ["overqualified", "Overqualified", "Below your level"], ["pivot", "Serious pivot", "A different field"]];
  var state = load(KEY, null);
  if (!state) {
    var old = load(PAGE_FILTERS, {});
    state = { visa: old.hide_unlikely ? "not_no" : "any", regions: (old.regions || []).slice(), buckets: (old.buckets || DEFAULT_BUCKETS).slice() };
    save(KEY, state);
  }
  state.regions = state.regions || [];
  state.buckets = state.buckets || DEFAULT_BUCKETS.slice();
  if (state.v !== 2) {                                    // once: the old default hid jobs outside Ready + Reach
    state.v = 2; state.buckets = DEFAULT_BUCKETS.slice(); save(KEY, state);
  }
  var listeners = [], revertFn = null, regionCounts = null, fitCounts = null;

  function changed() { save(KEY, state); draw(); listeners.forEach(function (fn) { fn(state); }); schedulePath(); }

  // ---------- fit (same rules as find.py, for pages that score jobs in the browser) ----------
  var ADJ = {
    "Consulting": ["Strategy & Operations", "Finance", "Data & Analytics"],
    "Strategy & Operations": ["Consulting", "Finance", "Operations & Supply Chain", "Product", "Data & Analytics"],
    "Finance": ["Strategy & Operations", "Consulting", "Data & Analytics"],
    "Data & Analytics": ["Product", "Finance", "Strategy & Operations", "Technology & Engineering", "Consulting"],
    "Product": ["Data & Analytics", "Marketing & Growth", "Technology & Engineering", "Strategy & Operations"],
    "Marketing & Growth": ["Product", "Sales & Business Development"],
    "Sales & Business Development": ["Marketing & Growth", "Strategy & Operations"],
    "Operations & Supply Chain": ["Strategy & Operations"], "Technology & Engineering": ["Data & Analytics", "Product"],
    "People & HR": ["Strategy & Operations"], "Legal & Policy": ["Strategy & Operations"], "Other": []
  };
  var LEVEL_YEARS = { Internship: 0, Entry: 1, Mid: 3, Senior: 7, Executive: 12 };
  function bucket(job) {
    var p = usable(load(PROFILE, null));
    if (!p || !(p.categories || []).length || !job.bcat) return null;
    var mine = p.categories, jc = job.bcat;
    var field = mine.indexOf(jc) >= 0 ? "strong" : mine.some(function (c) { return (ADJ[c] || []).indexOf(jc) >= 0; }) ? "partial" : "none";
    var years = Math.max(0, +p.years || 0), eff = years + (p.mba ? 2 : 0), lvl = job.blevel || "Mid";
    var asks = job.min_years != null ? job.min_years : LEVEL_YEARS[lvl];
    var level = lvl === "Internship" || (lvl === "Entry" && (p.mba || years >= 4)) || eff - asks > 6 ? "over"
              : asks - eff >= 2 || (lvl === "Executive" && eff < 12) ? "under" : "right";
    if (field === "none") return "pivot";
    if (level === "over") return "overqualified";
    if (level === "under" || field === "partial") return "reach";
    return "ready";
  }
  function passes(job) {
    var b = bucket(job);                                    // fit: only with a resume, and only for jobs it can score
    if (b && state.buckets.indexOf(b) < 0) return false;
    var picked = want().categories;                         // the functions you want; none picked = every job
    if (picked.length && picked.indexOf(job.bcat || "Other") < 0) return false;
    if (state.visa === "not_no" && job.visa === "Unlikely") return false;
    if (state.visa === "likely" && job.visa !== "Likely") return false;
    if (state.regions.length) {
      var r = job.regions || [];
      if (!r.some(function (x) { return state.regions.indexOf(x) >= 0; })) return false;
    }
    return true;
  }

  // ---------- resume ----------
  function loadScript(src) {
    return new Promise(function (ok, bad) {
      var s = document.createElement("script"); s.src = src; s.onload = ok;
      s.onerror = function () { bad(new Error("Couldn't load the file reader. Check your internet connection.")); };
      document.head.appendChild(s);
    });
  }
  function readFile(file) {
    var name = file.name.toLowerCase();
    if (name.endsWith(".txt")) return file.text();
    if (name.endsWith(".docx")) {
      return loadScript(MAMMOTH).then(function () { return file.arrayBuffer(); })
        .then(function (buf) { return window.mammoth.extractRawText({ arrayBuffer: buf }); }).then(function (r) { return r.value; });
    }
    if (name.endsWith(".pdf")) {
      return loadScript(PDFJS).then(function () { window.pdfjsLib.GlobalWorkerOptions.workerSrc = PDFJS_WORKER; return file.arrayBuffer(); })
        .then(function (buf) { return window.pdfjsLib.getDocument({ data: buf }).promise; }).then(function (pdf) {
          var pages = [];
          for (var i = 1; i <= pdf.numPages; i++) pages.push(pdf.getPage(i).then(function (p) { return p.getTextContent(); }));
          return Promise.all(pages).then(function (cs) {
            return cs.map(function (c) { return c.items.map(function (it) { return it.str + (it.hasEOL ? "\n" : " "); }).join(""); }).join("\n");
          });
        });
    }
    return Promise.reject(new Error("Use a PDF, Word (.docx) or text file."));
  }
  var status = "";
  function upload(file) {
    status = "Reading " + file.name + "…"; draw();
    readFile(file).then(function (text) {
      return fetch("/api/resume", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text: text }) });
    }).then(function (r) { return r.ok ? r.json() : r.text().then(function (t) { throw new Error(t); }); }).then(function (p) {
      save(PROFILE, p);
      var f = load(PAGE_FILTERS, {}); f.sort = "fit"; save(PAGE_FILTERS, f);
      // the resume sets what you are, and fills "What you want" with the same functions (add more there)
      var fns = functionsOf(p.categories || []);
      if (fns.length) { var w = want(); w.categories = normCats(catsOf(fns)); save(WANT, w); }
      status = "Read " + file.name + ". Check your fields below."; editing = true; changed();
    }).catch(function (e) { status = e.message; draw(); });
  }
  function startByHand() {                                  // the same boxes a resume fills, without one
    save(PROFILE, { years: 0, mba: false, categories: [], category_scores: {}, skills: [], inds: [], manual: true });
    var f = load(PAGE_FILTERS, {}); f.sort = "fit"; save(PAGE_FILTERS, f);    // Find a job sorts by fit once a field is picked
    status = "Pick your functions and skills below; every tab uses them like a resume."; editing = true; changed();
  }
  function setProfile(fn) { var p = load(PROFILE, null); if (!p) return; fn(p); save(PROFILE, p); changed(); }
  function setWant(fn) { var w = want(); fn(w); save(WANT, w); changed(); }

  // ---------- your path: closest gaps across the roles you aim at (from /api/find) ----------
  function schedulePath() {
    clearTimeout(pathTimer);
    pathTimer = setTimeout(fetchPath, 350);
  }
  function fetchPath() {
    var p = usable(load(PROFILE, null));
    if (!p) { pathData = null; draw(); return; }
    var seq = ++pathSeq;
    fetch("/api/find", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ profile: p, want: want(), filters: { visa: state.visa, regions: state.regions }, limit: 0, path: true }) })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (res) { if (seq === pathSeq) { pathData = res && res.path; draw(); } })
      .catch(function () { /* the panel just shows no path */ });
  }

  // ---------- small editors: chips you toggle, and a list you add words to ----------
  function chipPicker(options, picked, onToggle) {
    return el("div", { class: "gb-chips" }, options.map(function (o) {
      var on = picked.indexOf(o) >= 0;
      var b = el("button", { type: "button", class: "gb-chip", "aria-pressed": String(on), text: o });
      b.addEventListener("click", function () { onToggle(o); });
      return b;
    }));
  }
  // chips with an "All" chip first: nothing picked = all. Clicking one while on All picks just it; the last one off,
  // or every one on, is All again.
  function allPicker(options, picked, allLabel, setList) {
    var all = !picked.length;
    var a = el("button", { type: "button", class: "gb-chip", "aria-pressed": String(all), text: allLabel });
    a.addEventListener("click", function () { setList([]); });
    return el("div", { class: "gb-chips" }, [a].concat(options.map(function (o) {
      var on = !all && picked.indexOf(o) >= 0;
      var b = el("button", { type: "button", class: "gb-chip", "aria-pressed": String(on), text: o });
      b.addEventListener("click", function () {
        var next = on ? picked.filter(function (x) { return x !== o; }) : (all ? [] : picked).concat([o]);
        setList(next.length >= options.length ? [] : next);
      });
      return b;
    })));
  }
  function toggleIn(list, x) { var i = list.indexOf(x); if (i >= 0) list.splice(i, 1); else list.push(x); }
  function wordList(items, placeholder, label, onAdd, onRemove) {
    var input = el("input", { type: "text", class: "gb-input", placeholder: placeholder, "aria-label": label });
    input.addEventListener("keydown", function (e) {
      if (e.key === "Enter" && input.value.trim()) { e.preventDefault(); onAdd(input.value.trim()); }
    });
    var chips = items.map(function (x) {
      var b = el("button", { type: "button", class: "gb-chip", "aria-pressed": "true", title: "Remove " + x }, [x, el("span", { "aria-hidden": "true", text: " ×" })]);
      b.addEventListener("click", function () { onRemove(x); });
      return b;
    });
    return el("div", { class: "gb-words" }, [chips.length ? el("div", { class: "gb-chips" }, chips) : null, input]);
  }

  // ---------- the panel ----------
  var bar = null, editing = false, open = false;
  function section(title, kids) { return el("section", { class: "gb-sec" }, [el("h3", { text: title })].concat(kids)); }

  function draw() {
    if (!bar) return;
    drawFit();
    var body = bar.querySelector(".gb-body"); body.textContent = "";
    var p = load(PROFILE, null);

    // resume
    var file = el("input", { type: "file", accept: ".pdf,.docx,.txt", hidden: "", id: "gbResumeFile" });
    file.addEventListener("change", function () { var f = file.files[0]; file.value = ""; if (f) upload(f); });
    var resume;
    if (!p) {
      var byHand = el("button", { type: "button", class: "gb-link", text: "No resume? Fill it in yourself" });
      byHand.addEventListener("click", startByHand);
      resume = [el("p", { class: "gb-note", text: "Upload it once: every tab sorts jobs by how well they fit you." }),
                el("label", { class: "gb-btn primary", for: "gbResumeFile", text: "Upload resume" }), file,
                el("div", { class: "gb-row" }, [byHand])];
    } else {
      var summary = (p.manual ? "Filled in by hand · " : "") + "About " + p.years + " yr" + (p.years === 1 ? "" : "s") + (p.mba ? " + MBA" : "") +
        (p.categories.length ? " · " + functionsOf(p.categories).join(", ") : " · no functions picked") +
        ((p.skills || []).length ? " · " + p.skills.length + " skill" + (p.skills.length === 1 ? "" : "s") : "");
      var editBtn = el("button", { type: "button", class: "gb-link", "aria-expanded": String(editing), text: editing ? "Done" : "Edit" });
      editBtn.addEventListener("click", function () { editing = !editing; draw(); });
      resume = [el("p", { class: "gb-summary", text: summary }), el("div", { class: "gb-row" }, [
        editBtn, el("label", { class: "gb-link", for: "gbResumeFile", text: p.manual ? "Upload resume" : "Replace" }), removeBtn(p)]), file];
      if (editing) {
        var yrs = el("input", { type: "number", min: "0", max: "40", value: String(p.years), "aria-label": "Years of work experience" });
        yrs.addEventListener("change", function () { setProfile(function (q) { q.years = Math.max(0, +yrs.value || 0); }); });
        var mba = el("input", { type: "checkbox" }); mba.checked = !!p.mba;
        mba.addEventListener("change", function () { setProfile(function (q) { q.mba = mba.checked; }); });
        resume.push(el("label", { class: "gb-field" }, ["About ", yrs, " years of experience"]));
        resume.push(el("label", { class: "gb-check" }, [mba, " MBA (graduating or done)"]));
        resume.push(el("div", { class: "gb-label", text: "Your functions (pick 1 to 3)" }));
        resume.push(chipPicker(FUNCTIONS.map(function (f) { return f[0]; }), functionsOf(p.categories), function (name) {
          setProfile(function (q) {
            var cs = catsOf([name]), on = cs.some(function (c) { return q.categories.indexOf(c) >= 0; });
            q.categories = on ? q.categories.filter(function (c) { return cs.indexOf(c) < 0; })
                              : q.categories.concat(cs.filter(function (c) { return q.categories.indexOf(c) < 0; }));
          });
        }));
        if (meta && meta.skills) {
          var names = (p.skills || []).map(function (k) { return meta.skills[k]; }).filter(Boolean);
          resume.push(el("div", { class: "gb-label", text: "Your skills" }));
          var addSkill = el("select", { "aria-label": "Add a skill" }, [el("option", { value: "", text: "+ Add a skill…" })]);
          meta.skills.map(function (n, i) { return [n, i]; }).filter(function (x) { return (p.skills || []).indexOf(x[1]) < 0; })
            .sort(function (a, b) { return a[0].localeCompare(b[0]); })
            .forEach(function (x) { addSkill.appendChild(el("option", { value: String(x[1]), text: x[0] })); });
          addSkill.addEventListener("change", function () {
            if (addSkill.value !== "") setProfile(function (q) { q.skills = (q.skills || []).concat([+addSkill.value]); });
          });
          resume.push(el("div", { class: "gb-words" }, [names.length ? el("div", { class: "gb-chips" }, (p.skills || []).filter(function (k) { return meta.skills[k]; }).map(function (k) {
            var b = el("button", { type: "button", class: "gb-chip", "aria-pressed": "true", title: "Remove " + meta.skills[k] },
                       [meta.skills[k], el("span", { "aria-hidden": "true", text: " ×" })]);
            b.addEventListener("click", function () { setProfile(function (q) { q.skills = q.skills.filter(function (x) { return x !== k; }); }); });
            return b;
          })) : el("p", { class: "gb-note", text: "None found yet." }), addSkill]));
        }
      }
    }
    if (status) resume.push(el("p", { class: "gb-status", role: "status", text: status }));
    body.appendChild(section("What you are", resume));
    body.appendChild(wantSection());

    // sponsorship
    body.appendChild(section("Visa sponsorship", [el("div", { class: "gb-seg", role: "group", "aria-label": "Visa sponsorship" }, VISA.map(function (v) {
      var b = el("button", { type: "button", "aria-pressed": String(state.visa === v[0]), title: v[2], text: v[1] });
      b.addEventListener("click", function () { state.visa = v[0]; changed(); });
      return b;
    })), el("p", { class: "gb-note", text: VISA.filter(function (v) { return v[0] === state.visa; })[0][2] + "." })]));

    // location
    var loc = [];
    if (state.regions.length) {
      loc.push(el("div", { class: "gb-chips" }, state.regions.map(function (r) {
        var b = el("button", { type: "button", class: "gb-chip", "aria-pressed": "true", title: "Remove " + r }, [r, el("span", { "aria-hidden": "true", text: " ×" })]);
        b.addEventListener("click", function () { state.regions.splice(state.regions.indexOf(r), 1); changed(); });
        return b;
      })));
    } else {
      loc.push(el("p", { class: "gb-note", text: "Anywhere in the US." }));
    }
    var pick = el("select", { "aria-label": "Add a region" }, [el("option", { value: "", text: "+ Add a region…" })]);
    (regionCounts || []).forEach(function (rc) {
      if (state.regions.indexOf(rc[0]) < 0) pick.appendChild(el("option", { value: rc[0], text: rc[0] + " (" + fmtN(rc[1]) + ")" }));
    });
    pick.addEventListener("change", function () { if (pick.value) { state.regions.push(pick.value); changed(); } });
    loc.push(pick);
    loc.push(el("a", { class: "gb-link", href: "/map", text: "Pick on the map →" }));
    body.appendChild(section("Location", loc));
  }
  var editingWant = false;
  function wantSection() {
    var w = want(), kids = [];
    // functions: a filter. "All functions" (nothing picked) shows every job; picking one narrows to it, more add on.
    var all = !w.categories.length, onFns = all ? [] : functionsOf(w.categories);
    var allBtn = el("button", { type: "button", class: "gb-chip", "aria-pressed": String(all), text: "All functions" });
    allBtn.addEventListener("click", function () { setWant(function (q) { q.categories = []; }); });
    var fnChips = FUNCTIONS.map(function (f) {
      var on = onFns.indexOf(f[0]) >= 0;
      var b = el("button", { type: "button", class: "gb-chip", "aria-pressed": String(on), text: f[0], title: f[1].join(", ") });
      b.addEventListener("click", function () {
        setWant(function (q) {
          var names = on ? onFns.filter(function (x) { return x !== f[0]; }) : onFns.concat([f[0]]);
          q.categories = normCats(catsOf(names));            // the last one off, or all of them on, is "All functions" again
        });
      });
      return b;
    });
    kids.push(el("div", { class: "gb-label", text: "Functions" }));
    kids.push(el("div", { class: "gb-chips" }, [allBtn].concat(fnChips)));
    kids.push(el("p", { class: "gb-note", text: all ? "Showing every job. Pick functions to narrow it down."
                                                     : "Showing " + onFns.join(", ") + " jobs." }));

    var bits = [];
    if (w.levels.length) bits.push(w.levels.join(", "));
    if (w.verticals.length) bits.push(w.verticals.join(", "));
    if (w.companies.length) bits.push(w.companies.join(", "));
    if (w.avoid.length) bits.push("avoiding " + w.avoid.join(", "));
    if (w.salary_min) bits.push("$" + w.salary_min + "K+");
    var editBtn = el("button", { type: "button", class: "gb-link", "aria-expanded": String(editingWant),
                                 text: editingWant ? "Done" : (bits.length ? "Edit more targets" : "More targets (optional)") });
    editBtn.addEventListener("click", function () { editingWant = !editingWant; draw(); });
    if (bits.length) kids.push(el("p", { class: "gb-summary", text: bits.join(" · ") }));
    kids.push(el("div", { class: "gb-row" }, [editBtn]));
    if (editingWant) {
      kids.push(el("div", { class: "gb-label", text: "Level" }));
      kids.push(allPicker(LEVELS, w.levels, "All levels", function (l) { setWant(function (q) { q.levels = l; }); }));
      if (meta && meta.verticals) {
        kids.push(el("div", { class: "gb-label", text: "Verticals" }));
        kids.push(allPicker(meta.verticals.filter(function (v) { return v !== "Other"; }), w.verticals, "All verticals",
                            function (l) { setWant(function (q) { q.verticals = l; }); }));
      }
      kids.push(el("div", { class: "gb-label", text: "Companies to aim for" }));
      kids.push(wordList(w.companies, "Type a company, press Enter", "Add a target company",
        function (x) { setWant(function (q) { if (q.companies.indexOf(x) < 0) q.companies.push(x); }); },
        function (x) { setWant(function (q) { toggleIn(q.companies, x); }); }));
      kids.push(el("div", { class: "gb-label", text: "Avoid (companies or title words)" }));
      kids.push(wordList(w.avoid, "e.g. recruiter, Amazon", "Add something to avoid",
        function (x) { setWant(function (q) { if (q.avoid.indexOf(x) < 0) q.avoid.push(x); }); },
        function (x) { setWant(function (q) { toggleIn(q.avoid, x); }); }));
      var pay = el("input", { type: "number", min: "0", max: "1000", step: "5", value: w.salary_min ? String(w.salary_min) : "", placeholder: "none",
                              "aria-label": "Lowest salary, in thousands of dollars" });
      pay.addEventListener("change", function () { setWant(function (q) { q.salary_min = Math.max(0, +pay.value || 0); }); });
      kids.push(el("label", { class: "gb-field" }, ["Pay at least $", pay, "K (when listed)"]));
    }
    kids.push(pathBox());
    return section("What you want", kids);
  }
  function pathBox() {
    if (!pathData || !pathData.items || !pathData.items.length) return null;
    var list = el("ol", { class: "gb-path" }, pathData.items.map(function (it) {
      var href = it.kind === "bridge" ? "/?cat=" + encodeURIComponent(it.category) : it.kind === "skill" ? "/?skill=" + it.skill : null;
      return el("li", {}, [href ? el("a", { href: href, text: it.text }) : el("span", { text: it.text })]);
    }));
    return el("div", { class: "gb-pathbox" }, [
      el("div", { class: "gb-label", text: "Closest gaps" }), list,
      el("p", { class: "gb-note", text: "Across " + fmtN(pathData.n) + " of " + pathData.basis + "." })]);
  }

  function removeBtn(p) {
    var b = el("button", { type: "button", class: "gb-link", text: "Remove" });
    b.addEventListener("click", function () {
      if (!confirm(p && p.manual ? "Clear what you filled in?" : "Remove your resume from this browser?")) return;
      try { localStorage.removeItem(PROFILE); } catch (e) { /* ignore */ }
      status = ""; editing = false; changed();
    });
    return b;
  }

  // ---------- the Fit row: top right, under the tabs, on every tab ----------
  function drawFit() {
    var row = document.querySelector(".cb-fitrow");
    if (!row) return;
    var box = row.querySelector(".cb-fit"); box.textContent = "";
    var raw = load(PROFILE, null), has = !!usable(raw);
    box.appendChild(el("span", { class: "cb-fit-label", text: "Fit" }));
    BUCKETS.forEach(function (x) {
      var on = state.buckets.indexOf(x[0]) >= 0;
      var b = el("button", { type: "button", class: "cb-fitbtn fit-" + x[0], "aria-pressed": String(has && on), title: x[2] },
                 [x[1], has && fitCounts ? el("span", { class: "n", text: fmtN(fitCounts[x[0]] || 0) }) : null]);
      if (!has) b.disabled = true;
      b.addEventListener("click", function () {
        var i = state.buckets.indexOf(x[0]);
        if (i >= 0) state.buckets.splice(i, 1); else state.buckets.push(x[0]);
        changed();
      });
      box.appendChild(b);
    });
    if (!has) box.appendChild(el("span", { class: "cb-fit-hint", text: raw ? "Pick your functions on the left to filter by fit"
                                                                          : "Upload your resume (or fill it in) on the left to filter by fit" }));
  }

  function revert() {
    state = { v: 2, visa: "any", regions: [], buckets: DEFAULT_BUCKETS.slice() };
    save(PAGE_FILTERS, { categories: [], levels: [], posted: "0", q: "", mba: false, warm: false,
                         sort: usable(load(PROFILE, null)) ? "fit" : "newest", from: "", to: "", hidden: [] });   // every tab's filters
    var w = want(); w.categories = []; save(WANT, w);    // every function again
    save(KEY, state); draw();
    if (revertFn) revertFn(); else listeners.forEach(function (fn) { fn(state); });
    var b = bar.querySelector(".gb-revert"); b.classList.add("done"); setTimeout(function () { b.classList.remove("done"); }, 700);
  }

  function mount() {
    if (bar) return;
    var toggle = el("button", { type: "button", class: "gb-toggle", "aria-expanded": "false", "aria-controls": "globalBar" }, ["Your search"]);
    toggle.addEventListener("click", function () { open = !open; bar.classList.toggle("open", open); toggle.setAttribute("aria-expanded", String(open)); });
    var revertBtn = el("button", { type: "button", class: "gb-revert", title: "Every filter on every tab back to every job (your resume and other targets stay)" },
                       [el("span", { "aria-hidden": "true", text: "↺ " }), "Revert to everything"]);
    revertBtn.addEventListener("click", revert);
    bar = el("aside", { class: "global-bar", id: "globalBar", "aria-label": "Your search: applies on every tab" }, [
      el("div", { class: "gb-head" }, [el("b", { text: "Your search" }), el("span", { text: "applies on every tab" })]),
      el("div", { class: "gb-body" }), revertBtn]);
    document.body.appendChild(toggle);
    document.body.appendChild(bar);
    document.body.classList.add("has-global-bar");
    var nav = document.querySelector(".cb-nav");
    if (nav && !nav.querySelector(".cb-fitrow")) {
      nav.appendChild(el("div", { class: "cb-fitrow" }, [el("div", { class: "cb-nav-row" }, [
        el("div", { class: "cb-fit", role: "group", "aria-label": "Fit to your resume, on every tab" })])]));
    }
    draw();
    fetch("/api/find/meta").then(function (r) { return r.ok ? r.json() : null; })
      .then(function (m) { if (m) { meta = m; draw(); } }).catch(function () { /* editors just lack skills and verticals */ });
    schedulePath();
    // regions with job counts, for the "Add a region" picker
    fetch("/api/find", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ filters: {}, limit: 0 }) })
      .then(function (r) { return r.ok ? r.json() : null; }).then(function (res) {
        if (!res) return;
        var rc = res.counts.regions || {};
        regionCounts = Object.keys(rc).filter(function (k) { return k !== "Location not given"; })
          .sort(function (a, b) { return rc[b][0] - rc[a][0]; }).map(function (k) { return [k, rc[k][0]]; });
        draw();
      }).catch(function () { /* the picker just stays short */ });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", mount); else mount();

  window.Global = {
    state: function () { return { visa: state.visa, regions: state.regions.slice(), buckets: state.buckets.slice() }; },
    setFitCounts: function (c) { fitCounts = c || null; drawFit(); },
    profile: function () { return usable(load(PROFILE, null)); },
    want: want,
    setRegions: function (list) { state.regions = list.slice(); changed(); },
    toggleRegion: function (r) { var i = state.regions.indexOf(r); if (i >= 0) state.regions.splice(i, 1); else state.regions.push(r); changed(); },
    passes: passes, bucket: bucket,
    onChange: function (fn) { listeners.push(fn); },
    onRevert: function (fn) { revertFn = fn; }
  };
})();
