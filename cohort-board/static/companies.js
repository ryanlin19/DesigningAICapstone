// Companies: the company directory (data/companies.db), organized by vertical.
// Ranked by classmates who work or worked there, then by number of connections, then by open roles.
// Each company links to its open roles on Find a job. The Location pick in "Your search" keeps companies with
// their HQ or an office in a picked region.
(function () {
  var PAGE = 50;
  var KEY = "cohort.companiesFilters";
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

  var DEFAULTS = { vertical: "", show: "all" };
  var filters = Object.assign({}, DEFAULTS, load(KEY, {}));
  var query = new URLSearchParams(location.search).get("q") || "";      // from a "company page" link on Find a job
  var all = [], verticals = [], limit = PAGE;

  function regions() { return window.Global ? (window.Global.state().regions || []) : []; }
  function hasTies(c) { return c.people.length > 0 || c.contacts > 0; }
  function haystack(c) {
    if (!c._hay) c._hay = [c.name, c.desc, c.sub, c.vertical, c.hq, (c.offices || []).join(" "), c.jobs ? c.jobs.label : ""]
      .join(" ").toLowerCase();
    return c._hay;
  }
  function matches(c, skipVertical) {
    if (!skipVertical && filters.vertical && c.vertical !== filters.vertical) return false;
    if (filters.show === "ties" && !hasTies(c)) return false;
    if (filters.show === "jobs" && !c.jobs) return false;
    var picked = regions();
    if (picked.length && !c.regions.some(function (r) { return picked.indexOf(r) >= 0; })) return false;
    var q = query.trim().toLowerCase();
    if (q && haystack(c).indexOf(q) < 0) return false;
    return true;
  }

  // ---------- controls ----------
  function drawSeg() {
    Array.prototype.forEach.call(document.querySelectorAll(".seg button"), function (b) {
      b.setAttribute("aria-pressed", String(b.getAttribute("data-show") === filters.show));
    });
  }
  function drawVerticals() {
    var counts = {}, total = 0;
    all.forEach(function (c) { if (matches(c, true)) { counts[c.vertical] = (counts[c.vertical] || 0) + 1; total++; } });
    var box = $("verticals"); box.textContent = "";
    function chip(v, label, n) {
      var b = el("button", { type: "button", class: "chip", "aria-pressed": String(filters.vertical === v) },
                 [label, el("span", { class: "n", text: fmtN(n) })]);
      b.addEventListener("click", function () { filters.vertical = v; limit = PAGE; persist(); render(); });
      box.appendChild(b);
    }
    chip("", "All verticals", total);
    verticals.filter(function (v) { return counts[v]; })
      .sort(function (a, b) { return (a === "Other") - (b === "Other") || counts[b] - counts[a]; })
      .forEach(function (v) { chip(v, v, counts[v]); });
  }
  function drawRegionBar() {
    var picked = regions(), bar = $("regionBar");
    bar.textContent = ""; bar.hidden = !picked.length;
    if (!picked.length) return;
    bar.appendChild(el("span", { class: "hidden-label", text: "HQ or office in:" }));
    bar.appendChild(el("span", { text: picked.join(" · ") }));
    bar.appendChild(el("span", { class: "muted tiny", text: "(change it under Location in Your search)" }));
  }
  function persist() { save(KEY, filters); }

  // ---------- cohort ties: the same drill-down as the job cards on Find a job ----------
  var FIELD = { engineering: "engineering", data_ml: "data / ML", product: "product", design: "design", recruiting: "recruiting",
    sales_gtm: "sales / GTM", marketing: "marketing", finance: "finance", consulting: "consulting", research: "research",
    operations: "operations", legal: "legal", healthcare: "healthcare", education: "education", student_intern: "students / interns",
    leadership: "leadership" };
  function tieSummary(c) {
    var parts = [], alumni = c.people.filter(function (p) { return p.worked; });
    var now = alumni.filter(function (p) { return p.worked.current; });
    if (alumni.length) parts.push("💼 " + (alumni.length === 1 ? alumni[0].name + (now.length ? " works here" : " worked here")
                                          : alumni.length + " classmates " + (now.length === alumni.length ? "work" : "worked") + " here"));
    var knowers = c.people.filter(function (p) { return p.count || p.added.length; }).length;
    if (knowers) parts.push("👥 " + plural(knowers, "classmate", "classmates") + " · " + plural(c.contacts, "contact", "contacts"));
    return parts.join("  ");
  }
  function tieButton(c, getCard) {
    var alumni = c.people.some(function (p) { return p.worked; });
    var b = el("button", { type: "button", class: "tag tie" + (alumni ? " alumni" : ""), "aria-expanded": "false",
      title: "Who in your cohort is tied to " + c.name }, [tieSummary(c), el("span", { class: "caret", "aria-hidden": "true", text: "▾" })]);
    var panel = null;
    b.addEventListener("click", function () {
      var open = b.getAttribute("aria-expanded") !== "true";
      b.setAttribute("aria-expanded", String(open));
      if (!panel) { panel = tiePanel(c); getCard().insertBefore(panel, getCard().querySelector(".co-foot")); }
      panel.hidden = !open;
    });
    return b;
  }
  function tiePanel(c) {
    var rows = c.people.map(function (p) {
      var bits = [];
      if (p.worked) {
        bits.push(el("span", { class: "tag alumni", text: (p.worked.current ? "Works here now" : "Worked here") +
          (p.worked.title ? ": " + p.worked.title : "") + (p.worked.years ? ", " + p.worked.years : "") }));
      }
      if (p.count) {
        bits.push(el("span", { class: "tie-line", text: "Knows " + plural(p.count, "person", "people") + " here" +
          (p.bucket && FIELD[p.bucket] ? ", mostly " + FIELD[p.bucket] : "") }));
      }
      (p.added || []).forEach(function (a) {
        var who = [a.contact, a.title].filter(Boolean).join(", ");
        bits.push(el("span", { class: "tie-line", text: "Knows " + (who || "someone") + (a.note ? " (“" + a.note + "”)" : "") }));
      });
      return el("li", {}, [el("b", { text: p.name })].concat(bits));
    });
    var foot = [el("a", { href: "/companies?view=connect", text: "Connect with these classmates on LinkedIn" })];
    if (c.shared) foot.unshift(el("span", { class: "muted", text: plural(c.shared, "person here is", "people here are") + " known by 2+ classmates" }));
    return el("div", { class: "tie-panel" }, [
      el("div", { class: "tie-h", text: "Your cohort at " + c.name }),
      el("ol", { class: "tie-list" }, rows),
      el("div", { class: "tie-foot" }, foot)]);
  }

  // ---------- cards ----------
  function officesLine(c) {
    var parts = [el("b", { text: "HQ " }), c.hq || "unknown"];
    var offs = c.offices || [];
    if (offs.length) {
      var shown = offs.slice(0, 6);
      var span = el("span", { text: shown.join(" · ") });
      parts.push(" · ", el("b", { text: "Offices " }), span);
      if (offs.length > 6) {
        var more = el("button", { type: "button", class: "co-more", text: " +" + (offs.length - 6) + " more" });
        more.addEventListener("click", function () { span.textContent = offs.join(" · "); more.remove(); });
        parts.push(more);
      }
    }
    return el("div", { class: "co-meta" }, parts);
  }
  function card(c) {
    var article = null;
    var tags = [el("span", { class: "tag vert", text: c.vertical + (c.sub && c.sub !== c.vertical ? " · " + c.sub : "") })];
    if (c.people.length) tags.push(tieButton(c, function () { return article; }));
    if (c.sp500) tags.push(el("span", { class: "tag", text: "S&P 500" }));

    var head = [el("h2", { class: "co-name", text: c.name })];
    if (c.website) head.push(el("a", { class: "co-site", href: c.website, target: "_blank", rel: "noopener",
                                       text: c.website.replace(/^https?:\/\/(www\.)?/, "").replace(/\/$/, "") + " ↗" }));
    var foot = [c.jobs
      ? el("a", { class: "co-jobs", href: "/?company=" + encodeURIComponent(c.jobs.label),
                  text: plural(c.jobs.n, "open role", "open roles") + " on Find a job →" })
      : el("span", { class: "co-nojobs", text: "No open roles in the job feeds we read" })];
    if (!c.researched || c.confidence === "low")
      foot.push(el("span", { class: "co-flag", text: c.researched ? "Low-confidence match" : "Not yet researched: details are automatic" }));

    article = el("article", { class: "co-card" }, [
      el("div", { class: "co-head" }, head),
      el("div", { class: "tags" }, tags),
      c.desc ? el("p", { class: "co-desc", text: c.desc.length > 360 ? c.desc.slice(0, 360).replace(/\s+\S*$/, "") + "…" : c.desc }) : null,
      officesLine(c),
      el("div", { class: "co-foot" }, foot)]);
    return article;
  }

  // ---------- page ----------
  function render() {
    drawSeg(); drawVerticals(); drawRegionBar();
    var list = all.filter(function (c) { return matches(c); });
    $("count").textContent = plural(list.length, "company", "companies");
    var box = $("list"); box.textContent = "";
    if (!list.length) box.appendChild(el("p", { class: "muted", text: "No companies match. Try another vertical, clear the search, or change Location." }));
    list.slice(0, limit).forEach(function (c) { box.appendChild(card(c)); });
    var more = $("more");
    more.hidden = list.length <= limit;
    more.textContent = "Show more (" + fmtN(list.length - limit) + " left)";
  }

  function bind() {
    Array.prototype.forEach.call(document.querySelectorAll(".seg button"), function (b) {
      b.addEventListener("click", function () { filters.show = b.getAttribute("data-show"); limit = PAGE; persist(); render(); });
    });
    var q = $("q"); q.value = query;
    var t = null;
    q.addEventListener("input", function () {
      clearTimeout(t);
      t = setTimeout(function () { query = q.value; limit = PAGE; render(); }, 120);
    });
    $("more").addEventListener("click", function () { limit += PAGE; render(); });
    if (window.Global) {
      window.Global.onChange(function () { limit = PAGE; render(); });
      window.Global.onRevert(function () { filters = Object.assign({}, DEFAULTS); query = ""; q.value = ""; persist(); limit = PAGE; render(); });
    }
  }

  fetch("/api/companies", { credentials: "same-origin" })
    .then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
    .then(function (d) {
      var banner = $("banner");
      if (!d.ready) {
        banner.hidden = false;
        banner.textContent = "The company database isn't built yet (python3 company-db/companies.py merge).";
        return;
      }
      if (d.warning) { banner.hidden = false; banner.textContent = d.warning; }
      all = d.companies; verticals = d.verticals || [];
      if (filters.vertical && verticals.indexOf(filters.vertical) < 0) filters.vertical = "";
      bind(); render();
    })
    .catch(function (e) {
      var banner = $("banner"); banner.hidden = false;
      banner.textContent = "Couldn't load companies (" + e.message + ").";
    });
})();
