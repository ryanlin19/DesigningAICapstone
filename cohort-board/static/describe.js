// "Job description" toggle, shared by Find a job and the Companies page. The text is fetched only when opened
// (from data/descriptions.db via /api/description) and shown with its headings and bullets.
(function () {
  function el(tag, attrs, kids) {
    var n = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      if (k === "class") n.className = attrs[k]; else if (k === "text") n.textContent = attrs[k]; else n.setAttribute(k, attrs[k]);
    });
    (kids || []).forEach(function (c) { if (c != null) n.appendChild(typeof c === "string" ? document.createTextNode(c) : c); });
    return n;
  }

  function render(text) {
    var out = el("div", { class: "jd-text" });
    text.split(/\n{2,}/).forEach(function (block) {
      var list = null;
      block.split("\n").forEach(function (line) {
        line = line.trim();
        if (!line) return;
        if (line.indexOf("## ") === 0) { list = null; out.appendChild(el("h4", { text: line.slice(3) })); return; }
        if (line.indexOf("• ") === 0) {
          if (!list) { list = el("ul"); out.appendChild(list); }
          list.appendChild(el("li", { text: line.slice(2) }));
          return;
        }
        list = null;
        out.appendChild(el("p", { text: line }));
      });
    });
    return out;
  }

  // A self-contained block: a button, and the description under it once opened.
  function toggle(url) {
    var wrap = el("div", { class: "jd" });
    if (!url) return wrap;
    var btn = el("button", { type: "button", class: "jd-btn", "aria-expanded": "false" }, ["Job description", el("span", { class: "jd-caret", "aria-hidden": "true", text: "▾" })]);
    var panel = el("div", { class: "jd-panel", hidden: "" });
    var loaded = false;
    btn.addEventListener("click", function () {
      var open = btn.getAttribute("aria-expanded") !== "true";
      btn.setAttribute("aria-expanded", String(open));
      panel.hidden = !open;
      if (!open || loaded) return;
      loaded = true;
      panel.textContent = "Loading…";
      fetch("/api/description?url=" + encodeURIComponent(url))
        .then(function (r) { return r.json().then(function (d) { if (!r.ok) throw new Error(d.error || r.status); return d; }); })
        .then(function (d) { panel.textContent = ""; panel.appendChild(render(d.text)); })
        .catch(function (e) {
          loaded = false;
          panel.textContent = "";
          panel.appendChild(el("p", { class: "jd-missing" }, [e.message + " ", el("a", { href: url, target: "_blank", rel: "noopener noreferrer", text: "Read it on the company's site" })]));
        });
    });
    wrap.appendChild(btn); wrap.appendChild(panel);
    return wrap;
  }

  window.JobDescription = { toggle: toggle };
})();
