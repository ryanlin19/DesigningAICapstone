// Cohort connections layer for the private job board. Loaded before the board's own script.
// window.COHORT_DATA comes from serve.py: LinkedIn-export counts (read-only) plus connections added by hand.
(function () {
  var D = window.COHORT_DATA || { companies: {}, manual: {}, classmates: [] };
  D.manual = D.manual || {};

  var BUCKETS = {
    engineering: "engineering", data_ml: "data / ML", product: "product", design: "design", recruiting: "recruiting",
    sales_gtm: "sales / GTM", marketing: "marketing", finance: "finance", consulting: "consulting", research: "research",
    operations: "operations", legal: "legal", healthcare: "healthcare", education: "education",
    student_intern: "students / interns", leadership: "leadership", other: "mixed roles"
  };

  function el(tag, attrs, kids) {
    var n = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      if (k === "class") n.className = attrs[k];
      else if (k === "text") n.textContent = attrs[k];
      else n.setAttribute(k, attrs[k]);
    });
    (kids || []).forEach(function (c) { if (c) n.appendChild(typeof c === "string" ? document.createTextNode(c) : c); });
    return n;
  }

  function derived(co) { return (D.companies[co] && D.companies[co].connectors) || []; }
  function manual(co) { return D.manual[co] || []; }
  function stats(co) {
    // contacts: unique people (deduplicated where the data allows it) plus hand-added ones
    var people = {}, contacts = (D.companies[co] && D.companies[co].total) || 0;
    derived(co).forEach(function (c) { people[c.name] = 1; });
    manual(co).forEach(function (m) { people[m.classmate] = 1; contacts += 1; });
    return { classmates: Object.keys(people).length, contacts: contacts };
  }
  function plural(n, one, many) { return n + " " + (n === 1 ? one : many); }

  function sharedOf(co) { return (D.companies[co] && D.companies[co].shared) || []; }
  function badgeText(co) {
    var s = stats(co), n = sharedOf(co).length;
    if (!s.contacts) return "";
    return plural(s.classmates, "classmate", "classmates") + " · " + plural(s.contacts, "contact", "contacts") +
      (n ? " · " + n + " shared" : "");
  }

  // A deep connection: one person known by several classmates. Names are never sent to the page.
  function joinNames(names) {
    return names.length < 3 ? names.join(" and ") : names.slice(0, -1).join(", ") + " and " + names[names.length - 1];
  }
  function sharedLine(s, company) {
    var role = s.bucket && s.bucket !== "other" ? (BUCKETS[s.bucket] || s.bucket) + " contact" : "contact";
    return [
      el("span", { class: "cohort-depth", title: "Known by " + s.depth + " classmates", text: "×" + s.depth }),
      company || null,
      el("span", {}, ["A " + role + " known by ", el("b", { text: joinNames(s.connectors) })]),
      s.since ? el("span", { class: "cohort-src", text: "first connected " + s.since }) : null
    ];
  }
  // ---- "Classmate worked here": classmates' own past or current jobs at the company ----
  function alumniOf(co) { return (D.companies[co] && D.companies[co].alumni) || []; }
  function alumniText(co) {
    var a = alumniOf(co);
    if (!a.length) return "";
    if (a.length === 1) return a[0].name + (a[0].current ? " works here" : " worked here");
    return a.length + " classmates worked here";
  }
  function jobTag(co) {
    var a = alumniOf(co);
    if (!a.length) return null;
    var now = a.some(function (x) { return x.current; });
    return el("span", { class: "badge cohort-alumni-tag", title: a.map(function (x) { return x.name + ", " + x.years; }).join("; "),
      text: "💼 Classmate " + (now ? "works" : "worked") + " here" });
  }

  function headBadge(co) {
    var b = el("span", { class: "cohort-badges", "data-cohort-badge": co });
    paintBadge(b, co);
    return b;
  }
  function paintBadge(b, co) {
    var t = badgeText(co), w = alumniText(co);
    b.textContent = "";
    if (w) b.appendChild(el("span", { class: "cohort-badge cohort-alumni", text: "💼 " + w }));
    if (t) b.appendChild(el("span", { class: "cohort-badge", text: "👥 " + t }));
    b.hidden = !t && !w;
  }

  function panel(co) {
    var p = el("div", { class: "cohort-panel", "data-cohort-panel": co });
    fill(p, co);
    return p;
  }

  function fill(p, co) {
    p.textContent = "";
    var d = derived(co), m = manual(co);
    var al = alumniOf(co);
    if (al.length) {
      p.appendChild(el("div", { class: "cohort-h" }, [el("b", { text: "💼 Classmates who worked here" }),
        el("span", { class: "cohort-sub", text: "the warmest route in: they know the team and the hiring process" })]));
      p.appendChild(el("ul", { class: "cohort-list" }, al.map(function (a) {
        return el("li", {}, [el("b", { text: a.name }), a.title ? a.title : null,
          a.years ? el("span", { class: "cohort-src", text: a.years }) : null,
          a.current ? el("span", { class: "cohort-src cohort-now", text: "works here now" }) : null]);
      })));
    }
    p.appendChild(el("div", { class: "cohort-h" + (al.length ? " cohort-h2" : "") }, [el("b", { text: "Cohort connections" }),
      el("span", { class: "cohort-sub", text: d.length || m.length ? badgeText(co) : "None yet" })]));

    if (d.length) {
      p.appendChild(el("ul", { class: "cohort-list" }, d.map(function (c) {
        return el("li", {}, [el("b", { text: c.name }), " knows " + plural(c.count, "person", "people") + " here",
          c.bucket && c.bucket !== "other" ? ", mostly " + (BUCKETS[c.bucket] || c.bucket) : "",
          el("span", { class: "cohort-src", text: "LinkedIn export" })]);
      })));
    }
    var sh = sharedOf(co);
    if (sh.length) {
      p.appendChild(el("div", { class: "cohort-h cohort-h2" }, [el("b", { text: "Shared contacts" }),
        el("span", { class: "cohort-sub", text: "people here known by two or more classmates" })]));
      p.appendChild(el("ul", { class: "cohort-list" }, sh.map(function (s) { return el("li", {}, sharedLine(s)); })));
    }
    if (m.length) {
      p.appendChild(el("ul", { class: "cohort-list" }, m.map(function (e) {
        var who = [e.contact, e.title].filter(Boolean).join(", ");
        var del = el("button", { class: "cohort-del", type: "button", "aria-label": "Remove this connection", text: "Remove" });
        del.addEventListener("click", function () { remove(co, e, del); });
        return el("li", {}, [el("b", { text: e.classmate }), " knows " + who,
          e.note ? el("span", { class: "cohort-note", text: "“" + e.note + "”" }) : null,
          el("span", { class: "cohort-src", text: "added by hand" }), del]);
      })));
    }
    p.appendChild(addForm(co));
  }

  function addForm(co) {
    var wrap = el("div", { class: "cohort-add" });
    var open = el("button", { class: "linkbtn cohort-open", type: "button", text: "+ Add a connection at " + co });
    var listId = "cohort-classmates";
    if (!document.getElementById(listId)) {
      document.body.appendChild(el("datalist", { id: listId }, D.classmates.map(function (n) { return el("option", { value: n }); })));
    }
    var f = el("form", { class: "cohort-form", hidden: "" }, [
      field("Who knows them (classmate)", el("input", { name: "classmate", list: listId, required: "", maxlength: "80", autocomplete: "off" })),
      field("Contact's name", el("input", { name: "contact", maxlength: "80", autocomplete: "off" })),
      field("Their role", el("input", { name: "title", maxlength: "120", placeholder: "e.g. Engagement Manager", autocomplete: "off" })),
      field("Note", el("input", { name: "note", maxlength: "300", placeholder: "e.g. former teammate, happy to refer", autocomplete: "off" })),
      el("div", { class: "cohort-actions" }, [
        el("button", { class: "btn cohort-save", type: "submit", text: "Save" }),
        el("button", { class: "linkbtn", type: "button", text: "Cancel", "data-cancel": "" }),
        el("span", { class: "cohort-err", role: "status" })])
    ]);
    open.addEventListener("click", function () { open.hidden = true; f.hidden = false; f.elements.classmate.focus(); });
    f.querySelector("[data-cancel]").addEventListener("click", function () { f.reset(); f.hidden = true; open.hidden = false; });
    f.addEventListener("submit", function (ev) {
      ev.preventDefault();
      var v = { company: co, classmate: f.elements.classmate.value, contact: f.elements.contact.value,
                title: f.elements.title.value, note: f.elements.note.value };
      var err = f.querySelector(".cohort-err");
      if (!v.contact.trim() && !v.title.trim()) { err.textContent = "Add their name or their role."; return; }
      err.textContent = "Saving…";
      fetch("/api/connections", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(v) })
        .then(function (r) { return r.ok ? r.json() : r.text().then(function (t) { throw new Error(t || r.status); }); })
        .then(function (entry) {
          (D.manual[co] = D.manual[co] || []).push(entry);
          if (D.classmates.indexOf(entry.classmate) < 0) {
            D.classmates.push(entry.classmate);
            document.getElementById(listId).appendChild(el("option", { value: entry.classmate }));
          }
          refresh(co);
        })
        .catch(function (e) { err.textContent = "Not saved: " + e.message; });
    });
    wrap.appendChild(open); wrap.appendChild(f);
    return wrap;
  }

  function field(label, input) {
    return el("label", { class: "cohort-field" }, [el("span", { text: label }), input]);
  }

  function remove(co, e, btn) {
    if (!confirm("Remove " + e.classmate + "'s connection" + (e.contact ? " to " + e.contact : "") + "?")) return;
    btn.disabled = true;
    fetch("/api/connections/" + e.id, { method: "DELETE" }).then(function (r) {
      if (!r.ok && r.status !== 404) throw new Error(r.status);
      D.manual[co] = manual(co).filter(function (x) { return x.id !== e.id; });
      refresh(co);
    }).catch(function () { btn.disabled = false; alert("Could not remove it. Is the server still running?"); });
  }

  function refresh(co) {
    Array.prototype.forEach.call(document.querySelectorAll("[data-cohort-badge]"), function (b) {
      if (b.getAttribute("data-cohort-badge") === co) paintBadge(b, co);
    });
    Array.prototype.forEach.call(document.querySelectorAll("[data-cohort-panel]"), function (p) {
      if (p.getAttribute("data-cohort-panel") === co) fill(p, co);
    });
  }

  function hide(co) {
    var cb = document.getElementById("onlyConnected"), ab = document.getElementById("onlyAlumni");
    if (ab && ab.checked && !alumniOf(co).length) return true;
    return !!(cb && cb.checked) && !stats(co).contacts && !alumniOf(co).length;
  }

  document.addEventListener("DOMContentLoaded", function () {
    var h = document.querySelector("header.hero .wrap p");
    if (!h) return;
    if (window.COHORT_ERROR) {
      h.parentNode.insertBefore(el("p", { class: "cohort-private cohort-err", role: "alert", text: window.COHORT_ERROR }), h.nextSibling);
    }
    var out = el("button", { class: "linkbtn", type: "button", text: "Log out" });
    out.addEventListener("click", function () {
      fetch("/logout", { method: "POST" }).then(function () { location.href = "/login"; });
    });
    var bridgesBtn = el("button", { class: "btn cohort-view-btn", type: "button", "aria-expanded": "false" });
    var bar = el("p", { class: "cohort-private" }, [
      el("span", { class: "cohort-pill", text: "Private test version" }),
      " Cohort connections are visible only on this computer. ", out, el("span", { class: "cohort-views" }, [bridgesBtn])]);
    h.parentNode.insertBefore(bar, h.nextSibling);
    setUpBridges(bridgesBtn);
    document.dispatchEvent(new CustomEvent("cohort:ready"));
  });

  // ---- Full-page views that replace the role list (Shared contacts, Add classmates) ----
  var views = {};
  function registerView(name, section, btn, label, onShow) {
    var main = document.querySelector("main");
    main.parentNode.insertBefore(section, main);
    section.hidden = true;
    views[name] = { section: section, btn: btn, label: label, onShow: onShow };
    btn.textContent = label();
    btn.addEventListener("click", function () { showView(section.hidden ? name : null); });
  }
  function showView(name) {
    var main = document.querySelector("main");
    Object.keys(views).forEach(function (n) {
      var v = views[n], on = n === name;
      v.section.hidden = !on;
      v.btn.setAttribute("aria-expanded", String(on));
      v.btn.textContent = on ? "Back to roles" : v.label();
    });
    main.hidden = !!name;
    if (name) { if (views[name].onShow) views[name].onShow(); window.scrollTo(0, 0); }
  }

  // ---- Shared contacts view: every person known by 2+ classmates, strongest first ----
  function setUpBridges(btn) {
    var main = document.querySelector("main");
    if (!main) return;
    var list = el("div", { class: "cohort-bridge-list" });
    var minDepth = el("select", { class: "field", "aria-label": "Known by at least" }, [2, 3, 4, 5].map(function (n) {
      return el("option", { value: String(n), text: "Known by " + n + "+ classmates" });
    }));
    var boardOnly = el("input", { type: "checkbox" });
    var view = el("section", { class: "wrap cohort-bridges cohort-view" }, [
      el("h2", { text: "Shared contacts" }),
      el("p", { class: "cohort-sub", text: "People known by two or more classmates: the strongest routes in, since several " +
        "classmates can vouch for the same introduction. Classmates themselves, students and school staff are left out. " +
        "Names are not stored; ask any classmate listed to make the introduction." }),
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
        var co = b.on_board
          ? el("button", { class: "linkbtn cohort-co", type: "button", title: "Show this company's roles", text: b.company })
          : el("span", { class: "cohort-co", text: b.company });
        if (b.on_board) co.addEventListener("click", function () { jump(b.company); });
        return el("li", {}, sharedLine(b, co));
      })));
    }
    function jump(company) {
      showView(null);
      var q = document.getElementById("q");
      if (document.getElementById("tab-jobs").classList.contains("hidden")) document.getElementById("tabMba").click();
      q.value = company;
      q.dispatchEvent(new Event("input"));
      q.scrollIntoView({ block: "center" });
    }
    minDepth.addEventListener("change", draw);
    boardOnly.addEventListener("change", draw);
  }

  window.COHORT = { headBadge: headBadge, panel: panel, hide: hide, jobTag: jobTag, el: el, plural: plural, data: D,
                    registerView: registerView, showView: showView };
})();
