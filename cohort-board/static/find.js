// Find a job: one card per job. Filter by broad category and level; with a resume, by fit bucket too.
(function () {
  var PDFJS = "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.min.js";
  var PDFJS_WORKER = "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js";
  var MAMMOTH = "https://cdnjs.cloudflare.com/ajax/libs/mammoth/1.6.0/mammoth.browser.min.js";
  var BUCKETS = [
    ["ready", "Ready", "your field, your level"],
    ["reach", "Reach", "asks more experience, or a neighbouring field"],
    ["overqualified", "Overqualified", "below your level"],
    ["pivot", "Serious pivot", "a different field"]
  ];
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
  var profile = load("cohort.profile", null);
  var DEFAULT_FILTERS = { categories: [], buckets: ["ready", "reach"], levels: [], posted: "0", q: "", mba: false,
                          hide_unlikely: false, warm: false, sort: "fit", from: "", to: "", hidden: [] };
  var filters = Object.assign({}, DEFAULT_FILTERS, load("cohort.findFilters", {}));
  filters.hidden = (filters.hidden || []).slice();          // never share the default's list
  var shown = [], total = 0, lastCounts = null, seq = 0;

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
      return loadScript(PDFJS).then(function () {
        window.pdfjsLib.GlobalWorkerOptions.workerSrc = PDFJS_WORKER;
        return file.arrayBuffer();
      }).then(function (buf) { return window.pdfjsLib.getDocument({ data: buf }).promise; }).then(function (pdf) {
        var pages = [];
        for (var i = 1; i <= pdf.numPages; i++) pages.push(pdf.getPage(i).then(function (p) { return p.getTextContent(); }));
        return Promise.all(pages).then(function (contents) {
          return contents.map(function (c) {
            return c.items.map(function (it) { return it.str + (it.hasEOL ? "\n" : " "); }).join("");
          }).join("\n");
        });
      });
    }
    return Promise.reject(new Error("Use a PDF, Word (.docx) or text file."));
  }
  $("resumeFile").addEventListener("change", function () {
    var file = this.files[0]; this.value = "";
    if (!file) return;
    var st = $("resumeStatus"); st.className = "status"; st.textContent = "Reading " + file.name + "…";
    readFile(file).then(function (text) {
      return fetch("/api/resume", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text: text }) });
    }).then(function (r) { return r.ok ? r.json() : r.text().then(function (t) { throw new Error(t); }); }).then(function (p) {
      profile = p; save("cohort.profile", p);
      filters.buckets = ["ready", "reach"]; filters.sort = "fit"; saveFilters();
      st.textContent = "Read " + file.name + ". Check the summary below; you can change any of it.";
      drawProfile(); refresh();
    }).catch(function (e) { st.className = "status bad"; st.textContent = e.message; });
  });
  $("clearResume").addEventListener("click", function () {
    profile = null; try { localStorage.removeItem("cohort.profile"); } catch (e) { /* ignore */ }
    $("resumeStatus").textContent = ""; drawProfile(); refresh();
  });
  $("years").addEventListener("change", function () { if (profile) { profile.years = Math.max(0, +this.value || 0); save("cohort.profile", profile); refresh(); } });
  $("mba").addEventListener("change", function () { if (profile) { profile.mba = this.checked; save("cohort.profile", profile); refresh(); } });

  function drawSort() {
    Array.prototype.forEach.call(document.querySelectorAll(".seg button"), function (b) {
      var s = b.getAttribute("data-sort");
      b.disabled = s === "fit" && !profile;
      b.title = b.disabled ? "Upload a resume to sort by fit" : "";
      b.setAttribute("aria-pressed", String(filters.sort === s));
    });
  }
  function drawProfile() {
    var has = !!profile;
    $("resumeEmpty").hidden = has; $("resumeFull").hidden = !has; $("fitPanel").hidden = !has;
    if (!has && filters.sort === "fit") filters.sort = "newest";
    drawSort();
    if (!has) return;
    $("years").value = profile.years; $("mba").checked = !!profile.mba;
    var box = $("myCats"); box.textContent = "";
    (meta ? meta.categories : []).filter(function (c) { return c !== "Other"; }).forEach(function (c) {
      var on = profile.categories.indexOf(c) >= 0;
      var b = el("button", { type: "button", class: "chip", "aria-pressed": String(on), text: c });
      b.addEventListener("click", function () {
        var i = profile.categories.indexOf(c);
        if (i >= 0) profile.categories.splice(i, 1); else profile.categories.push(c);
        save("cohort.profile", profile); drawProfile(); refresh();
      });
      box.appendChild(b);
    });
    $("skillsFound").textContent = profile.skills && profile.skills.length
      ? "Matched " + plural(profile.skills.length, "skill", "skills") + " from your resume against job descriptions." : "";
  }

  // ---------- filters ----------
  // The company box is a one-off lookup (often opened from a company link), so it isn't remembered between visits.
  function saveFilters() { save("cohort.findFilters", Object.assign({}, filters, { q: "" })); }
  function toggle(list, v) { var i = list.indexOf(v); if (i >= 0) list.splice(i, 1); else list.push(v); }

  function drawFacets(counts) {
    lastCounts = counts;
    var cats = $("cats"); cats.textContent = "";
    (meta ? meta.categories : []).forEach(function (c) {
      var n = (counts.categories || {})[c] || 0, on = filters.categories.indexOf(c) >= 0;
      var b = el("button", { type: "button", class: "chip", "aria-pressed": String(on) }, [c, el("span", { class: "n", text: fmtN(n) })]);
      b.addEventListener("click", function () { toggle(filters.categories, c); refresh(); });
      cats.appendChild(b);
    });
    var lv = $("levels"); lv.textContent = "";
    (meta ? meta.levels : []).forEach(function (l) {
      var n = (counts.levels || {})[l] || 0, on = filters.levels.indexOf(l) >= 0;
      var b = el("button", { type: "button", class: "chip", "aria-pressed": String(on) }, [l, el("span", { class: "n", text: fmtN(n) })]);
      b.addEventListener("click", function () { toggle(filters.levels, l); refresh(); });
      lv.appendChild(b);
    });
    var bk = $("buckets"); bk.textContent = "";
    BUCKETS.forEach(function (x) {
      var on = filters.buckets.indexOf(x[0]) >= 0;
      var b = el("button", { type: "button", class: "bucket b-" + x[0], "aria-pressed": String(on) }, [
        el("b", { text: x[1] }), el("span", { class: "n", text: fmtN((counts.buckets || {})[x[0]] || 0) }), el("small", { text: x[2] })]);
      b.addEventListener("click", function () { toggle(filters.buckets, x[0]); refresh(); });
      bk.appendChild(b);
    });
  }
  function bindInputs() {
    bindValues();
    $("posted").addEventListener("change", function () { filters.posted = this.value; refresh(); });
    $("warm").addEventListener("change", function () { filters.warm = this.checked; refresh(); });
    $("mbaOnly").addEventListener("change", function () { filters.mba = this.checked; refresh(); });
    $("hideUnlikely").addEventListener("change", function () { filters.hide_unlikely = this.checked; refresh(); });
    Array.prototype.forEach.call(document.querySelectorAll(".seg button"), function (b) {
      b.addEventListener("click", function () { filters.sort = b.getAttribute("data-sort"); drawSort(); refresh(); });
    });
    var t = null;
    $("company").addEventListener("input", function () { var v = this.value; clearTimeout(t); t = setTimeout(function () { filters.q = v; refresh(); }, 200); });
    $("reset").addEventListener("click", function () {
      // hidden companies stay hidden: they have their own "Show all companies" reset
      filters = Object.assign({}, DEFAULT_FILTERS, { categories: [], buckets: ["ready", "reach"], levels: [], hidden: filters.hidden,
                                                     sort: profile ? "fit" : "newest" });
      bindValues(); refresh();
    });
  }
  function bindValues() {
    $("posted").value = filters.posted; $("warm").checked = filters.warm; $("mbaOnly").checked = filters.mba;
    $("hideUnlikely").checked = filters.hide_unlikely; $("company").value = filters.q; drawSort();
  }

  // ---------- results ----------
  function refresh(more) {
    saveFilters();
    var my = ++seq, offset = more ? shown.length : 0;
    var body = { profile: profile, filters: Object.assign({}, filters, { buckets: profile ? filters.buckets : [] }), offset: offset, limit: PAGE };
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

  function card(j) {
    var fit = j.bucket ? el("div", { class: "fit" }, [
      el("span", { class: "badge " + j.bucket, text: j.bucket_label }),
      el("div", { class: "why", text: j.reason })]) : null;
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
          el("h3", {}, [el("a", { href: safe(j.url), target: "_blank", rel: "noopener noreferrer", text: j.title })]),
          el("div", { class: "meta" }, [
            el("a", { class: "co", href: "/companies?q=" + encodeURIComponent(j.company), text: j.company }),
            el("span", { text: loc }), el("span", { text: "posted " + ago(j.posted) }),
            j.min_years != null ? el("span", { text: j.min_years + "+ yrs asked" }) : null])]),
        fit]),
      el("div", { class: "tags" }, tags),
      j.skills_hit && j.skills_hit.length ? el("div", { class: "skills", text: "Matches your " + j.skills_hit.join(", ") }) : null,
      el("div", { class: "card-foot" }, [
        window.JobDescription ? window.JobDescription.toggle(j.url) : null,
        el("span", { class: "card-actions" }, [
          el("a", { class: "co-page", href: "/companies?q=" + encodeURIComponent(j.company), title: "Everything at " + j.company + ", with your cohort's ties",
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
    if (t.alumni.length) parts.push("💼 " + (t.alumni.length === 1 ? t.alumni[0] + " worked here" : t.alumni.length + " classmates worked here"));
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
    var foot = [el("a", { href: "/companies?q=" + encodeURIComponent(j.company), text: "Open " + j.company + " on Companies" }),
                el("a", { href: "/companies?view=connect", text: "Connect with these classmates on LinkedIn" })];
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
      list.appendChild(el("div", { class: "empty", text: profile && filters.buckets.length === 0
        ? "Pick at least one fit bucket on the left." : "No jobs match these filters." }));
    } else {
      var start = reset ? 0 : list.children.length;
      shown.slice(start).forEach(function (j) { list.appendChild(card(j)); });
    }
    $("more").hidden = shown.length >= total;
    $("more").textContent = "Show more (" + fmtN(total - shown.length) + " left)";
  }
  $("more").addEventListener("click", function () { refresh(true); });
  document.querySelector(".cb-logout").addEventListener("click", function () {
    fetch("/logout", { method: "POST" }).then(function () { location.href = "/login"; });
  });

  // ---------- posting timeline: postings per day for the jobs in view; drag or click to pick a period ----------
  var DAY = 864e5, WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  var TL_VIEWS = [["30", "30 days"], ["90", "90 days"], ["365", "1 year"], ["all", "All"]];
  var tlView = load("cohort.findTimelineView", "90"), lastTimeline = null;
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

    var views = el("div", { class: "tl-views", role: "group", "aria-label": "Timeline range" }, TL_VIEWS.map(function (v) {
      var b = el("button", { type: "button", "aria-pressed": String(tlView === v[0]), text: v[1] });
      b.addEventListener("click", function () { tlView = v[0]; save("cohort.findTimelineView", tlView); drawTimeline(); });
      return b;
    }));
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
    var linked = new URLSearchParams(location.search).get("company");          // from a company page link
    if (linked) { filters.q = linked; filters.categories = []; filters.levels = []; filters.buckets = ["ready", "reach", "overqualified", "pivot"]; }
    bindInputs(); drawProfile(); refresh();
  });
})();
