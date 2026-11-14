// Find a job: one card per job. Filter by broad category and level; with a resume, by fit bucket too.
// Your resume, sponsorship and location live in the "Your search" panel (globalbar.js) and apply on every tab.
(function () {
  var PAGE = 40;
  var $ = function (id) { return document.getElementById(id); };

  function el(tag, attrs, kids) {
    var n = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      if (k === "class") n.className = attrs[k]; else if (k === "text") n.textContent = attrs[k]; else n.setAttribute(k, attrs[k]);
    });
    (kids || []).forEach(function (c) { if (c != null) n.appendChild(typeof c === "string" ? document.createTextNode(c) : c); });
    return n;
  }
  function fmtN(n) { return (n || 0).toLocaleString("en-US"); }
  function plural(n, a, b) { return fmtN(n) + " " + (n === 1 ? a : b); }
  function load(k, d) { try { var v = localStorage.getItem(k); return v ? JSON.parse(v) : d; } catch (e) { return d; } }
  function save(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* private mode */ } }

  var meta = null;
  var profile = window.Global ? window.Global.profile() : null;
  var DEFAULT_FILTERS = { categories: [], buckets: ["ready", "reach", "overqualified", "pivot"], levels: [], posted: "0", q: "", skill: "", mba: false,
                          warm: false, sort: "fit", from: "", to: "", hidden: [] };
  function loadFilters() {
    var f = Object.assign({}, DEFAULT_FILTERS, load("cohort.findFilters", {}));
    f.hidden = (f.hidden || []).slice(); f.categories = (f.categories || []).slice(); f.levels = (f.levels || []).slice();
    f.buckets = (f.buckets || []).slice();
    return f;
  }
  var filters = loadFilters();
  var shown = [], total = 0, lastCounts = null, seq = 0;

  // The "Your search" panel: a new resume, sponsorship or location re-runs the search; Revert resets this page too.
  if (window.Global) {
    window.Global.onChange(function () {
      var had = !!profile; profile = window.Global.profile();
      if (profile && !had) filters = loadFilters();        // a new resume sorts by fit; it filters nothing
      drawProfile(); refresh();
    });
    window.Global.onRevert(function () {
      profile = window.Global.profile(); filters = loadFilters();
      bindValues(); drawProfile(); window.scrollTo(0, 0); refresh();
    });
  }

  function drawSort() {
    Array.prototype.forEach.call(document.querySelectorAll(".seg button"), function (b) {
      var s = b.getAttribute("data-sort");
      b.disabled = s === "fit" && !profile;
      b.title = b.disabled ? "Upload a resume to sort by fit" : "";
      b.setAttribute("aria-pressed", String(filters.sort === s));
    });
  }
  function drawProfile() {
    if (!profile && filters.sort === "fit") filters.sort = "newest";
    drawSort();
  }

  // ---------- filters ----------
  // A company opened from a link is a one-off lookup, so it isn't remembered between visits. Fit, sponsorship and
  // location come from the "Your search" panel; this page adds only the timeline period and hidden companies.
  function saveFilters() { save("cohort.findFilters", Object.assign({}, filters, { q: "", skill: "", categories: [] })); }

  function drawFacets(counts) {
    lastCounts = counts;
    if (window.Global) window.Global.setFitCounts(profile ? counts.buckets : null);     // counts in the Fit row
    var bar = $("companyBar"); bar.textContent = "";
    var looks = [];                                   // one-off lookups from links: a company, a skill, a field
    if (filters.q) looks.push(["Company:", filters.q, function () { filters.q = ""; }]);
    if (filters.skill !== "" && filters.skill != null) looks.push(["Needs:", (meta && meta.skills && meta.skills[filters.skill]) || "a skill", function () { filters.skill = ""; }]);
    (filters.categories || []).forEach(function (c) { looks.push(["Field:", c, function () { filters.categories = filters.categories.filter(function (x) { return x !== c; }); }]); });
    bar.hidden = !looks.length;
    looks.forEach(function (l) {
      var chip = el("button", { type: "button", class: "chip hidden-chip", title: "Remove this filter" },
                    [l[1], el("span", { class: "x", "aria-hidden": "true", text: "×" })]);
      chip.addEventListener("click", function () { l[2](); refresh(); });
      bar.appendChild(el("span", { class: "hidden-label", text: l[0] }));
      bar.appendChild(chip);
    });
  }
  function bindInputs() {
    Array.prototype.forEach.call(document.querySelectorAll(".seg button"), function (b) {
      b.addEventListener("click", function () { filters.sort = b.getAttribute("data-sort"); drawSort(); refresh(); });
    });
    drawSort();
  }
  function bindValues() { drawSort(); }

  // ---------- results ----------
  function refresh(more) {
    saveFilters();
    var my = ++seq, offset = more ? shown.length : 0;
    var g = window.Global ? window.Global.state() : { visa: "any", regions: [], buckets: [] };
    var body = { profile: profile, want: window.Global ? window.Global.want() : {}, offset: offset, limit: PAGE,
                 filters: Object.assign({}, filters, { buckets: profile ? g.buckets : [], visa: g.visa, regions: g.regions }) };
    return fetch("/api/find", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })
      .then(function (r) { return r.ok ? r.json() : r.text().then(function (t) { throw new Error(t || "error " + r.status); }); })
      .then(function (res) {
        if (my !== seq) return;
        total = res.total;
        shown = more ? shown.concat(res.jobs) : res.jobs;
        drawFacets(res.counts); drawList(!more);
        if (!more) { lastTimeline = res.timeline; drawTimeline(); }
      }).catch(function (e) { $("list").textContent = ""; $("list").appendChild(el("div", { class: "empty", text: e.message })); });
  }

  function ago(iso) {
    if (!iso) return "date unknown";
    var d = Math.round((Date.now() - new Date(iso + "T00:00:00").getTime()) / 864e5);
    return d <= 0 ? "today" : d === 1 ? "yesterday" : d < 60 ? d + " days ago" : Math.round(d / 30) + " months ago";
  }
  function money(s) {
    if (!s || !s.max) return null;
    var k = function (n) { return n >= 1000 ? "$" + Math.round(n / 1000) + "K" : "$" + n; };
    return s.min && s.min !== s.max ? k(s.min) + "–" + k(s.max) : k(s.max);
  }
  function safe(u) { return /^https?:\/\//i.test(u || "") ? u : "#"; }

  // ---------- Apply: opens the posting; when locations have their own postings, pick one from a menu ----------
  function closeMenus(except) {
    Array.prototype.forEach.call(document.querySelectorAll(".applymenu"), function (m) {
      if (m === except) return;
      m.hidden = true;
      var b = m.previousSibling; if (b && b.setAttribute) b.setAttribute("aria-expanded", "false");
    });
  }
  document.addEventListener("click", function (e) { if (!e.target.closest(".applywrap")) closeMenus(); });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape") closeMenus(); });
  function applyControl(j) {
    if (!j.apply || j.apply.length < 2) {
      return el("a", { class: "apply-btn", href: safe(j.url), target: "_blank", rel: "noopener noreferrer",
                       title: "Open the posting at " + j.company + " to apply", text: "Apply ↗" });
    }
    var btn = el("button", { type: "button", class: "apply-btn", "aria-haspopup": "true", "aria-expanded": "false",
                             title: "This role has a posting per location" }, ["Apply ▾"]);
    var menu = el("ul", { class: "applymenu", hidden: "" }, [el("li", { class: "hdr", text: "Choose a location" })].concat(j.apply.map(function (l) {
      return el("li", {}, [el("a", { href: safe(l.url), target: "_blank", rel: "noopener noreferrer", text: l.name })]);
    })));
    btn.addEventListener("click", function (e) {
      e.stopPropagation();
      var open = menu.hidden;
      closeMenus(menu);
      menu.hidden = !open;
      btn.setAttribute("aria-expanded", String(open));
      if (open) { var first = menu.querySelector("a"); if (first) first.focus(); }
    });
    return el("span", { class: "applywrap" }, [btn, menu]);
  }

  function card(j) {
    var fit = j.bucket ? el("div", { class: "fit" }, [
      el("span", { class: "badge " + j.bucket, text: j.bucket_label }),
      el("div", { class: "why", text: j.reason }),
      j.closer && j.closer.length ? el("div", { class: "closer" }, [el("b", { text: "Closer with: " }), j.closer.join(" · ")]) : null]) : null;
    var tags = [el("span", { class: "tag", text: j.category }), el("span", { class: "tag", text: j.level })];
    if (j.mba) tags.push(el("span", { class: "tag mba", text: j.mba === "title" || j.mba === "required" ? "MBA required" : "MBA preferred" }));
    if (j.visa === "Unlikely") tags.push(el("span", { class: "tag visa-bad", text: "Visa: unlikely" }));
    if (j.visa === "Likely") tags.push(el("span", { class: "tag visa-good", text: "Visa: likely" }));
    var pay = money(j.salary); if (pay) tags.push(el("span", { class: "tag", text: pay }));
    var art;
    if (j.cohort) tags.push(tieButton(j, function () { return art; }));
    var loc = (j.location || "Location not listed") + (j.remote ? " · remote OK" : "");
    return art = el("article", { class: "job" }, [
      el("div", { class: "job-top" }, [
        el("div", { class: "job-main" }, [
          el("h3", {}, [el("a", { href: safe(j.url), target: "_blank", rel: "noopener noreferrer", title: "Open the posting" },
                             [j.title, el("span", { class: "ext", "aria-hidden": "true", text: " ↗" })])]),
          el("div", { class: "meta" }, [
            el("a", { class: "co", href: "/companies?company=" + encodeURIComponent(j.company), text: j.company }),
            el("span", { text: loc }), el("span", { text: "posted " + ago(j.posted) }),
            j.min_years != null ? el("span", { text: j.min_years + "+ yrs asked" }) : null])]),
        fit]),
      el("div", { class: "tags" }, tags),
      j.reasons && j.reasons.length ? el("div", { class: "here-why", text: "★ " + j.reasons.join(" · ") }) : null,
      j.skills_hit && j.skills_hit.length ? el("div", { class: "skills", text: "Matches your " + j.skills_hit.join(", ") }) : null,
      el("div", { class: "card-foot" }, [
        window.JobDescription ? window.JobDescription.toggle(j.url) : null,
        el("span", { class: "card-actions" }, [
          applyControl(j),
          j.cohort
            ? el("a", { class: "co-page", href: "/companies?company=" + encodeURIComponent(j.company) + "&field=" + encodeURIComponent(j.category) + "#graph",
                        title: "Who in your cohort can get you into " + j.company, text: "Go to relationship graph →" })
            : el("a", { class: "co-page", href: "/companies?company=" + encodeURIComponent(j.company), title: "Everything at " + j.company,
                        text: j.company + " company page →" }),
          hideButton(j.company)])])
    ]);
  }

  // ---------- cohort ties: a dropdown on each card listing everyone in the database tied to the company ----------
  var FIELD = { engineering: "engineering", data_ml: "data / ML", product: "product", design: "design", recruiting: "recruiting",
    sales_gtm: "sales / GTM", marketing: "marketing", finance: "finance", consulting: "consulting", research: "research",
    operations: "operations", legal: "legal", healthcare: "healthcare", education: "education", student_intern: "students / interns",
    leadership: "leadership" };
  function tieSummary(t) {
    var parts = [];
    var now = t.people.filter(function (p) { return p.worked && p.worked.current; }).length;
    if (t.alumni.length) parts.push("💼 " + (t.alumni.length === 1 ? t.alumni[0] + (now ? " works here" : " worked here")
                                            : t.alumni.length + " classmates " + (now === t.alumni.length ? "work" : "worked") + " here"));
    var knowers = t.people.filter(function (p) { return p.count || p.added.length; }).length;
    if (knowers) parts.push("👥 " + plural(knowers, "classmate", "classmates") + " · " + plural(t.contacts, "contact", "contacts"));
    return parts.join("  ");
  }
  function tieButton(j, getCard) {
    var t = j.cohort;
    var b = el("button", { type: "button", class: "tag tie" + (t.alumni.length ? " alumni" : ""), "aria-expanded": "false",
      title: "Who in your cohort is tied to " + j.company }, [tieSummary(t), el("span", { class: "caret", "aria-hidden": "true", text: "▾" })]);
    var panel = null;
    b.addEventListener("click", function () {
      var open = b.getAttribute("aria-expanded") !== "true";
      b.setAttribute("aria-expanded", String(open));
      if (!panel) { panel = tiePanel(j); getCard().appendChild(panel); }
      panel.hidden = !open;
    });
    return b;
  }
  function tiePanel(j) {
    var t = j.cohort;
    var rows = t.people.map(function (p) {
      var bits = [];
      if (p.worked) {
        bits.push(el("span", { class: "tag alumni", text: (p.worked.current ? "Works here now" : "Worked here") +
          (p.worked.title ? ": " + p.worked.title : "") + (p.worked.years ? ", " + p.worked.years : "") }));
      }
      if (p.count) {
        bits.push(el("span", { class: "tie-line", text: "Knows " + plural(p.count, "person", "people") + " here" +
          (p.bucket && FIELD[p.bucket] ? ", mostly " + FIELD[p.bucket] : "") }));
      }
      p.added.forEach(function (a) {
        var who = [a.contact, a.title].filter(Boolean).join(", ");
        bits.push(el("span", { class: "tie-line", text: "Knows " + (who || "someone") + (a.note ? " (“" + a.note + "”)" : "") }));
      });
      return el("li", {}, [el("b", { text: p.name })].concat(bits));
    });
    var foot = [el("a", { href: "/companies?company=" + encodeURIComponent(j.company) + "&field=" + encodeURIComponent(j.category) + "#graph",
                          text: "Go to relationship graph" }),
                el("a", { href: "/cohort", text: "Your cohort: who to connect with" })];
    if (t.shared) foot.unshift(el("span", { class: "muted", text: plural(t.shared, "person here is", "people here are") + " known by 2+ classmates" }));
    return el("div", { class: "tie-panel" }, [
      el("div", { class: "tie-h", text: "Your cohort at " + j.company }),
      el("ol", { class: "tie-list" }, rows),
      el("div", { class: "tie-foot" }, foot)]);
  }

  // ---------- hidden companies: drop a company that floods the list; undo one at a time or all at once ----------
  function hideButton(company) {
    var b = el("button", { type: "button", class: "hide-co", title: "Hide every job at " + company }, ["⊘ Hide " + company]);
    b.addEventListener("click", function () {
      if (filters.hidden.indexOf(company) < 0) filters.hidden.push(company);
      refresh();
    });
    return b;
  }
  function drawHidden() {
    var bar = $("hiddenBar");
    bar.textContent = "";
    bar.hidden = !filters.hidden.length;
    if (!filters.hidden.length) return;
    bar.appendChild(el("span", { class: "hidden-label", text: "Hidden " + (filters.hidden.length === 1 ? "company" : "companies") + ":" }));
    filters.hidden.slice().sort().forEach(function (c) {
      var chip = el("button", { type: "button", class: "chip hidden-chip", title: "Show " + c + " again" }, [c, el("span", { class: "x", "aria-hidden": "true", text: "×" })]);
      chip.setAttribute("aria-label", "Show " + c + " again");
      chip.addEventListener("click", function () { filters.hidden.splice(filters.hidden.indexOf(c), 1); refresh(); });
      bar.appendChild(chip);
    });
    var all = el("button", { type: "button", class: "linkbtn", text: "Show all companies" });
    all.addEventListener("click", function () { filters.hidden = []; refresh(); });
    bar.appendChild(all);
  }

  function drawList(reset) {
    var list = $("list");
    if (reset) list.textContent = "";
    drawHidden();
    $("count").textContent = plural(total, "job", "jobs");
    if (!shown.length) {
      list.appendChild(el("div", { class: "empty", text: profile && window.Global && window.Global.state().buckets.length === 0
        ? "Pick at least one Fit button at the top right." : "No jobs match these filters." }));
    } else {
      var start = reset ? 0 : list.children.length;
      shown.slice(start).forEach(function (j) { list.appendChild(card(j)); });
    }
    $("more").hidden = shown.length >= total;
    $("more").textContent = "Show more (" + fmtN(total - shown.length) + " left)";
  }
  $("more").addEventListener("click", function () { refresh(true); });

  // ---------- posting timeline: postings per day for the jobs in view; drag or click to pick a period ----------
  var DAY = 864e5, WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  var tlView = "60", lastTimeline = null;                 // always the last 2 months
  function dayNum(iso) { var m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || ""); return m ? Math.floor(Date.UTC(+m[1], m[2] - 1, +m[3]) / DAY) : null; }
  function isoOf(n) { return new Date(n * DAY).toISOString().slice(0, 10); }
  function todayNum() { var d = new Date(); return Math.floor(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()) / DAY); }
  function weekdayOf(n) { return (new Date(n * DAY).getUTCDay() + 6) % 7; }
  function fmtDay(n, year) { return new Date(n * DAY).toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC", year: year ? "numeric" : undefined }); }

  function drawTimeline() {
    var box = $("timeline"), tl = lastTimeline;
    box.textContent = "";
    if (!tl) return;
    var t = todayNum(), dated = 0, earliest = t, perDay = {};
    Object.keys(tl.days).forEach(function (iso) {
      var n = dayNum(iso); if (n === null || n > t) return;
      perDay[n] = (perDay[n] || 0) + tl.days[iso]; dated += tl.days[iso]; if (n < earliest) earliest = n;
    });
    var span = tlView === "all" ? Math.max(t - earliest + 1, 14) : +tlView, weekly = span > 120;
    var binOf = function (n) { return weekly ? n - weekdayOf(n) : n; };
    var first = binOf(t - span + 1), bins = [], index = {}, older = 0;
    for (var n = first; n <= t; n += weekly ? 7 : 1) { index[n] = bins.length; bins.push({ from: n, to: weekly ? n + 6 : n, count: 0 }); }
    Object.keys(perDay).forEach(function (k) {
      var d = +k; if (d < first) { older += perDay[k]; return; }
      bins[index[binOf(d)]].count += perDay[k];
    });
    var max = bins.reduce(function (m, b) { return Math.max(m, b.count); }, 0) || 1;
    var from = dayNum(filters.from), to = dayNum(filters.to);

    var views = el("span", { class: "muted tiny", text: "Last 2 months" });
    box.appendChild(el("div", { class: "tl-h" }, [el("b", { text: "When these jobs were posted" }),
      el("span", { class: "muted tiny", text: plural(dated, "job", "jobs") + " dated" + (tl.undated ? ", " + fmtN(tl.undated) + " without a date" : "") +
        " · one bar per " + (weekly ? "week" : "day") }), views]));

    var bars = el("div", { class: "tl-bars", role: "img", "aria-label": "Jobs posted per " + (weekly ? "week" : "day") + ", up to " + max + " per bar" });
    bins.forEach(function (b) {
      var label = (weekly ? "Week of " + fmtDay(b.from) : new Date(b.from * DAY).toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric", timeZone: "UTC" })) +
        ": " + plural(b.count, "job", "jobs");
      bars.appendChild(el("div", { class: "tl-bar", title: label }, [
        el("span", { class: "tl-fill", style: "height:" + (b.count ? Math.max(3, Math.round(100 * b.count / max)) : 0) + "%" })]));
    });
    paint(bars, bins, from, to);
    box.appendChild(bars);
    box.appendChild(el("div", { class: "tl-axis" }, [el("span", { text: fmtDay(bins[0].from, tlView !== "30" && tlView !== "90") }),
      el("span", { text: fmtDay(bins[Math.floor(bins.length / 2)].from) }), el("span", { text: "today" })]));

    var foot = el("div", { class: "tl-foot" });
    if (from !== null) {
      var clear = el("button", { type: "button", class: "linkbtn", text: "Clear period" });
      clear.addEventListener("click", function () { filters.from = filters.to = ""; refresh(); });
      foot.appendChild(el("span", {}, [el("b", { text: "Posted " + (from === to ? fmtDay(from, true) : fmtDay(from) + " – " + fmtDay(to, true)) }),
        " · jobs without a date are hidden"]));
      foot.appendChild(clear);
    } else {
      foot.appendChild(el("span", { class: "muted", text: "Drag across the bars, or click one, to see only jobs posted then." +
        (older ? " " + plural(older, "job was", "jobs were") + " posted earlier." : "") }));
    }
    var wmax = Math.max.apply(null, tl.weekday) || 1;
    foot.appendChild(el("span", { class: "tl-week", title: "Jobs in view by the weekday they were posted" }, tl.weekday.map(function (c, i) {
      return el("span", { class: "tl-wd", title: WEEKDAYS[i] + ": " + plural(c, "job", "jobs") }, [
        el("span", { class: "tl-wdbar" }, [el("span", { style: "width:" + Math.round(100 * c / wmax) + "%" })]), WEEKDAYS[i]]);
    })));
    box.appendChild(foot);
    brush(bars, bins);
  }
  function paint(bars, bins, from, to) {
    Array.prototype.forEach.call(bars.children, function (bar, i) {
      var on = from !== null && bins[i].to >= from && bins[i].from <= to;
      bar.classList.toggle("sel", on); bar.classList.toggle("dim", from !== null && !on);
    });
  }
  function brush(bars, bins) {
    var anchor = null;
    function at(e) { var r = bars.getBoundingClientRect(); return Math.max(0, Math.min(bins.length - 1, Math.floor((e.clientX - r.left) / r.width * bins.length))); }
    bars.addEventListener("pointerdown", function (e) { anchor = at(e); bars.setPointerCapture(e.pointerId); paint(bars, bins, bins[anchor].from, bins[anchor].to); e.preventDefault(); });
    bars.addEventListener("pointermove", function (e) {
      if (anchor === null) return; var i = at(e);
      paint(bars, bins, bins[Math.min(anchor, i)].from, bins[Math.max(anchor, i)].to);
    });
    bars.addEventListener("pointerup", function (e) {
      if (anchor === null) return;
      var i = at(e), lo = Math.min(anchor, i), hi = Math.max(anchor, i), f = isoOf(bins[lo].from), tt = isoOf(bins[hi].to);
      anchor = null;
      if (lo === hi && filters.from === f && filters.to === tt) { filters.from = filters.to = ""; } else { filters.from = f; filters.to = tt; }
      refresh();
    });
    bars.addEventListener("pointercancel", function () { anchor = null; paint(bars, bins, dayNum(filters.from), dayNum(filters.to)); });
  }

  // ---------- start ----------
  fetch("/api/find/meta").then(function (r) { return r.json(); }).then(function (m) {
    meta = m;
    if (!m.ready) {
      var b = $("banner"); b.hidden = false;
      b.textContent = "The full job list isn't built yet. It's created after the nightly download (pipeline/expand.py).";
      return;
    }
    if (!profile && filters.sort === "fit") filters.sort = "newest";
    var params = new URLSearchParams(location.search);                           // from a company page or "Closest gaps" link
    if (params.get("company")) { filters.q = params.get("company"); filters.categories = []; filters.levels = []; }
    if (params.get("skill")) { filters.skill = params.get("skill"); filters.sort = profile ? "fit" : filters.sort; }
    if (params.get("cat")) { filters.categories = [params.get("cat")]; filters.sort = profile ? "fit" : filters.sort; }
    bindInputs(); drawProfile(); refresh();
  });
})();
