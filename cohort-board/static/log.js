// Log tab: when Muse last ran, and everything that changed the cohort data (Muse findings merged, uploads, removals).
(function () {
  var $ = function (id) { return document.getElementById(id); };
  function el(tag, attrs, kids) {
    var n = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      if (k === "class") n.className = attrs[k]; else if (k === "text") n.textContent = attrs[k]; else n.setAttribute(k, attrs[k]);
    });
    (kids || []).forEach(function (c) { if (c != null) n.appendChild(typeof c === "string" ? document.createTextNode(c) : c); });
    return n;
  }
  function when(iso) {
    if (!iso) return "never";
    var d = new Date(iso), mins = Math.round((Date.now() - d.getTime()) / 60000);
    var ago = mins < 1 ? "just now" : mins < 60 ? mins + " min ago" : mins < 1440 ? Math.round(mins / 60) + " h ago" : Math.round(mins / 1440) + " days ago";
    return d.toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) + " (" + ago + ")";
  }
  var LABEL = { muse: "Muse", board: "Board", upload: "Upload", sync: "Sync" };
  // an entry's details (JSON): a short "Details" toggle; for Muse's LinkedIn checks, the counts and the profiles it opened
  function details(r) {
    var d;
    try { d = r.details ? JSON.parse(r.details) : null; } catch (e) { d = null; }
    if (!d || typeof d !== "object") return null;
    var box = el("div", { class: "log-details", hidden: "" });
    Object.keys(d).forEach(function (k) {
      var v = d[k], label = k.replace(/_/g, " ");
      if (Array.isArray(v) && v.every(function (x) { return typeof x === "string" && /^https?:\/\//.test(x); })) {
        box.appendChild(el("div", {}, [el("b", { text: label + " (" + v.length + "): " })]));
        box.appendChild(el("ul", {}, v.map(function (u) { return el("li", {}, [el("a", { href: u, target: "_blank", rel: "noopener", text: u })]); })));
      } else {
        box.appendChild(el("div", {}, [el("b", { text: label + ": " }), typeof v === "object" ? JSON.stringify(v) : String(v)]));
      }
    });
    var btn = el("button", { type: "button", class: "log-more", "aria-expanded": "false", text: "Details" });
    btn.addEventListener("click", function () { box.hidden = !box.hidden; btn.setAttribute("aria-expanded", String(!box.hidden)); });
    return [btn, box];
  }
  function render(d) {
    var page = $("page"); page.textContent = "";
    var check = el("button", { type: "button", class: "btn primary", text: "Check for Muse updates now" });
    var status = el("span", { class: "muted tiny" });
    check.addEventListener("click", function () {
      check.disabled = true; status.textContent = "Checking the cloud…";
      fetch("/api/log/check", { method: "POST" }).then(function (r) { return r.ok ? r.json() : r.text().then(function (t) { throw new Error(t); }); })
        .then(function (res) { status.textContent = res.found ? "Merged " + res.merged + " of " + res.found + " new finding(s)." : "Nothing new."; load(); })
        .catch(function (e) { status.textContent = e.message; check.disabled = false; });
    });
    page.appendChild(el("div", { class: "results-head" }, [el("div", {}, [el("h1", { text: "Activity log" }),
      el("p", { class: "muted tiny dir-sub", text: "Muse runs, what was merged into the cohort data, uploads and removals. Muse's findings are merged automatically every 15 minutes." })]),
      el("div", { class: "cp-pick" }, [check, status])]));
    var m = d.last_muse;
    var warn = (d.entries || []).filter(function (r) { return r.source === "muse" && r.action === "warning"; })[0];
    if (warn) page.appendChild(el("section", { class: "co-card log-warning" }, [
      el("h2", { text: "Warning during a Muse run, " + when(warn.at) }), el("p", { text: warn.summary })]));
    page.appendChild(el("section", { class: "co-card log-muse" }, [
      el("h2", { text: "Muse last ran: " + (m ? when(m.at) : "no runs recorded yet") }),
      m ? el("p", { text: m.summary }) : el("p", { class: "muted", text: "When Muse adds findings to the cloud database, they show up here." }),
      d.last_check && d.last_check.at ? el("p", { class: "muted tiny", text: "Last checked for updates " + when(d.last_check.at) + (d.last_check.error ? " · error: " + d.last_check.error : "") }) : null]));
    var rows = d.entries || [];
    page.appendChild(el("section", { class: "co-card" }, [el("h2", { text: "History (" + rows.length + ")" }),
      rows.length ? el("ul", { class: "log-list" }, rows.map(function (r) {
        var more = details(r) || [];
        return el("li", { class: "log-row" + (r.action === "warning" ? " is-warning" : "") }, [
          el("span", { class: "tag log-" + r.source, text: r.action === "warning" ? "Warning" : LABEL[r.source] || r.source }),
          el("div", {}, [el("div", { text: r.summary }), el("div", { class: "np-who" }, [when(r.at)].concat(more.slice(0, 1))), more[1] || null])]);
      })) : el("p", { class: "muted", text: "Nothing logged yet." })]));
  }
  function load() { fetch("/api/log").then(function (r) { return r.json(); }).then(render); }
  load();
})();
