// Companies: the company directory (data/companies.db), organized by vertical.
// Ranked "For you" when you have a resume (or filled it in) or targets in Your search: open roles that fit you and match
// what you want, scored like Find a job (find.company_scores). Otherwise, or with "Cohort ties", by classmates who work or
// worked there, then by number of connections, then by open roles.
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

  var DEFAULTS = { vertical: "", show: "all", rank: "you" };
  var filters = Object.assign({}, DEFAULTS, load(KEY, {}));
  var query = new URLSearchParams(location.search).get("q") || "";      // from a "company page" link on Find a job
  var all = [], verticals = [], limit = PAGE;
  var ranks = null, rankSeq = 0;                          // {company id: {score, n, fit, why}} for "For you"

  // ---------- "For you": ranked by your resume or hand-filled profile, what you want, and Your search ----------
  function canRank() {
    var g = window.Global;
    if (!g) return false;
    var w = g.want() || {};
    return !!g.profile() || ["categories", "levels", "verticals", "companies"].some(function (k) { return (w[k] || []).length; });
  }
  function rankingOn() { return filters.rank === "you" && canRank() && !!ranks; }
  function fetchRanks() {
    if (!canRank()) { ranks = null; render(); return; }
    var g = window.Global, st = g.state(), seq = ++rankSeq, p = g.profile();
    fetch("/api/companies/rank", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ profile: p, want: g.want(), filters: { visa: st.visa, regions: st.regions, buckets: p ? st.buckets : [] } }) })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) { if (seq === rankSeq && d) { ranks = d.ranks || {}; render(); } })
      .catch(function () { /* stays on the cohort-ties order */ });
  }
  function ranked(list) {
    if (!rankingOn()) return list;
    var pos = new Map(list.map(function (c, i) { return [c, i]; }));
    return list.slice().sort(function (a, b) {
      var x = ranks[a.id], y = ranks[b.id];
      return ((y ? y.score : -1) - (x ? x.score : -1)) || pos.get(a) - pos.get(b);
    });
  }
  function forYouLine(c) {
    var r = rankingOn() && ranks[c.id];
    if (!r) return null;
    var hasProfile = !!window.Global.profile();
    var bits = [hasProfile ? plural(r.fit, "role fits you", "roles fit you") + (r.ready ? " (" + fmtN(r.ready) + " Ready)" : "")
                           : plural(r.n, "matching role", "matching roles")];
    return el("p", { class: "co-foryou" }, [el("b", { text: "For you: " }), bits.concat(r.why || []).join(" · ")]);
  }

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
    Array.prototype.forEach.call(document.querySelectorAll(".seg button[data-show]"), function (b) {
      b.setAttribute("aria-pressed", String(b.getAttribute("data-show") === filters.show));
    });
    var can = canRank();
    Array.prototype.forEach.call(document.querySelectorAll("#rankSeg button"), function (b) {
      var mode = b.getAttribute("data-rank");
      b.setAttribute("aria-pressed", String(mode === (can ? filters.rank : "ties")));
      b.disabled = mode === "you" && !can;
      if (mode === "you") b.title = can ? "Open roles that fit you and match what you want, plus Your search's filters"
                                        : "Upload a resume, fill it in yourself, or set targets in Your search to rank for you";
    });
    $("dirSub").textContent = rankingOn()
      ? "Ranked for you: open roles that fit you and match what you want, under Your search's filters."
      : "Classmates who work or worked there come first, then most connections.";
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
    var foot = [el("a", { href: "/cohort", text: "Your cohort: who to connect with" })];
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

    var head = [el("h2", { class: "co-name" }, [el("a", { href: "/companies?id=" + encodeURIComponent(c.id), text: c.name })])];
    if (c.website) head.push(el("a", { class: "co-site", href: c.website, target: "_blank", rel: "noopener",
                                       text: c.website.replace(/^https?:\/\/(www\.)?/, "").replace(/\/$/, "") + " ↗" }));
    var foot = [c.jobs
      ? el("a", { class: "co-jobs", href: "/?company=" + encodeURIComponent(c.jobs.label),
                  text: plural(c.jobs.n, "open role", "open roles") + " on Find a job →" })
      : el("span", { class: "co-nojobs", text: "No open roles in the job feeds we read" })];
    if (c.people.length) foot.push(el("a", { class: "co-graph", href: "/companies?id=" + encodeURIComponent(c.id) + "#graph", text: "Relationship graph →" }));
    if (!c.researched || c.confidence === "low")
      foot.push(el("span", { class: "co-flag", text: c.researched ? "Low-confidence match" : "Not yet researched: details are automatic" }));

    article = el("article", { class: "co-card" }, [
      el("div", { class: "co-head" }, head),
      el("div", { class: "tags" }, tags),
      forYouLine(c),
      c.desc ? el("p", { class: "co-desc", text: c.desc.length > 360 ? c.desc.slice(0, 360).replace(/\s+\S*$/, "") + "…" : c.desc }) : null,
      officesLine(c),
      el("div", { class: "co-foot" }, foot)]);
    return article;
  }

  // ---------- page ----------
  function render() {
    drawSeg(); drawVerticals(); drawRegionBar();
    var list = ranked(all.filter(function (c) { return matches(c); }));
    $("count").textContent = plural(list.length, "company", "companies");
    var box = $("list"); box.textContent = "";
    if (!list.length) box.appendChild(el("p", { class: "muted", text: "No companies match. Try another vertical, clear the search, or change Location." }));
    list.slice(0, limit).forEach(function (c) { box.appendChild(card(c)); });
    var more = $("more");
    more.hidden = list.length <= limit;
    more.textContent = "Show more (" + fmtN(list.length - limit) + " left)";
  }

  function bind() {
    Array.prototype.forEach.call(document.querySelectorAll(".seg button[data-show]"), function (b) {
      b.addEventListener("click", function () { filters.show = b.getAttribute("data-show"); limit = PAGE; persist(); render(); });
    });
    Array.prototype.forEach.call(document.querySelectorAll("#rankSeg button"), function (b) {
      b.addEventListener("click", function () { filters.rank = b.getAttribute("data-rank"); limit = PAGE; persist(); render(); });
    });
    var q = $("q"); q.value = query;
    var t = null;
    q.addEventListener("input", function () {
      clearTimeout(t);
      t = setTimeout(function () { query = q.value; limit = PAGE; render(); }, 120);
    });
    $("more").addEventListener("click", function () { limit += PAGE; render(); });
    if (window.Global) {
      window.Global.onChange(function () { limit = PAGE; render(); fetchRanks(); });
      window.Global.onRevert(function () { filters = Object.assign({}, DEFAULTS); query = ""; q.value = ""; persist(); limit = PAGE; render(); fetchRanks(); });
    }
  }

  // ---------- one company: its page, with the relationship graph and the best ways in ----------
  function showDetail(params) {
    $("dirList").hidden = true;
    var box = $("detail"); box.hidden = false;
    box.appendChild(el("p", { class: "muted", text: "Loading…" }));
    var q = new URLSearchParams();
    ["id", "company", "field"].forEach(function (k) { if (params.get(k)) q.set(k, params.get(k)); });
    fetch("/api/company?" + q.toString(), { credentials: "same-origin" })
      .then(function (r) { return r.json().then(function (d) { if (!r.ok) throw new Error(d.error || "HTTP " + r.status); return d; }); })
      .then(function (c) { drawDetail(box, c); })
      .catch(function (e) {
        box.textContent = "";
        box.appendChild(el("a", { class: "back", href: "/companies", text: "← All companies" }));
        box.appendChild(el("p", { class: "banner", text: e.message + (params.get("company") ? " (" + params.get("company") + ")" : "") }));
      });
  }
  function drawDetail(box, c) {
    box.textContent = "";
    document.title = c.name + " · Companies";
    var tags = [el("span", { class: "tag vert", text: c.vertical + (c.sub && c.sub !== c.vertical ? " · " + c.sub : "") })];
    if (c.sp500) tags.push(el("span", { class: "tag", text: "S&P 500" }));
    if (c.ownership) tags.push(el("span", { class: "tag", text: c.ownership.charAt(0).toUpperCase() + c.ownership.slice(1) }));
    if (c.employees) tags.push(el("span", { class: "tag", text: "~" + fmtN(c.employees) + " employees" }));
    var head = [el("h1", { class: "co-title", text: c.name })];
    if (c.website) head.push(el("a", { class: "co-site", href: c.website, target: "_blank", rel: "noopener",
                                       text: c.website.replace(/^https?:\/\/(www\.)?/, "").replace(/\/$/, "") + " ↗" }));
    box.appendChild(el("a", { class: "back", href: "/companies", text: "← All companies" }));
    box.appendChild(el("article", { class: "co-card" }, [
      el("div", { class: "co-head" }, head), el("div", { class: "tags" }, tags),
      c.desc ? el("p", { class: "co-desc", text: c.desc }) : null,
      officesLine(c),
      el("div", { class: "co-foot" }, [c.jobs
        ? el("a", { class: "co-jobs", href: "/?company=" + encodeURIComponent(c.jobs.label), text: plural(c.jobs.n, "open role", "open roles") + " on Find a job →" })
        : el("span", { class: "co-nojobs", text: "No open roles in the job feeds we read" })])]));

    // who is who: the company map
    var g = el("section", { class: "co-card rg", id: "graph" }, [
      el("div", { class: "rg-head" }, [el("h2", { text: "Who's who at " + c.name }),
        c.named && c.named.length ? el("span", { class: "muted tiny", text: "People your cohort knows, by function and seniority" }) : null])]);
    if (!c.people.length) {
      g.appendChild(el("p", { class: "muted", text: "No one in your cohort is tied to " + c.name + " yet. Ties appear when classmates add their LinkedIn exports." }));
      g.appendChild(el("a", { href: "/companies?view=upload", text: "Add classmates' exports →" }));
    } else {
      var holder = el("div", { class: "cm" });
      g.appendChild(holder);
      if (c.named && c.named.length) g.appendChild(el("p", { class: "muted tiny", text: "Coloured initials show which classmates know each person; " +
        "purple-edged chips are known by two or more. Click a classmate above to see only the people they know, or a person for details." }));
      box.appendChild(g);
      var peopleList = c.named && c.named.length ? namedSection(c) : null;
      var graph = window.CompanyGraph.render(holder, c);
    }
    if (!c.people.length) box.appendChild(g);

    // best ways in
    if (c.ways && c.ways.length) {
      var list = el("ol", { class: "ways" }, c.ways.map(function (w, i) {
        var li = el("li", { class: "way" + (i === 0 ? " top" : "") }, [
          el("div", { class: "way-h" }, [w.url ? el("b", {}, [el("a", { href: w.url, target: "_blank", rel: "noopener", text: w.name })])
                                                 : el("b", { text: w.kind === "classmate" ? "Ask " + w.name : w.name }),
                                         i === 0 ? el("span", { class: "tag works", text: "Strongest" }) : null]),
          el("div", { class: "way-why", text: w.why.join(" · ") })]);
        if (w.kind === "classmate" && graph) {
          li.addEventListener("mouseenter", function () { graph.highlight(w.name); });
          li.addEventListener("mouseleave", function () { graph.highlight(null); });
        }
        return li;
      }));
      var you = c.people.filter(function (p) { return p.name === c.me; })[0];
      var youLine = you && (you.count || you.worked) ? el("div", { class: "way-you", text: "You: " + [you.worked ? (you.worked.current ? "you work here" : "you worked here") : null,
        you.count ? "you know " + plural(you.count, "person", "people") + " here yourself" : null].filter(Boolean).join(" · ") + "." }) : null;
      box.appendChild(el("section", { class: "co-card" }, [
        el("h2", { text: "Best ways in" + (c.field ? " for a " + c.field + " role" : "") }),
        youLine,
        el("p", { class: "muted tiny", text: "Strongest first: a classmate who works there now, then one who worked there, then who knows the most people, " +
          "especially in the role's field, recruiting or leadership, and contacts several classmates share." }),
        list,
        el("div", { class: "tie-foot" }, [el("a", { href: "/cohort", text: "Your cohort: who to connect with" })])]));
    } else if (c.people.length) {
      box.appendChild(el("section", { class: "co-card" }, [el("h2", { text: "Best ways in" }),
        el("p", { class: "muted", text: "Only you are tied to " + c.name + " so far." })]));
    }
    if (c.shared && c.shared.length) box.appendChild(sharedSection(c));
    if (peopleList) box.appendChild(peopleList.node);
    else if (c.people.length) box.appendChild(el("p", { class: "muted tiny", text: "Names appear once classmates' exports are uploaded again (uploads before this change kept only counts)." }));
    if (location.hash === "#graph") { var t = document.getElementById("graph"); if (t) t.scrollIntoView({ block: "start" }); }
  }

  // The most meaningful shared connections (people 2+ classmates know): the top few, with "See all".
  function sharedSection(c) {
    var labels = c.bucket_labels || {}, TOP = 5, PAGE_N = 30, all = false, shownN = PAGE_N;
    var list = el("ol", { class: "sh-list" });
    var toggle = el("button", { type: "button", class: "btn sh-all" });
    var more = el("button", { type: "button", class: "btn more", text: "Show more" });
    function row(x, i) {
      var who = x.known_by
        ? x.known_by.map(function (k) { return (k.name === c.me ? "you" : k.name) + (k.since ? " (" + k.since + ")" : ""); }).join(", ")
        : (x.connectors || []).join(", ") + (x.since ? " · since " + x.since : "");
      var role = labels[x.bucket] || "someone";
      var name = x.name
        ? (x.url ? el("a", { class: "np-name", href: x.url, target: "_blank", rel: "noopener", text: x.name + " ↗" }) : el("span", { class: "np-name", text: x.name }))
        : el("span", { class: "np-name", text: "A " + role + " contact" });
      return el("li", { class: "sh" + (i === 0 ? " top" : "") }, [
        el("div", { class: "np-top" }, [el("span", { class: "sh-rank", text: String(i + 1) }), name]),
        x.position ? el("div", { class: "np-pos", text: x.position }) : null,
        el("div", { class: "sh-why" }, x.why.map(function (w) { return el("span", { class: "tag" + (/^Known by \d/.test(w) ? " shared" : /who work/.test(w) ? " works" : "") , text: w }); })),
        el("div", { class: "np-who", text: "Known by " + who })]);
    }
    function draw() {
      var rows = all ? c.shared.slice(0, shownN) : c.shared.slice(0, TOP);
      list.textContent = "";
      rows.forEach(function (x, i) { list.appendChild(row(x, i)); });
      toggle.hidden = c.shared.length <= TOP;
      toggle.textContent = all ? "Show the top " + TOP : "See all " + fmtN(c.shared.length) + " shared connections";
      more.hidden = !all || c.shared.length <= shownN;
      more.textContent = "Show more (" + fmtN(c.shared.length - shownN) + " left)";
    }
    toggle.addEventListener("click", function () { all = !all; shownN = PAGE_N; draw(); if (!all) node.scrollIntoView({ block: "start" }); });
    more.addEventListener("click", function () { shownN += PAGE_N; draw(); });
    var node = el("section", { class: "co-card", id: "shared" }, [
      el("h2", { text: "Most meaningful shared connections (" + fmtN(c.shared.length) + ")" }),
      el("p", { class: "muted tiny", text: "People two or more classmates know. Ranked by how many classmates know them, whether a classmate " +
        "who worked here knows them, seniority, recruiting" + (c.field ? ", the " + c.field + " field" : "") + ", and how long the connection goes back." }),
      list, more, toggle]);
    draw();
    return node;
  }

  // People your cohort knows at the company, by name: search, filter by role, and who knows each person.
  function namedSection(c) {
    var labels = c.bucket_labels || {}, PAGE_N = 30, shownN = PAGE_N, bucket = "", text = "";
    var counts = {};
    c.named.forEach(function (x) { counts[x.bucket] = (counts[x.bucket] || 0) + 1; });
    var input = el("input", { type: "search", class: "np-search", placeholder: "Search names and titles…", "aria-label": "Search people" });
    var chips = el("div", { class: "chips np-chips" });
    var list = el("ol", { class: "np-list" }), more = el("button", { type: "button", class: "btn more", text: "Show more" });
    function cap(t) { t = labels[t] || t; return t.charAt(0).toUpperCase() + t.slice(1); }
    function drawChips() {
      chips.textContent = "";
      [""].concat(Object.keys(counts).sort(function (a, b) { return counts[b] - counts[a]; })).forEach(function (b) {
        var ch = el("button", { type: "button", class: "chip", "aria-pressed": String(bucket === b) },
                    [b ? cap(b) : "Everyone", el("span", { class: "n", text: " " + fmtN(b ? counts[b] : c.named.length) })]);
        ch.addEventListener("click", function () { bucket = b; shownN = PAGE_N; draw(); });
        chips.appendChild(ch);
      });
    }
    function draw() {
      drawChips();
      var q = text.toLowerCase();
      var rows = c.named.filter(function (x) {
        return (!bucket || x.bucket === bucket) && (!q || (x.name + " " + (x.position || "")).toLowerCase().indexOf(q) >= 0);
      });
      list.textContent = "";
      rows.slice(0, shownN).forEach(function (x) {
        var who = x.known_by.map(function (k) { return (k.name === c.me ? "you" : k.name) + (k.since ? " (" + k.since + ")" : ""); }).join(", ");
        list.appendChild(el("li", { class: "np" + (x.known_by.length > 1 ? " shared" : "") }, [
          el("div", { class: "np-top" }, [
            x.url ? el("a", { class: "np-name", href: x.url, target: "_blank", rel: "noopener", text: x.name + " ↗" }) : el("span", { class: "np-name", text: x.name }),
            el("span", { class: "tag", text: cap(x.bucket) }),
            x.known_by.length > 1 ? el("span", { class: "tag shared", text: "known by " + x.known_by.length }) : null]),
          x.position ? el("div", { class: "np-pos", text: x.position }) : null,
          el("div", { class: "np-who", text: "Known by " + who })]));
      });
      if (!rows.length) list.appendChild(el("li", { class: "muted", text: "No one matches." }));
      more.hidden = rows.length <= shownN;
      more.textContent = "Show more (" + fmtN(rows.length - shownN) + " left)";
    }
    input.addEventListener("input", function () { text = input.value; shownN = PAGE_N; draw(); });
    more.addEventListener("click", function () { shownN += PAGE_N; draw(); });
    var node = el("section", { class: "co-card", id: "people" }, [
      el("h2", { text: "People your cohort knows at " + c.name + " (" + fmtN(c.named_total) + ")" }),
      el("p", { class: "muted tiny", text: "Known by several classmates first, then people in the role's field, recruiters and leaders. Names link to LinkedIn." }),
      input, chips, list, more]);
    draw();
    return { node: node, pick: function (b) {
      bucket = b === "rest" ? "" : b; shownN = PAGE_N; draw();
      node.scrollIntoView({ behavior: "smooth", block: "start" });
    } };
  }

  var logout = document.querySelector(".cb-logout");
  if (logout) logout.addEventListener("click", function () {
    fetch("/logout", { method: "POST" }).then(function () { location.href = "/login"; });
  });

  var detailParams = new URLSearchParams(location.search);
  if (detailParams.get("id") || detailParams.get("company")) { showDetail(detailParams); return; }

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
      fetchRanks();
      if (filters.vertical && verticals.indexOf(filters.vertical) < 0) filters.vertical = "";
      bind(); render();
    })
    .catch(function (e) {
      var banner = $("banner"); banner.hidden = false;
      banner.textContent = "Couldn't load companies (" + e.message + ").";
    });
})();
