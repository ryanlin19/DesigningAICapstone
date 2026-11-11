// Map tab: jobs per region as bubbles on a US map, under the same filters as Find a job.
// Clicking a bubble adds or removes that region; the pick is saved with Find a job's filters, so it filters
// Find a job and the Companies page too.
(function () {
  var ATLAS = "https://cdn.jsdelivr.net/npm/us-atlas@3.0.1/states-10m.json";
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

  // ---------- data ----------
  function refresh() {
    var g = window.Global.state();
    var body = { profile: profile, limit: 0,
                 filters: Object.assign({}, filters, { buckets: profile ? g.buckets : [], visa: g.visa, regions: g.regions }) };
    return fetch("/api/find", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })
      .then(function (r) { return r.ok ? r.json() : r.text().then(function (t) { throw new Error(t || r.status); }); })
      .then(function (res) {
        counts = res.counts.regions || {}; total = res.total;
        window.Global.setFitCounts(profile ? res.counts.buckets : null);
        draw(); drawSide();
      }).catch(function (e) { $("mapSub").textContent = e.message; });
  }

  // ---------- map ----------
  var tip = $("tip");
  function draw() {
    if (!states) return;
    var svg = d3.select("#map"), W = $("map").parentNode.clientWidth, H = Math.round(W * 0.6);
    svg.attr("viewBox", "0 0 " + W + " " + H).attr("width", W).attr("height", H).selectAll("*").remove();
    var projection = d3.geoAlbersUsa().fitSize([W, H], states), path = d3.geoPath(projection);
    svg.append("g").selectAll("path").data(states.features).join("path").attr("class", "state").attr("d", path);

    var points = REGIONS.filter(function (r) { return r.lat !== null && value(r.name) > 0; }).map(function (r) {
      var xy = projection([r.lon, r.lat]);
      return xy ? { r: r, x: xy[0], y: xy[1], v: value(r.name) } : null;
    }).filter(Boolean);
    var max = d3.max(points, function (p) { return p.v; }) || 1;
    var rad = d3.scaleSqrt().domain([0, max]).range([0, Math.max(26, W / 22)]);     // area follows the (weighted) count
    points.sort(function (a, b) { return b.v - a.v; });                              // small bubbles drawn on top
    var labelled = new Set(points.filter(function (p) { return p.r.kind === "metro"; }).slice(0, 10).map(function (p) { return p.r.name; }));

    var g = svg.append("g").selectAll("g").data(points).join("g")
      .attr("class", function (p) { return "bubble" + (p.r.kind === "state" ? " state-kind" : "") + (filters.regions.indexOf(p.r.name) >= 0 ? " on" : ""); })
      .attr("transform", function (p) { return "translate(" + p.x + "," + p.y + ")"; })
      .attr("tabindex", 0).attr("role", "button")
      .attr("aria-pressed", function (p) { return String(filters.regions.indexOf(p.r.name) >= 0); })
      .attr("aria-label", function (p) { return p.r.name + ": " + label(p.r.name); });
    g.append("circle").attr("r", function (p) { return Math.max(3, rad(p.v)); });
    g.filter(function (p) { return labelled.has(p.r.name); }).append("text").attr("text-anchor", "middle")
      .attr("y", function (p) { return Math.max(3, rad(p.v)) + 12; }).text(function (p) { return short(p.r.name); });
    g.on("click", function (e, p) { toggle(p.r.name); })
     .on("keydown", function (e, p) { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(p.r.name); } })
     .on("mousemove", function (e, p) {
        var box = $("map").getBoundingClientRect();
        tip.hidden = false; tip.style.left = (e.clientX - box.left) + "px"; tip.style.top = (e.clientY - box.top) + "px";
        tip.textContent = ""; tip.appendChild(el("b", { text: p.r.name })); tip.appendChild(el("br"));
        tip.appendChild(document.createTextNode(label(p.r.name)));
      })
     .on("mouseleave", function () { tip.hidden = true; });

    // regions with no place on the map
    var off = $("offmap"); off.textContent = "";
    REGIONS.filter(function (r) { return r.lat === null && value(r.name) > 0; }).forEach(function (r) {
      var d = Math.max(10, Math.min(56, 2 * rad(value(r.name))));
      var b = el("button", { type: "button", class: "off" + (filters.regions.indexOf(r.name) >= 0 ? " on" : ""),
                             "aria-pressed": String(filters.regions.indexOf(r.name) >= 0) }, [
        el("span", { class: "dot", style: "width:" + d + "px;height:" + d + "px" }),
        el("span", {}, [el("b", { text: r.name }), el("small", { text: label(r.name) })])]);
      b.addEventListener("click", function () { toggle(r.name); });
      off.appendChild(b);
    });
    var shown = d3.sum(Object.keys(counts), function (k) { return counts[k][1]; });
    $("mapNote").textContent = "Bubble area: " + (sizeBy === "w"
      ? "jobs, with a posting that names several regions split evenly across them. "
      : "every listing, counted fully in each region it names. ") +
      "Grey dashed bubbles are “elsewhere in” a state, outside its big metros. " + plural(shown, "job", "jobs") + " under your filters.";
  }
  function short(n) { return n.replace(/ area$/, "").replace("San Francisco Bay", "SF Bay").replace("New York City", "NYC").replace("Washington, DC", "DC"); }
  function label(name) {
    var c = counts[name] || [0, 0];
    return plural(c[0], "job", "jobs") + (c[0] !== Math.round(c[1]) ? " (" + fmtN(c[1]) + " weighted)" : "");
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
      b.addEventListener("click", function () { toggle(r); });
      list.appendChild(el("li", {}, [b]));
    });
  }

  // ---------- start ----------
  Array.prototype.forEach.call(document.querySelectorAll(".seg button"), function (b) {
    b.setAttribute("aria-pressed", String(b.getAttribute("data-size") === sizeBy));
    b.addEventListener("click", function () {
      sizeBy = b.getAttribute("data-size"); save("cohort.mapSize", sizeBy);
      Array.prototype.forEach.call(document.querySelectorAll(".seg button"), function (x) { x.setAttribute("aria-pressed", String(x === b)); });
      draw(); drawSide();
    });
  });
  document.querySelector(".cb-logout").addEventListener("click", function () {
    fetch("/logout", { method: "POST" }).then(function () { location.href = "/login"; });
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
