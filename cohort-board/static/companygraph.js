// Company map: who is who at one company, among the people your cohort knows.
//   CompanyGraph.render(container, company)  -> {highlight(name)}      company: the /api/company payload
// Columns are functions (from job titles, the same rules as Find a job), rows are seniority. Each person is a chip with
// coloured initials for every classmate who knows them; a filled chip means 2+ classmates do (the warmest paths).
// Click a classmate at the top to keep only the people they know; click a person for who knows them and since when.
// Without names (exports loaded before names were kept), it falls back to a short summary per classmate.
(function () {
  var COLORS = ["#0a66c2", "#b45309", "#15803d", "#7c3aed", "#be123c", "#0f766e", "#4d7c0f", "#c2410c"];
  var PER_CELL = 6;
  var SHORT = { "Strategy & Operations": "Strategy & Ops", "Sales & Business Development": "Sales & BD",
                "Operations & Supply Chain": "Ops & Supply Chain", "Technology & Engineering": "Tech & Engineering",
                "Marketing & Growth": "Marketing", "People & HR": "People & Recruiting" };

  function el(tag, attrs, kids) {
    var n = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      if (k === "class") n.className = attrs[k]; else if (k === "text") n.textContent = attrs[k]; else n.setAttribute(k, attrs[k]);
    });
    (kids || []).forEach(function (c) { if (c != null) n.appendChild(typeof c === "string" ? document.createTextNode(c) : c); });
    return n;
  }
  function trunc(t, n) { t = String(t || ""); return t.length > n ? t.slice(0, n - 1) + "…" : t; }
  function initials(name) {
    var w = String(name || "").trim().split(/\s+/);
    return ((w[0] || "?").charAt(0) + (w.length > 1 ? w[w.length - 1].charAt(0) : "")).toUpperCase();
  }

  function render(box, c) {
    box.textContent = "";
    var named = c.named || [];
    var me = c.me;
    // classmates: everyone tied to the company, strongest first (works there, worked there, knows the most)
    var known = {};
    named.forEach(function (x) { x.known_by.forEach(function (k) { known[k.name] = (known[k.name] || 0) + 1; }); });
    var mates = c.people.map(function (p) { return p.name; });
    Object.keys(known).forEach(function (n) { if (mates.indexOf(n) < 0) mates.push(n); });
    var byName = {}; c.people.forEach(function (p) { byName[p.name] = p; });
    mates.sort(function (a, b) {
      var pa = byName[a] || {}, pb = byName[b] || {};
      return (b === me) - (a === me) || !!(pb.worked && pb.worked.current) - !!(pa.worked && pa.worked.current) ||
             !!pb.worked - !!pa.worked || (known[b] || pb.count || 0) - (known[a] || pa.count || 0) || a.localeCompare(b);
    });
    var color = {}; mates.forEach(function (n, i) { color[n] = COLORS[i % COLORS.length]; });
    function tag(name) {
      return el("span", { class: "cm-ini", style: "background:" + color[name], title: name === me ? "You" : name, text: initials(name) });
    }

    var focus = null, selected = null;
    // ---- the cohort row: click a classmate to keep only the people they know ----
    var legend = el("div", { class: "cm-legend", role: "group", "aria-label": "Your cohort: click one to see who they know" });
    var legendBtns = {};
    mates.forEach(function (n) {
      var p = byName[n] || {};
      var sub = p.worked ? (p.worked.current ? "works here" : "worked here") : "";
      var count = known[n] != null ? known[n] : p.count || 0;
      var b = el("button", { type: "button", class: "cm-mate", "aria-pressed": "false",
                             title: (n === me ? "You" : n) + (p.worked && p.worked.title ? " · " + p.worked.title + (p.worked.years ? " (" + p.worked.years + ")" : "") : "") },
                 [tag(n), el("span", { class: "cm-mate-name", text: n === me ? "You" : n }),
                  el("span", { class: "cm-mate-sub", text: [sub, count ? count + " here" : ""].filter(Boolean).join(" · ") })]);
      b.addEventListener("click", function () { setFocus(focus === n ? null : n); });
      legendBtns[n] = b;
      legend.appendChild(b);
    });
    box.appendChild(legend);

    if (!named.length) {                                     // no names yet: a short summary per classmate
      var labels = c.bucket_labels || {};
      box.appendChild(el("ul", { class: "cm-summary" }, c.people.map(function (p) {
        var parts = Object.keys(p.buckets || {}).sort(function (a, b) { return p.buckets[b] - p.buckets[a]; })
          .map(function (k) { return p.buckets[k] + " " + (labels[k] || k); });
        return el("li", {}, [tag(p.name), el("b", { text: p.name === me ? "You" : p.name }),
          (p.worked ? " · " + (p.worked.current ? "works here" : "worked here") + (p.worked.title ? " as " + p.worked.title : "") : "") +
          (parts.length ? " · knows " + parts.join(", ") : "")]);
      })));
      box.appendChild(el("p", { class: "muted tiny", text: "Names and titles appear here once these classmates' exports are uploaded again." }));
      return { highlight: function () {} };
    }

    // ---- only people 2+ classmates know (off by default: everybody shows) ----
    var allNamed = named, onlyWarm = false, chips = [];
    var warmBox = el("input", { type: "checkbox" });
    var warmCount = allNamed.filter(function (x) { return x.known_by.length >= 2; }).length;
    warmBox.addEventListener("change", function () { onlyWarm = warmBox.checked; drawGrid(); });
    box.appendChild(el("label", { class: "chk cm-warm-only" }, [warmBox, " Only people 2+ classmates know (" + warmCount + ")"]));
    var gridHost = el("div");
    box.appendChild(gridHost);

    function drawGrid() {
      if (selected) { selected = null; card.hidden = true; }
      // ---- the grid: functions across, seniority down ----
      var tiers = c.tiers || ["Leadership", "Senior", "Mid", "Early career"];
      var named = onlyWarm ? allNamed.filter(function (x) { return x.known_by.length >= 2; }) : allNamed;
      chips = [];
      if (!named.length) { gridHost.textContent = ""; gridHost.appendChild(el("p", { class: "muted tiny", text: "Nobody here is known by 2 or more classmates yet." })); return; }
      var fcount = {};
      named.forEach(function (x) { fcount[x.function] = (fcount[x.function] || 0) + 1; });
      var fns = Object.keys(fcount).sort(function (a, b) {
        return (b === c.field) - (a === c.field) || (a === "Other") - (b === "Other") || fcount[b] - fcount[a];
      });
      if (fns.length > 5) {                                    // keep it to five columns; the smallest go under "Other"
        var keep = fns.filter(function (f) { return f !== "Other"; }).slice(0, 4);
        named.forEach(function (x) { x._col = keep.indexOf(x.function) >= 0 ? x.function : "Other"; });
        fns = keep.concat(["Other"]);
      } else {
        named.forEach(function (x) { x._col = x.function; });
      }
      var grid = el("div", { class: "cm-grid", style: "grid-template-columns: 104px repeat(" + fns.length + ", minmax(190px, 1fr))" });
      grid.appendChild(el("div", { class: "cm-corner" }));
      fns.forEach(function (f) {
        var n = named.filter(function (x) { return x._col === f; }).length;
        grid.appendChild(el("div", { class: "cm-colhead" + (f === c.field ? " field" : "") }, [f === "Other" ? "Other" : SHORT[f] || f, el("span", { class: "cm-n", text: " " + n })]));
      });
      tiers.forEach(function (t) {
        grid.appendChild(el("div", { class: "cm-rowhead", text: t }));
        fns.forEach(function (f) {
          var people = named.filter(function (x) { return x._col === f && x.tier === t; });
          var cell = el("div", { class: "cm-cell" + (people.length ? "" : " empty") });
          people.forEach(function (x, i) {
            var chip = el("button", { type: "button", class: "cm-chip" + (x.known_by.length > 1 ? " warm" : "") + (i >= PER_CELL ? " extra" : ""),
                                      title: x.name + (x.position ? " · " + x.position : "") },
              [el("span", { class: "cm-chip-name", text: x.name }),
               x.position ? el("span", { class: "cm-chip-pos", text: trunc(x.position, 34) }) : null,
               el("span", { class: "cm-chip-who" }, x.known_by.map(function (k) { return tag(k.name); }))]);
            chip._who = x.known_by.map(function (k) { return k.name; });
            chip.addEventListener("click", function () { select(x, chip); });
            chips.push(chip);
            cell.appendChild(chip);
          });
          if (people.length > PER_CELL) {
            var more = el("button", { type: "button", class: "cm-more", text: "+" + (people.length - PER_CELL) + " more" });
            more.addEventListener("click", function () { cell.classList.add("open"); more.remove(); });
            cell.appendChild(more);
          }
          grid.appendChild(cell);
        });
      });
      gridHost.textContent = "";
      gridHost.appendChild(el("div", { class: "cm-scroll" }, [grid]));
      if (focus) setFocus(focus);
    }

    // ---- the selected person ----
    var card = el("div", { class: "cm-card", hidden: "" });
    box.appendChild(card);
    drawGrid();
    function select(x, chip) {
      if (selected) selected.classList.remove("sel");
      if (selected === chip) { selected = null; card.hidden = true; return; }
      selected = chip; chip.classList.add("sel");
      card.textContent = "";
      var others = x.known_by.filter(function (k) { return k.name !== me; });
      card.appendChild(el("div", { class: "cm-card-h" }, [
        x.url ? el("a", { href: x.url, target: "_blank", rel: "noopener", text: x.name + " ↗" }) : el("b", { text: x.name }),
        el("span", { class: "muted", text: [x.position, (SHORT[x.function] || x.function) + " · " + x.tier].filter(Boolean).join(" · ") })]));
      card.appendChild(el("ul", { class: "cm-card-who" }, x.known_by.map(function (k) {
        return el("li", {}, [tag(k.name), " " + (k.name === me ? "You" : k.name) + (k.since ? ", connected since " + k.since : "")]);
      })));
      card.appendChild(el("p", { class: "cm-card-ask", text: others.length
        ? "Ask " + others.slice(0, 2).map(function (k) { return k.name; }).join(" or ") + " for an intro to " + x.name.split(" ")[0] + "."
        : "You know " + x.name.split(" ")[0] + " directly." }));
      card.hidden = false;
    }
    function setFocus(n) {
      focus = n;
      Object.keys(legendBtns).forEach(function (k) { legendBtns[k].setAttribute("aria-pressed", String(k === n)); });
      box.classList.toggle("cm-focus", !!n);
      chips.forEach(function (ch) { ch.classList.toggle("lit", !!n && ch._who.indexOf(n) >= 0); });
      if (n) Array.prototype.forEach.call(box.querySelectorAll(".cm-cell"), function (cell) {
        if (cell.querySelector(".cm-chip.extra.lit")) { cell.classList.add("open"); var m = cell.querySelector(".cm-more"); if (m) m.remove(); }
      });
    }
    return { highlight: function (n) { setFocus(n && legendBtns[n] ? n : null); } };
  }
  window.CompanyGraph = { render: render };
})();
