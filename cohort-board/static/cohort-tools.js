// Cohort tab tools: a bar under the top nav with Overview, Shared contacts, Connect on LinkedIn and Add classmates.
// Each tool is a full-width view that replaces the overview (cohortpage.js). The address shows which one is open
// (/cohort?view=upload|connect|bridges), on this page only, so a link or a reload opens the same view.
// window.COHORT_DATA comes from serve.py (/cohort-data.js). cohort-upload.js and cohort-connect.js add their views on
// "cohort:ready" through window.COHORT.registerView.
(function () {
  var D = window.COHORT_DATA || { companies: {}, manual: {}, classmates: [], people: [], bridges: [] };
  var BUCKETS = {
    engineering: "engineering", data_ml: "data / ML", product: "product", design: "design", recruiting: "recruiting",
    sales_gtm: "sales / GTM", marketing: "marketing", finance: "finance", consulting: "consulting", research: "research",
    operations: "operations", legal: "legal", healthcare: "healthcare", education: "education",
    student_intern: "students / interns", leadership: "leadership", other: "mixed roles"
  };
  var VIEW_ORDER = { overview: 0, bridges: 1, connect: 2, upload: 3 };

  function el(tag, attrs, kids) {
    var n = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      if (k === "class") n.className = attrs[k]; else if (k === "text") n.textContent = attrs[k]; else n.setAttribute(k, attrs[k]);
    });
    (kids || []).forEach(function (c) { if (c) n.appendChild(typeof c === "string" ? document.createTextNode(c) : c); });
    return n;
  }
  function plural(n, one, many) { return n + " " + (n === 1 ? one : many); }
  function joinNames(names) {
    return names.length < 3 ? names.join(" and ") : names.slice(0, -1).join(", ") + " and " + names[names.length - 1];
  }

  var views = {}, overviewBtn = null, bar = null;
  function registerView(name, section, btn, label, onShow) {
    var main = document.querySelector("main");
    main.parentNode.insertBefore(section, main);
    section.hidden = true;
    views[name] = { section: section, btn: btn, label: label, onShow: onShow };
    btn.className = "cohort-view-btn";
    btn.style.order = VIEW_ORDER[name] || 9;
    btn.textContent = label();
    if (btn.parentNode !== bar) bar.appendChild(btn);
    Array.prototype.slice.call(bar.children)                   // keep the page order the same as the visual order (Tab key)
      .sort(function (a, b) { return (+a.style.order || 0) - (+b.style.order || 0); })
      .forEach(function (c) { bar.appendChild(c); });
    btn.addEventListener("click", function () { showView(name); });
  }
  function showView(name) {
    if (name && !views[name]) name = null;
    Object.keys(views).forEach(function (n) {
      var v = views[n], on = n === name;
      v.section.hidden = !on;
      v.btn.classList.toggle("on", on);
      v.btn.setAttribute("aria-current", on ? "page" : "false");
      v.btn.textContent = v.label();
    });
    overviewBtn.classList.toggle("on", !name);
    overviewBtn.setAttribute("aria-current", name ? "false" : "page");
    document.querySelector("main").hidden = !!name;
    try { history.replaceState(null, "", name ? "/cohort?view=" + name : "/cohort"); } catch (e) { /* ignore */ }
    if (name && views[name].onShow) views[name].onShow();
    window.scrollTo(0, 0);
  }

  // ---- Shared contacts: every person known by 2+ classmates, strongest first ----
  function sharedLine(s, company) {
    var role = s.bucket && s.bucket !== "other" ? (BUCKETS[s.bucket] || s.bucket) + " contact" : "contact";
    return [
      el("span", { class: "cohort-depth", title: "Known by " + s.depth + " classmates", text: "×" + s.depth }),
      company || null,
      el("span", {}, ["A " + role + " known by ", el("b", { text: joinNames(s.connectors) })]),
      s.since ? el("span", { class: "cohort-src", text: "first connected " + s.since }) : null
    ];
  }
  function setUpBridges() {
    var btn = el("button", { type: "button" });
    var list = el("div", { class: "cohort-bridge-list" });
    var minDepth = el("select", { class: "field", "aria-label": "Known by at least" }, [2, 3, 4, 5].map(function (n) {
      return el("option", { value: String(n), text: "Known by " + n + "+ classmates" });
    }));
    var boardOnly = el("input", { type: "checkbox" });
    var view = el("section", { class: "wrap cohort-bridges cohort-view" }, [
      el("h2", { text: "Shared contacts" }),
      el("p", { class: "cohort-sub", text: "People known by two or more classmates: the strongest routes in, since several " +
        "classmates can vouch for the same introduction. Classmates themselves, students and school staff are left out. " +
        "Ask any classmate listed to make the introduction." }),
      el("div", { class: "cohort-bridge-tools" }, [minDepth,
        el("label", { class: "chk" }, [boardOnly, " Only companies with roles on the board"])]),
      list
    ]);
    registerView("bridges", view, btn, function () { return "Shared contacts (" + (D.bridges || []).length + ")"; }, draw);

    function draw() {
      var min = +minDepth.value, rows = (D.bridges || []).filter(function (b) {
        return b.depth >= min && (!boardOnly.checked || b.on_board);
      });
      list.textContent = "";
      if (!rows.length) {
        list.appendChild(el("div", { class: "empty", text: (D.bridges || []).length
          ? "No shared contacts match these settings."
          : "No shared contacts yet. They appear once two or more classmates' exports are loaded with contact keys." }));
        return;
      }
      list.appendChild(el("p", { class: "cohort-sub", text: plural(rows.length, "shared contact", "shared contacts") +
        " at " + plural(Object.keys(rows.reduce(function (m, b) { m[b.company] = 1; return m; }, {})).length, "company", "companies") }));
      list.appendChild(el("ul", { class: "cohort-list" }, rows.slice(0, 500).map(function (b) {
        var co = el("a", { class: "cohort-co", href: "/companies?company=" + encodeURIComponent(b.company) + "#graph",
                           title: "Open " + b.company + " on the Companies tab", text: b.company });
        return el("li", {}, sharedLine(b, co));
      })));
    }
    minDepth.addEventListener("change", draw);
    boardOnly.addEventListener("change", draw);
  }

  document.addEventListener("DOMContentLoaded", function () {
    // the tools bar, under the top nav (styles in nav.css)
    bar = el("div", { class: "cb-nav-row cohort-views", role: "group", "aria-label": "Cohort tools" });
    overviewBtn = el("button", { type: "button", class: "cohort-view-btn on", "aria-current": "page", text: "Overview" });
    overviewBtn.style.order = 0;
    overviewBtn.addEventListener("click", function () { showView(null); });
    bar.appendChild(overviewBtn);
    document.querySelector(".cb-nav").appendChild(el("div", { class: "cb-sub" }, [bar]));
    if (window.COHORT_ERROR) {
      var page = document.getElementById("page");
      page.parentNode.insertBefore(el("p", { class: "banner wrap", role: "alert", text: window.COHORT_ERROR }), page.parentNode.firstChild);
    }
    setUpBridges();
    document.dispatchEvent(new CustomEvent("cohort:ready"));
    showView(new URLSearchParams(location.search).get("view"));
  });

  window.COHORT = { el: el, plural: plural, data: D, registerView: registerView, showView: showView };
})();
