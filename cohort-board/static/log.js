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
    page.appendChild(el("section", { class: "co-card log-muse" }, [
      el("h2", { text: "Muse last ran: " + (m ? when(m.at) : "no runs recorded yet") }),
      m ? el("p", { text: m.summary }) : el("p", { class: "muted", text: "When Muse adds findings to the cloud database, they show up here." }),
      d.last_check && d.last_check.at ? el("p", { class: "muted tiny", text: "Last checked for updates " + when(d.last_check.at) + (d.last_check.error ? " · error: " + d.last_check.error : "") }) : null]));
    var rows = d.entries || [];
    page.appendChild(el("section", { class: "co-card" }, [el("h2", { text: "History (" + rows.length + ")" }),
      rows.length ? el("ul", { class: "log-list" }, rows.map(function (r) {
        return el("li", { class: "log-row" }, [el("span", { class: "tag log-" + r.source, text: LABEL[r.source] || r.source }),
          el("div", {}, [el("div", { text: r.summary }), el("div", { class: "np-who", text: when(r.at) })])]);
      })) : el("p", { class: "muted", text: "Nothing logged yet." })]));
  }
  function load() { fetch("/api/log").then(function (r) { return r.json(); }).then(render); }
  var logout = document.querySelector(".cb-logout");
  if (logout) logout.addEventListener("click", function () { fetch("/logout", { method: "POST" }).then(function () { location.href = "/login"; }); });
  load();
})();
