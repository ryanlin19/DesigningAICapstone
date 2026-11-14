// Map tab: jobs per region as bubbles on a US map, under the same filters as Find a job.
// Clicking a bubble adds or removes that region; the pick is saved with Find a job's filters, so it filters
// Find a job and the Companies page too.
(function () {
  var ATLAS = "https://cdn.jsdelivr.net/npm/us-atlas@3.0.1/states-10m.json";
  var WORLD = "https://cdn.jsdelivr.net/npm/world-atlas@2.0.2/countries-110m.json";
  // What the bubbles count and where: always opens on Jobs, US (not remembered).
  var mode = "jobs", area = "us", world = null, jobCounts = {}, placeData = {};
  var NOUN = { jobs: ["job", "jobs"], people: ["person", "people"], companies: ["company", "companies"] };
  var KEY = "cohort.findFilters";
  var $ = function (id) { return document.getElementById(id); };
  function el(tag, attrs, kids) {
    var n = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      if (k === "class") n.className = attrs[k]; else if (k === "text") n.textContent = attrs[k]; else n.setAttribute(k, attrs[k]);
    });
    (kids || []).forEach(function (c) { if (c != null) n.appendChild(typeof c === "string" ? document.createTextNode(c) : c); });
    return n;
  }
  function fmtN(n) { return Math.round(n || 0).toLocaleString("en-US"); }
  function plural(n, a, b) { return fmtN(n) + " " + (Math.round(n) === 1 ? a : b); }
  function load(k, d) { try { var v = localStorage.getItem(k); return v ? JSON.parse(v) : d; } catch (e) { return d; } }
  function save(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* private mode */ } }

  // Page filters come from Find a job; resume, sponsorship and regions from the "Your search" panel (Global).
  var filters = load(KEY, {});
  var profile = window.Global.profile();
  var sizeBy = load("cohort.mapSize", "w");
  var REGIONS = [], counts = {}, total = 0, states = null;
  filters.regions = window.Global.state().regions;

  function toggle(name) { window.Global.toggleRegion(name); }      // the panel re-runs refresh through onChange
  window.Global.onChange(function () { profile = window.Global.profile(); filters.regions = window.Global.state().regions; refresh(); });
  window.Global.onRevert(function () { filters = load(KEY, {}); filters.regions = []; profile = window.Global.profile(); refresh(); });
  function value(name) { var c = counts[name]; return c ? (sizeBy === "w" ? c[1] : c[0]) : 0; }
  function setCounts() {
    if (mode === "jobs") { counts = jobCounts; return; }
    var d = placeData[mode] || { counts: {} };
    counts = d.counts;
  }
  function loadMode() {                     // People / Companies: counted once per visit, not by the job filters
    if (mode === "jobs" || placeData[mode]) { setCounts(); draw(); drawSide(); return Promise.resolve(); }
    $("mapSub").textContent = "Loading " + NOUN[mode][1] + "…";
    var m = mode;
    return fetch("/api/map-places?mode=" + m).then(function (r) { return r.json(); }).then(function (d) {
      placeData[m] = d; if (m === mode) { setCounts(); draw(); drawSide(); }
    }).catch(function (e) { $("mapSub").textContent = "Couldn't load " + NOUN[m][1] + " (" + e.message + ")."; });
  }
  function loadWorld() {
    if (world) return Promise.resolve();
    return fetch(WORLD).then(function (r) { return r.json(); }).then(function (w) { world = topojson.feature(w, w.objects.countries); });
  }

  // ---------- data ----------
  function refresh() {
    var g = window.Global.state();
    var body = { profile: profile, limit: 0, want: window.Global.want(),
                 filters: Object.assign({}, filters, { buckets: profile ? g.buckets : [], visa: g.visa, regions: g.regions }) };
    return fetch("/api/find", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })
      .then(function (r) { return r.ok ? r.json() : r.text().then(function (t) { throw new Error(t || r.status); }); })
      .then(function (res) {
        jobCounts = res.counts.regions || {}; total = res.total; setCounts();
        window.Global.setFitCounts(profile ? res.counts.buckets : null);
        draw(); drawSide(); drawWho();
      }).catch(function (e) { $("mapSub").textContent = e.message; });
  }

  // ---------- who's there: people your cohort knows at companies in the picked regions ----------
  var whoKey = null, whoSeq = 0, WHO_TOP = 8;
  function drawWho() {
    var box = $("who"), picked = filters.regions.slice();
    var want = window.Global.want ? window.Global.want() : {};
    var key = JSON.stringify([picked, (want.categories || [])[0] || "", !!load("cohort.mapSingle", false)]);
    if (key === whoKey) return;
    whoKey = key;
    box.textContent = "";
    if (!picked.length) {
      $("whoWorked").hidden = true;
      box.appendChild(el("h2", { id: "whoTitle", text: "Who's there" }));
      box.appendChild(el("p", { class: "muted", text: "Click a bubble to see the companies your cohort is tied to there and the people worth knowing." }));
      return;
    }
    box.appendChild(el("p", { class: "muted", text: "Finding who's there…" }));
    var q = new URLSearchParams();
    picked.forEach(function (r) { q.append("region", r); });
    if ((want.categories || [])[0]) q.set("field", want.categories[0]);
    if (load("cohort.mapSingle", false)) q.set("single", "1");
    var seq = ++whoSeq;
    fetch("/api/region-people?" + q.toString()).then(function (r) { return r.json(); }).then(function (d) {
      if (seq === whoSeq) renderWho(box, d);
    }).catch(function (e) { box.textContent = ""; box.appendChild(el("p", { class: "muted", text: "Couldn't load who's there (" + e.message + ")." })); });
  }
  function renderWho(box, d) {
    box.textContent = "";
    var where = d.regions.map(short).join(" + ");
    box.appendChild(el("div", { class: "who-head" }, [
      el("div", {}, [el("h2", { id: "whoTitle", text: "Who's there: " + where }),
        el("p", { class: "muted tiny", text: "People your cohort knows at companies with an office, HQ or open roles here, ranked like the shared connections " +
          "(contacts' own cities aren't in LinkedIn exports). Classmates' cities come from their own LinkedIn jobs and profile." })]),
      el("a", { class: "btn primary", href: "/", text: "See the " + fmtN(d.jobs) + " jobs here →" })]));
    var me = function (n) { return n === d.me ? "You" : n; };
    // a classmate's name, linked to their own LinkedIn profile when the board has it
    var mate = function (n, label) {
      var url = (d.links || {})[n], text = label == null ? me(n) : label;
      return url ? el("a", { class: "who-mate", href: url, target: "_blank", rel: "noopener", title: n + " on LinkedIn", text: text }) : document.createTextNode(text);
    };
    var joined = function (names, fmt) {
      var out = [];
      names.forEach(function (n, i) { if (i) out.push(", "); out.push(fmt(n)); });
      return out;
    };
    // hide companies in several places (offices or open roles in more than one region), which show up in every bubble
    var single = el("input", { type: "checkbox", id: "whoSingle" });
    single.checked = !!d.single;
    single.addEventListener("change", function () { save("cohort.mapSingle", single.checked); drawWho(); });
    box.appendChild(el("label", { class: "chk who-single", for: "whoSingle", title: "Companies with an office or open roles in more than one map region" }, [
      single, " Only companies in one place",
      el("span", { class: "muted tiny", text: d.single ? " (hiding " + plural(d.multi_location, "company", "companies") + " in several places)"
                                                     : " (" + plural(d.multi_location, "company is", "companies are") + " in several places)" })]));
    if (d.classmates.length) box.appendChild(el("p", { class: "who-based" }, [el("b", { text: "Classmates based here: " })]
      .concat(joined(d.classmates, function (n) { return mate(n); }))));
    drawWorked(d, me, mate);
    if (!d.people.length && !d.companies.length) {
      box.appendChild(el("p", { class: "muted", text: "No one in your cohort is tied to a company here yet." }));
      return;
    }
    var cols = el("div", { class: "who-cols" });
    cols.appendChild(listBlock("People to know", d.people, d.people_total, personRow, "person", "people"));
    cols.appendChild(listBlock("Companies with cohort ties", d.companies, d.companies_total, companyRow, "company", "companies"));
    box.appendChild(cols);
    function personRow(x, i) {
      var who = joined(x.known_by, function (k) {
        return el("span", {}, [mate(k.name, k.name === d.me ? "you" : k.name), k.since ? " (" + k.since + ")" : ""]);
      });
      return el("li", { class: "who-row" }, [
        el("span", { class: "who-rank", text: String(i + 1) }),
        el("div", {}, [
          el("div", { class: "who-top" }, [x.url ? el("a", { class: "who-name", href: x.url, target: "_blank", rel: "noopener", text: x.name + " ↗" }) : el("span", { class: "who-name", text: x.name })]),
          el("div", { class: "who-pos" }, [(x.position ? x.position + " · " : ""), el("a", { href: "/companies?id=" + encodeURIComponent(x.company_id) + "#graph", text: x.company })]),
          x.why.length ? el("div", { class: "who-why" }, x.why.map(function (w) {
            return el("span", { class: "tag" + (/^Known by \d/.test(w) ? " shared" : /who work/.test(w) ? " works" : ""), text: w }); })) : null,
          el("div", { class: "who-by" }, ["Known by "].concat(who))])]);
    }
    function companyRow(c, i) {
      var al = c.alumni.map(function (a) {
        return (a.name === d.me ? (a.current ? "You work here" : "You worked here") : a.name + (a.current ? " works here" : " worked here")) +
               (a.here ? ", in " + d.regions.map(short).join(" / ") : "");
      });
      var bits = [c.contacts ? plural(c.contacts, "contact", "contacts") : null, c.jobs ? plural(c.jobs, "open role", "open roles") + " here" : null].filter(Boolean);
      return el("li", { class: "who-row" }, [
        el("span", { class: "who-rank", text: String(i + 1) }),
        el("div", {}, [
          el("div", { class: "who-top" }, [el("a", { class: "who-name", href: "/companies?id=" + encodeURIComponent(c.id) + "#graph", text: c.name }),
                                           el("span", { class: "tag", text: c.vertical })]),
          al.length ? el("div", { class: "who-why" }, al.map(function (t) { return el("span", { class: "tag works", text: t }); })) : null,
          el("div", { class: "who-by", text: bits.join(" · ") + (c.office ? "" : " · no office listed here, but hiring here") })])]);
    }
  }
  // Classmates who've worked in the picked regions: right under the map, one line per classmate with all their jobs here.
  function drawWorked(d, me, mate) {
    var box = $("whoWorked"); box.textContent = "";
    var byPerson = [], seen = {};
    (d.worked_here || []).forEach(function (w) {          // already ordered: current jobs first, then most recent
      if (!(w.name in seen)) { seen[w.name] = byPerson.length; byPerson.push({ name: w.name, jobs: [] }); }
      byPerson[seen[w.name]].jobs.push(w);
    });
    box.hidden = !byPerson.length;
    if (!byPerson.length) return;
    box.appendChild(el("h3", { text: "Classmates who've worked here (" + byPerson.length + ")" }));
    function when(w) { return w.current ? "now" + (w.years ? ", since " + w.years.split("–")[0] : "") : w.years || "dates not listed"; }
    box.appendChild(el("ul", {}, byPerson.map(function (p) {
      var parts = [el("b", {}, [mate(p.name)]), " · "], companies = [], at = {};
      p.jobs.forEach(function (w) {                       // one company, its roles together: "Senior Analyst (…), Analyst (…) at Lyft"
        if (!(w.company in at)) { at[w.company] = companies.length; companies.push({ w: w, roles: [] }); }
        companies[at[w.company]].roles.push(w);
      });
      companies.forEach(function (c, i) {
        if (i) parts.push("; ");
        var roles = c.roles.map(function (w) { return (w.title || "Role") + " (" + when(w) + ")"; }).join(", ");
        parts.push(el("span", { title: c.roles.map(function (w) { return w.location; }).filter(function (x, j, a) { return a.indexOf(x) === j; }).join(" · ") }, [
          roles + " at ",
          c.w.company_id ? el("a", { href: "/companies?id=" + encodeURIComponent(c.w.company_id) + "#graph", text: c.w.company }) : c.w.company]));
      });
      return el("li", {}, parts);
    })));
  }
  function listBlock(title, items, total, row, one, many) {
    var all = false, list = el("ol", { class: "who-list" });
    var btn = el("button", { type: "button", class: "btn who-all" });
    function draw() {
      list.textContent = "";
      (all ? items : items.slice(0, WHO_TOP)).forEach(function (x, i) { list.appendChild(row(x, i)); });
      btn.hidden = items.length <= WHO_TOP;
      btn.textContent = all ? "Show the top " + WHO_TOP : "See all " + fmtN(total) + " " + (total === 1 ? one : many) + (total > items.length ? " (top " + fmtN(items.length) + ")" : "");
    }
    btn.addEventListener("click", function () { all = !all; draw(); });
    draw();
    return el("div", { class: "who-block" }, [el("h3", { text: title + " (" + fmtN(total) + ")" }), list, btn]);
  }

  // ---------- map ----------
  var tip = $("tip");
  function draw() {
    if (!states) return;
    var svg = d3.select("#map"), W = $("map").parentNode.clientWidth, H = Math.round(W * 0.6);
    svg.attr("viewBox", "0 0 " + W + " " + H).attr("width", W).attr("height", H).selectAll("*").remove();
    var global = area === "world" && world;
    if (global) { H = Math.round(W * 0.52); svg.attr("viewBox", "0 0 " + W + " " + H).attr("height", H); }
    var projection = global ? d3.geoNaturalEarth1().fitSize([W, H], { type: "Sphere" }) : d3.geoAlbersUsa().fitSize([W, H], states);
    var path = d3.geoPath(projection);
    svg.append("g").selectAll("path").data(global ? world.features : states.features).join("path").attr("class", "state").attr("d", path);
    $("map").setAttribute("aria-label", (global ? "World" : "US") + " map of " + NOUN[mode][1] + " by region");

    var shapes = {};                                         // country outlines, for countries without office coordinates
    if (world) world.features.forEach(function (f) { shapes[f.properties.name] = f; });
    var countries = mode === "jobs" ? [] : ((placeData[mode] || {}).countries || []).map(function (c) {
      var lat = c.lat, lon = c.lon, f = shapes[c.name];
      if (lat == null && f) { var ct = d3.geoCentroid(f); lon = ct[0]; lat = ct[1]; }
      return { name: c.name, lat: lat == null ? null : lat, lon: lon == null ? null : lon, kind: "country" };
    });
    var outside = d3.sum(countries, function (c) { return value(c.name); });
    var drawn = REGIONS.concat(global ? countries : []);

    var points = drawn.filter(function (r) { return r.lat !== null && value(r.name) > 0; }).map(function (r) {
      var xy = projection([r.lon, r.lat]);
      return xy ? { r: r, x: xy[0], y: xy[1], v: value(r.name) } : null;
    }).filter(Boolean);
    var max = d3.max(points, function (p) { return p.v; }) || 1;
    var rad = d3.scaleSqrt().domain([0, max]).range([0, Math.max(26, W / 22)]);     // area follows the (weighted) count
    points.sort(function (a, b) { return b.v - a.v; });                              // small bubbles drawn on top
    var labelled = new Set(points.filter(function (p) { return p.r.kind === "metro" || p.r.kind === "country"; }).slice(0, global ? 8 : 10).map(function (p) { return p.r.name; }));

    var g = svg.append("g").selectAll("g").data(points).join("g")
      .attr("class", function (p) { return "bubble" + (p.r.kind === "state" ? " state-kind" : "") + (p.r.kind === "country" ? " country-kind" : "") + (filters.regions.indexOf(p.r.name) >= 0 ? " on" : ""); })
      .attr("transform", function (p) { return "translate(" + p.x + "," + p.y + ")"; })
      .attr("tabindex", 0).attr("role", "button")
      .attr("aria-pressed", function (p) { return String(filters.regions.indexOf(p.r.name) >= 0); })
      .attr("aria-label", function (p) { return p.r.name + ": " + label(p.r.name); });
    g.append("circle").attr("r", function (p) { return Math.max(3, rad(p.v)); });
    g.filter(function (p) { return labelled.has(p.r.name); }).append("text").attr("text-anchor", "middle")
      .attr("y", function (p) { return Math.max(3, rad(p.v)) + 12; }).text(function (p) { return short(p.r.name); });
    g.filter(function (p) { return p.r.kind === "country"; }).attr("role", "img").attr("tabindex", null).attr("aria-pressed", null);
    g.on("click", function (e, p) { if (p.r.kind !== "country") toggle(p.r.name); })
     .on("keydown", function (e, p) { if (p.r.kind !== "country" && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); toggle(p.r.name); } })
     .on("mousemove", function (e, p) {
        var box = $("map").getBoundingClientRect();
        tip.hidden = false; tip.style.left = (e.clientX - box.left) + "px"; tip.style.top = (e.clientY - box.top) + "px";
        tip.textContent = ""; tip.appendChild(el("b", { text: p.r.name })); tip.appendChild(el("br"));
        tip.appendChild(document.createTextNode(label(p.r.name)));
      })
     .on("mouseleave", function () { tip.hidden = true; });

    // regions with no place on the map
    var off = $("offmap"); off.textContent = "";
    if (!global && outside > 0) {
      var go = el("button", { type: "button", class: "off" }, [el("span", { class: "dot", style: "width:14px;height:14px" }),
        el("span", {}, [el("b", { text: "Outside the US" }), el("small", { text: plural(outside, NOUN[mode][0], NOUN[mode][1]) + (sizeBy === "w" ? " (weighted)" : "") + " · show Global" })])]);
      go.addEventListener("click", function () { setArea("world"); });
      off.appendChild(go);
    }
    drawn.filter(function (r) { return r.lat === null && value(r.name) > 0 && (r.kind !== "country" || global); }).forEach(function (r) {
      var d = Math.max(10, Math.min(56, 2 * rad(value(r.name))));
      var b = el("button", { type: "button", class: "off" + (filters.regions.indexOf(r.name) >= 0 ? " on" : ""),
                             "aria-pressed": String(filters.regions.indexOf(r.name) >= 0) }, [
        el("span", { class: "dot", style: "width:" + d + "px;height:" + d + "px" }),
        el("span", {}, [el("b", { text: r.name }), el("small", { text: label(r.name) })])]);
      if (r.kind !== "country") b.addEventListener("click", function () { toggle(r.name); });
      off.appendChild(b);
    });
    var shown = d3.sum(Object.keys(counts), function (k) { return counts[k][1]; }), pd = placeData[mode] || {};
    $("mapTitle").textContent = { jobs: "Jobs", people: "People", companies: "Companies" }[mode] + " by region" + (global ? ", worldwide" : "");
    $("mapSub").textContent = mode === "jobs" ? "Click bubbles to pick regions. Your pick filters Find a job and Companies." + (global ? " Jobs on the board are US postings." : "")
      : "Click a US bubble to pick it as a region (it filters jobs and shows who's there). Country bubbles are for looking.";
    $("mapNote").textContent = mode === "jobs"
      ? "Bubble area: " + (sizeBy === "w" ? "jobs, with a posting that names several regions split evenly across them. "
                                          : "every listing, counted fully in each region it names. ") +
        "Grey dashed bubbles are “elsewhere in” a state, outside its big metros. " + plural(shown, "job", "jobs") + " under your filters."
      : (mode === "people"
          ? "Classmates who uploaded their data, at every place they've worked (from their LinkedIn jobs). "
          : "Companies in the directory, at their headquarters. ") +
        (sizeBy === "w" ? "Weighted: one in several places counts as a share in each. " : "All listings: counted fully in every place. ") +
        plural(pd.total || 0, NOUN[mode][0], NOUN[mode][1]) + ", " + fmtN(pd.unplaced || 0) + (mode === "people" ? " with no job locations listed." : " with no known headquarters.") + " Not filtered by Your search.";
  }
  function short(n) { return n.replace(/ area$/, "").replace("San Francisco Bay", "SF Bay").replace("New York City", "NYC").replace("Washington, DC", "DC"); }
  function label(name) {
    var c = counts[name] || [0, 0];
    return plural(c[0], NOUN[mode][0], NOUN[mode][1]) + (c[0] !== Math.round(c[1]) ? " (" + fmtN(c[1]) + " weighted)" : "");
  }

  // ---------- side panel ----------
  function drawSide() {
    var s = $("selection"); s.textContent = "";
    if (!filters.regions.length) {
      s.appendChild(el("p", { class: "muted", style: "margin:0", text: "Anywhere in the US. Click bubbles to pick regions; they show under Location in Your search." }));
    } else {
      s.appendChild(el("p", { class: "sel-total" }, [el("b", { text: plural(total, "job", "jobs") }), " in " + filters.regions.join(", ")]));
      s.appendChild(el("div", { class: "sel-actions" }, [
        el("a", { class: "btn primary", href: "/", text: "See these jobs in Find a job →" }),
        el("a", { class: "btn", href: "/companies", text: "See companies here →" })]));
    }

    var f = $("filterSummary"); f.textContent = "";
    var items = [];
    if ((filters.categories || []).length) items.push("Categories: " + filters.categories.join(", "));
    if ((filters.levels || []).length) items.push("Levels: " + filters.levels.join(", "));
    var fitOn = window.Global.state().buckets;
    if (profile) items.push("Fit: " + (fitOn.length ? fitOn.join(", ") : "none picked"));
    if (filters.from) items.push("Posted " + filters.from + " to " + filters.to);
    if (+filters.posted) items.push("Posted in the last " + filters.posted + " days");
    if ((filters.hidden || []).length) items.push(plural(filters.hidden.length, "company", "companies") + " hidden");
    if (filters.warm) items.push("Only companies with a cohort tie");
    if (filters.mba) items.push("Mentions an MBA");
    var visa = window.Global.state().visa;
    if (visa === "not_no") items.push("Hiding roles that won't sponsor a visa");
    if (visa === "likely") items.push("Only roles likely to sponsor a visa");
    f.appendChild(items.length ? el("ul", { class: "filter-list" }, items.map(function (t) { return el("li", { text: t }); }))
                               : el("p", { class: "muted", style: "margin:0", text: "None: every job is counted." }));
    f.appendChild(el("p", { style: "margin:8px 0 0" }, [el("a", { href: "/", text: "Change filters in Find a job" })]));

    var list = $("regionList"); list.textContent = "";
    var top = Object.keys(counts).sort(function (a, b) { return value(b) - value(a); }).slice(0, 15);
    var max = top.length ? value(top[0]) : 1;
    top.forEach(function (r) {
      var on = filters.regions.indexOf(r) >= 0;
      var b = el("button", { type: "button", "aria-pressed": String(on) }, [
        el("span", { text: r }), el("span", { class: "n", text: fmtN(value(r)) }),
        el("span", { class: "bar" }, [el("span", { style: "width:" + Math.round(100 * value(r) / max) + "%" })])]);
      if (REGIONS.some(function (x) { return x.name === r; })) b.addEventListener("click", function () { toggle(r); }); else b.disabled = true;
      list.appendChild(el("li", {}, [b]));
    });
  }

  // ---------- start ----------
  Array.prototype.forEach.call(document.querySelectorAll("#sizeSeg button"), function (b) {
    b.setAttribute("aria-pressed", String(b.getAttribute("data-size") === sizeBy));
    b.addEventListener("click", function () {
      sizeBy = b.getAttribute("data-size"); save("cohort.mapSize", sizeBy);
      Array.prototype.forEach.call(document.querySelectorAll("#sizeSeg button"), function (x) { x.setAttribute("aria-pressed", String(x === b)); });
      draw(); drawSide();
    });
  });
  function press(seg, attr, v) {
    Array.prototype.forEach.call(document.querySelectorAll(seg + " button"), function (x) { x.setAttribute("aria-pressed", String(x.getAttribute(attr) === v)); });
  }
  function setArea(a) {
    area = a; press("#areaSeg", "data-area", a);
    (a === "world" ? loadWorld() : Promise.resolve()).then(function () { draw(); drawSide(); })
      .catch(function (e) { $("mapSub").textContent = "Couldn't load the world map (" + e.message + ")."; });
  }
  Array.prototype.forEach.call(document.querySelectorAll("#areaSeg button"), function (b) {
    b.addEventListener("click", function () { setArea(b.getAttribute("data-area")); });
  });
  Array.prototype.forEach.call(document.querySelectorAll("#modeSeg button"), function (b) {
    b.addEventListener("click", function () { mode = b.getAttribute("data-mode"); press("#modeSeg", "data-mode", mode); loadMode(); });
  });
  var resizeTimer = null;
  window.addEventListener("resize", function () { clearTimeout(resizeTimer); resizeTimer = setTimeout(draw, 150); });

  Promise.all([fetch("/api/regions").then(function (r) { return r.json(); }), fetch(ATLAS).then(function (r) { return r.json(); })])
    .then(function (res) {
      REGIONS = res[0];
      states = topojson.feature(res[1], res[1].objects.states);
      return refresh();
    }).catch(function (e) { $("mapSub").textContent = "Couldn't load the map (" + e.message + "). Check your internet connection."; });
})();
