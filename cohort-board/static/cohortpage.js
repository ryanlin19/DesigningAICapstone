// Cohort tab: who's uploaded, which of them you're not connected to on LinkedIn, and the people most of the cohort
// knows that you don't (known by the most classmates first; top 10, extendable to 50).
(function () {
  var TOP = 10;
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

  function whoAreYou(d, page, change) {
    var sel = el("select", { "aria-label": "Who are you?" }, [el("option", { value: "", text: "Pick yourself…" })].concat(
      d.choices.map(function (c) { var o = el("option", { value: c.id, text: c.name }); if (c.id === d.me_id) o.selected = true; return o; })));
    var save = el("button", { type: "button", class: "btn primary", text: "Save" });
    save.addEventListener("click", function () {
      if (!sel.value) return;
      fetch("/api/me", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ id: sel.value }) })
        .then(function () { location.reload(); });
    });
    return el("section", { class: "co-card" }, [
      el("h2", { text: change ? "Change who you are" : "Who are you?" }),
      el("p", { class: "muted tiny", text: "Pick yourself from the classmates who've uploaded, so the board can show who you're not connected to yet." }),
      el("div", { class: "cp-pick" }, [sel, save])]);
  }

  function classmatesCard(d) {
    var notYet = d.classmates.filter(function (c) { return c.connected === false; });
    var yes = d.classmates.filter(function (c) { return c.connected === true; });
    var unknown = d.classmates.filter(function (c) { return c.connected === null; });
    var list = el("ul", { class: "cp-list" }, notYet.map(function (c) {
      return el("li", { class: "cp-row" }, [
        el("div", {}, [el("b", { text: c.name }), c.headline ? el("div", { class: "np-pos", text: c.headline }) : null,
                       el("div", { class: "np-who", text: plural(c.contacts, "contact", "contacts") + " uploaded" })]),
        c.profile_url ? el("a", { class: "btn cp-connect", href: c.profile_url, target: "_blank", rel: "noopener", text: "Connect on LinkedIn ↗" })
                      : el("span", { class: "muted tiny", text: "No profile link" })]);
    }));
    var kids = [el("h2", { text: "Classmates you're not connected with (" + notYet.length + ")" }),
      el("p", { class: "muted tiny", text: "Of the " + plural(d.uploaded, "classmate", "classmates") + " who've uploaded their LinkedIn data. " +
        "Connecting adds their network to yours on LinkedIn too." })];
    if (notYet.length) kids.push(list);
    else if (!unknown.length) kids.push(el("p", { class: "cp-done", text: "You're connected with everyone who's uploaded." }));
    if (unknown.length) kids.push(el("p", { class: "muted", text: "Upload your own LinkedIn data to see who you're connected with." }));
    if (yes.length) kids.push(el("p", { class: "muted tiny", text: "Already connected: " + yes.map(function (c) { return c.name; }).join(", ") }));
    return el("section", { class: "co-card" }, kids);
  }

  function overlapCard(d) {
    var shown = TOP, list = el("ol", { class: "sh-list" });
    var others = d.others_with_contacts;
    var btn = el("button", { type: "button", class: "btn sh-all" });
    function row(x, i) {
      var n = x.known_by.length;
      var tags = [el("span", { class: "tag shared", text: "Known by " + n + (others ? " of " + others : "") + " classmates" })];
      if (x.tier === "Leadership" || x.tier === "Senior") tags.push(el("span", { class: "tag", text: x.tier }));
      if (x.bucket === "recruiting") tags.push(el("span", { class: "tag works", text: "Recruiting" }));
      var name = x.name
        ? (x.url ? el("a", { class: "np-name", href: x.url, target: "_blank", rel: "noopener", text: x.name + " ↗" }) : el("span", { class: "np-name", text: x.name }))
        : el("span", { class: "np-name", text: "Someone (re-upload to see names)" });
      return el("li", { class: "sh" + (i === 0 ? " top" : "") }, [
        el("div", { class: "np-top" }, [el("span", { class: "sh-rank", text: String(i + 1) }), name]),
        el("div", { class: "np-pos" }, [x.position ? x.position + (x.company ? " · " : "") : "",
          x.company_id ? el("a", { href: "/companies?id=" + encodeURIComponent(x.company_id) + "#graph", text: x.company }) : (x.company || "")]),
        el("div", { class: "sh-why" }, tags),
        el("div", { class: "np-who", text: "Known by " + x.known_by.map(function (k) { return k.name + (k.since ? " (" + k.since + ")" : ""); }).join(", ") })]);
    }
    function draw() {
      list.textContent = "";
      d.overlap.slice(0, shown).forEach(function (x, i) { list.appendChild(row(x, i)); });
      btn.hidden = d.overlap.length <= TOP;
      btn.textContent = shown > TOP ? "Show the top " + TOP : "Show the top " + Math.min(50, d.overlap.length);
    }
    btn.addEventListener("click", function () {
      shown = shown > TOP ? TOP : 50; draw();
      if (shown === TOP) node.scrollIntoView({ block: "start" });
    });
    draw();
    var node = el("section", { class: "co-card", id: "overlap" }, [
      el("h2", { text: "People the cohort knows that you don't" }),
      el("p", { class: "muted tiny", text: "Known by the most classmates first (" + fmtN(d.overlap_total) + " people are known by two or more of them), " +
        "then leaders, recruiters and the longest-standing connections. Leaves out anyone you're already connected to." }),
      d.overlap.length ? list : el("p", { class: "muted", text: "No one yet: this fills in as more classmates upload." }),
      btn]);
    return node;
  }

  function render(d) {
    var page = $("page"); page.textContent = "";
    if (!d.ready) { page.appendChild(el("p", { class: "banner", text: "No classmates have uploaded yet." })); return; }
    var change = el("button", { type: "button", class: "linkbtn", text: "change" });
    page.appendChild(el("div", { class: "results-head" }, [el("div", {}, [
      el("h1", { text: "Your cohort" }),
      el("p", { class: "muted tiny dir-sub" }, [plural(d.uploaded, "classmate has", "classmates have") + " uploaded their LinkedIn data" +
        (d.me ? " · You are " + d.me + " (" : ""), d.me ? change : null, d.me ? ")" : ""])]),
      el("a", { class: "btn", href: "/cohort?view=upload", text: "Add or update classmates" })]));
    if (!d.me) { page.appendChild(whoAreYou(d, page)); return; }
    var picker = whoAreYou(d, page, true); picker.hidden = true;
    change.addEventListener("click", function () { picker.hidden = !picker.hidden; });
    page.appendChild(picker);
    page.appendChild(classmatesCard(d));
    page.appendChild(overlapCard(d));
  }

  var logout = document.querySelector(".cb-logout");
  if (logout) logout.addEventListener("click", function () { fetch("/logout", { method: "POST" }).then(function () { location.href = "/login"; }); });

  fetch("/api/cohort").then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
    .then(render)
    .catch(function (e) { $("page").textContent = ""; $("page").appendChild(el("p", { class: "banner", text: "Couldn't load your cohort (" + e.message + ")." })); });
})();
