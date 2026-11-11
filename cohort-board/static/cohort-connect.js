// "Connect on LinkedIn": every loaded classmate, whether they're already a connection of yours, and a
// one-click way to open their profile with the note copied. LinkedIn doesn't allow sending invitations
// automatically, so the final Connect click happens on LinkedIn, by you.
(function () {
  var DEFAULT_NOTE = "Hi! I found you through our cohort's shared-network job board, where classmates pool " +
    "their connections for warm intros. I'd love to connect, please accept!";
  var NOTE_LIMIT = 200;   // LinkedIn's limit for notes on free accounts (Premium allows more)
  var STATUS = { connected: ["Connected", "good"], not_connected: ["Not connected yet", "warn"], unknown: ["Can't tell yet", "neutral"] };

  function getLocal(k, d) { try { var v = localStorage.getItem(k); return v === null ? d : v; } catch (e) { return d; } }
  function setLocal(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* private mode */ } }
  function opened() { try { return JSON.parse(sessionStorage.getItem("cohort.opened") || "[]"); } catch (e) { return []; } }
  function markOpened(id) {
    var o = opened(); if (o.indexOf(id) < 0) o.push(id);
    try { sessionStorage.setItem("cohort.opened", JSON.stringify(o)); } catch (e) { /* private mode */ }
  }

  document.addEventListener("cohort:ready", function () {
    var C = window.COHORT, el = C.el, plural = C.plural, D = C.data;
    var views = document.querySelector(".cohort-views");
    if (!views) return;
    var btn = el("button", { class: "btn cohort-view-btn", type: "button", "aria-expanded": "false" });
    views.insertBefore(btn, views.firstChild);

    var meSelect = el("select", { class: "field", "aria-label": "Who you are" });
    var note = el("textarea", { class: "field cohort-note", rows: "3", maxlength: String(NOTE_LIMIT), "aria-label": "Invitation note" });
    note.value = getLocal("cohort.note", DEFAULT_NOTE);
    var count = el("span", { class: "cohort-sub" });
    var copyBtn = el("button", { class: "btn", type: "button", text: "Copy note" });
    var copied = el("span", { class: "cohort-status ok", role: "status" });
    var showConnected = el("input", { type: "checkbox" });
    var tally = el("span", { class: "cohort-sub" });
    var list = el("div", { class: "cohort-queue" });

    var view = el("section", { class: "wrap cohort-view cohort-connect" }, [
      el("h2", { text: "Connect with classmates" }),
      el("p", { class: "cohort-sub", text: "Open a profile and the note below is copied for you. On LinkedIn, click Connect, then " +
        "Add a note, paste, and Send. LinkedIn doesn't allow invitations to be sent automatically, so that last click is " +
        "yours. LinkedIn limits how many invitations you can send each week, and free accounts get only a few notes a " +
        "month, so you can also send without a note." }),
      el("div", { class: "cohort-connect-me" }, [el("label", { class: "cohort-field" }, [el("span", { text: "I am" }), meSelect])]),
      el("label", { class: "cohort-field" }, [el("span", { text: "Note for everyone" }), note]),
      el("div", { class: "cohort-run" }, [count, copyBtn, copied]),
      el("div", { class: "cohort-run" }, [el("label", { class: "chk" }, [showConnected, " Also show classmates I'm already connected to"]), tally]),
      list
    ]);
    C.registerView("connect", view, btn, function () {
      var n = (D.people || []).filter(function (p) { return p.status === "not_connected"; }).length;
      return "Connect on LinkedIn" + (n ? " (" + n + ")" : "");
    }, draw);

    meSelect.appendChild(el("option", { value: "", text: "Choose yourself…" }));
    (D.people || []).forEach(function (p) { meSelect.appendChild(el("option", { value: p.id, text: p.name })); });
    meSelect.value = D.me || "";
    meSelect.addEventListener("change", function () {
      fetch("/api/me", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ id: meSelect.value || null }) })
        .then(function (r) { if (!r.ok) throw new Error(r.status); location.reload(); })
        .catch(function () { alert("Couldn't save that. Is the server still running?"); });
    });

    function updateCount() {
      count.textContent = note.value.length + " / " + NOTE_LIMIT + " characters";
      setLocal("cohort.note", note.value);
    }
    note.addEventListener("input", updateCount);
    updateCount();

    function copyNote() {
      var text = note.value;
      var done = function () { copied.textContent = "Note copied."; setTimeout(function () { copied.textContent = ""; }, 2500); };
      if (navigator.clipboard && window.isSecureContext) return navigator.clipboard.writeText(text).then(done, fallback);
      fallback();
      function fallback() { note.select(); try { document.execCommand("copy"); done(); } catch (e) { copied.textContent = "Select the note and copy it."; } }
    }
    copyBtn.addEventListener("click", copyNote);
    showConnected.addEventListener("change", draw);

    var ORDER = { not_connected: 0, unknown: 1, connected: 2 };
    function draw() {
      list.textContent = "";
      if (!D.me) {
        list.appendChild(el("div", { class: "cohort-warn", text: "Choose yourself above to see who you're already connected to." }));
      }
      var o = opened();
      var others = (D.people || []).filter(function (p) { return p.id !== D.me; });
      var rows = others.filter(function (p) { return showConnected.checked || p.status !== "connected"; })
        .sort(function (a, b) { return (ORDER[a.status] || 1) - (ORDER[b.status] || 1) || a.name.localeCompare(b.name); });
      var nConn = others.filter(function (p) { return p.status === "connected"; }).length;
      tally.textContent = plural(o.length, "profile", "profiles") + " opened this session" +
        (D.me ? " · " + plural(nConn, "classmate", "classmates") + " already connected" : "");
      if (!rows.length) {
        list.appendChild(el("div", { class: "empty", text: others.length ? "You're connected to everyone loaded so far." : "No other classmates loaded yet." }));
        return;
      }
      rows.forEach(function (p) { list.appendChild(card(p, o.indexOf(p.id) >= 0)); });
    }

    function card(p, wasOpened) {
      var st = STATUS[p.status];
      var head = el("div", { class: "cohort-item-h" }, [
        el("b", { text: p.name }),
        st ? el("span", { class: "badge " + st[1], text: st[0] }) : null,
        wasOpened ? el("span", { class: "badge accent", text: "Opened this session" }) : null,
        el("span", { class: "cohort-sub", text: plural(p.contacts || 0, "contact", "contacts") + " loaded" })
      ]);
      var body;
      if (p.profile_url) {
        var open = el("button", { class: "btn cohort-save", type: "button", text: wasOpened ? "Open profile again" : "Open profile & copy note" });
        open.addEventListener("click", function () {
          copyNote();
          window.open(p.profile_url, "_blank", "noopener");
          markOpened(p.id);
          draw();
        });
        body = el("div", { class: "cohort-run" }, [open, el("span", { class: "cohort-sub", text: p.profile_url })]);
      } else {
        var input = el("input", { maxlength: "300", autocomplete: "off", placeholder: "https://www.linkedin.com/in/…", "aria-label": "Their LinkedIn profile link" });
        var save = el("button", { class: "btn", type: "button", text: "Save link" });
        var msg = el("span", { class: "cohort-status" });
        save.addEventListener("click", function () {
          save.disabled = true; msg.className = "cohort-status"; msg.textContent = "Saving…";
          fetch("/api/people/" + encodeURIComponent(p.id) + "/link", { method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ profile_url: input.value.trim() }) })
            .then(function (r) { return r.ok ? r.json() : r.text().then(function (t) { throw new Error(t); }); })
            .then(function (r) { p.profile_url = r.profile_url; p.linkChanged = true; draw(); })
            .catch(function (e) { save.disabled = false; msg.className = "cohort-status bad"; msg.textContent = e.message; });
        });
        body = el("div", { class: "cohort-form" }, [
          el("label", { class: "cohort-field" }, [el("span", { text: "No profile link on file. Add it to connect" }), input]),
          el("div", { class: "cohort-run" }, [save, msg])]);
      }
      var why = p.status === "unknown" ? el("p", { class: "cohort-sub cohort-why", text: p.linkChanged
        ? "Link saved. Refresh the board to recheck whether you're connected."
        : "To check, the board needs your export (loaded with fingerprints) and their profile link, or the other way round." }) : null;
      return el("div", { class: "cohort-item" }, [head, body, why]);
    }
  });
})();
