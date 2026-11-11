// "Add classmates": drop LinkedIn exports (zips or unzipped folders, several at once), load each one,
// and manage who is loaded. Each export goes to this computer's server, which runs the ingest, uploads
// the result to the cohort database and deletes the export.
(function () {
  // Invitations.csv is only for the classmate's own profile link (the sender link on invitations they sent).
  var ALLOWED = ["Connections.csv", "Profile.csv", "Positions.csv", "Education.csv", "Skills.csv", "Invitations.csv"];

  document.addEventListener("cohort:ready", function () {
    var C = window.COHORT, el = C.el, plural = C.plural, D = C.data;
    var views = document.querySelector(".cohort-views");
    if (!views) return;
    var btn = el("button", { class: "btn cohort-view-btn", type: "button", "aria-expanded": "false" });
    views.insertBefore(btn, views.firstChild);

    var queue = [], ignored = 0, running = false, changed = false;
    var fileInput = el("input", { type: "file", multiple: "", accept: ".zip,.csv", hidden: "" });
    var folderInput = el("input", { type: "file", multiple: "", webkitdirectory: "", hidden: "" });
    var drop = el("div", { class: "cohort-drop" }, [
      el("p", {}, [el("b", { text: "Drop LinkedIn exports here" }),
        " — the .zip files LinkedIn emails, or the unzipped folders. Several at once is fine."]),
      pick("Choose zip files", fileInput), pick("Choose a folder", folderInput), fileInput, folderInput
    ]);
    var queueBox = el("div", { class: "cohort-queue" });
    var note = el("p", { class: "cohort-sub" });
    var consent = el("input", { type: "checkbox" });
    var ai = el("input", { type: "checkbox" });
    var go = el("button", { class: "btn cohort-save", type: "button", disabled: "" });
    var after = el("span", { class: "cohort-status" });
    var peopleBox = el("div", { class: "cohort-people" });

    var view = el("section", { class: "wrap cohort-view cohort-upload" }, [
      el("h2", { text: "Add classmates" }),
      el("p", { class: "cohort-sub", text: "Each export is read on this computer: only Connections, Profile, Positions, " +
        "Education and Skills are opened, plus Invitations for one thing only, the classmate's own profile link (taken " +
        "from invitations they sent, when you don't type it in). The export is deleted as soon as it's loaded, and from a " +
        "folder only those files are sent at all. Contacts' names, job titles and LinkedIn links are kept for the " +
        "relationship graph; their emails are not. Loading a classmate again replaces their earlier data." }),
      el("div", { class: "cohort-howto" }, [
        el("b", { text: "Getting your LinkedIn export: " }),
        el("a", { href: "https://www.linkedin.com/mypreferences/d/download-my-data", target: "_blank", rel: "noopener",
                  text: "open LinkedIn's “Get a copy of your data” page ↗" }),
        el("ol", {}, [
          el("li", { text: "Pick the files you want: tick Connections and Profile (or take the full archive)." }),
          el("li", { text: "Click “Request archive”. LinkedIn emails you a download link, usually within minutes for Connections and up to a day for the full archive." }),
          el("li", { text: "Download the .zip and drop it below as it is: no need to unzip." })])]),
      D.can_upload ? null : el("p", { class: "cohort-warn", text: "Uploads are off: no contact key is set up. Run " +
        "`python -m ingest.contact_keys new` in linkedin-ingest, then restart the board." }),
      drop, note, queueBox,
      el("div", { class: "cohort-run" }, [
        el("label", { class: "chk" }, [consent, " These classmates agreed to share their LinkedIn connections and profile link with the cohort"]),
        D.ai_available ? el("label", { class: "chk" }, [ai, " Use AI for unclear job titles and companies (uses your Anthropic API key)"]) : null,
        go, after]),
      el("h3", { text: "Loaded classmates" }), peopleBox
    ]);
    C.registerView("upload", view, btn, function () { return "Add classmates (" + (D.people || []).length + ")"; }, drawPeople);

    function pick(label, input) {
      var b = el("button", { class: "btn", type: "button", text: label });
      b.addEventListener("click", function () { input.click(); });
      return b;
    }

    // ---- collecting files ----
    fileInput.addEventListener("change", function () { addFiles(Array.prototype.map.call(fileInput.files, function (f) { return { file: f, path: f.name }; })); fileInput.value = ""; });
    folderInput.addEventListener("change", function () { addFiles(Array.prototype.map.call(folderInput.files, function (f) { return { file: f, path: f.webkitRelativePath || f.name }; })); folderInput.value = ""; });
    ["dragenter", "dragover"].forEach(function (t) { drop.addEventListener(t, function (e) { e.preventDefault(); drop.classList.add("over"); }); });
    ["dragleave", "drop"].forEach(function (t) { drop.addEventListener(t, function () { drop.classList.remove("over"); }); });
    drop.addEventListener("drop", function (e) {
      e.preventDefault();
      var items = Array.prototype.slice.call(e.dataTransfer.items || []);
      var entries = items.map(function (i) { return i.webkitGetAsEntry && i.webkitGetAsEntry(); }).filter(Boolean);
      if (!entries.length) {
        addFiles(Array.prototype.map.call(e.dataTransfer.files, function (f) { return { file: f, path: f.name }; }));
        return;
      }
      Promise.all(entries.map(walk)).then(function (lists) { addFiles([].concat.apply([], lists)); });
    });
    function walk(entry) {
      return new Promise(function (resolve) {
        if (entry.isFile) { entry.file(function (f) { resolve([{ file: f, path: entry.fullPath.replace(/^\//, "") }]); }, function () { resolve([]); }); return; }
        var reader = entry.createReader(), all = [];
        (function more() {
          reader.readEntries(function (batch) {
            if (!batch.length) { Promise.all(all.map(walk)).then(function (l) { resolve([].concat.apply([], l)); }); return; }
            all = all.concat(Array.prototype.slice.call(batch)); more();
          }, function () { resolve([]); });
        })();
      });
    }

    // A zip is one classmate; loose export files are grouped by the folder they sit in.
    function addFiles(list) {
      var groups = {};
      list.forEach(function (x) {
        var name = x.path.split("/").pop();
        if (/\.zip$/i.test(name)) { queue.push(item({ kind: "zip", label: name, file: x.file, size: x.file.size })); return; }
        if (ALLOWED.indexOf(name) < 0) { ignored++; return; }
        var folder = x.path.indexOf("/") >= 0 ? x.path.slice(0, x.path.lastIndexOf("/")) : "Selected files";
        (groups[folder] = groups[folder] || { kind: "csv", label: folder, files: {} }).files[name] = x.file;
      });
      Object.keys(groups).forEach(function (k) { queue.push(item(groups[k])); });
      draw();
    }

    function item(g) {
      g.name = el("input", { maxlength: "80", autocomplete: "off", placeholder: "From Profile.csv" });
      g.url = el("input", { maxlength: "300", autocomplete: "off", placeholder: "Leave blank to find it in the export" });
      g.status = el("div", { class: "cohort-status" });
      var rm = el("button", { class: "cohort-del", type: "button", text: "Remove" });
      rm.addEventListener("click", function () { if (!running) { queue.splice(queue.indexOf(g), 1); draw(); } });
      var what = g.kind === "zip" ? (g.size >= 1048576 ? (g.size / 1048576).toFixed(1) + " MB" : Math.max(1, Math.round(g.size / 1024)) + " KB") + " zip"
        : Object.keys(g.files).length + " export files: " + Object.keys(g.files).join(", ");
      var missing = g.kind === "csv" && !g.files["Connections.csv"];
      g.card = el("div", { class: "cohort-item" }, [
        el("div", { class: "cohort-item-h" }, [el("b", { text: g.label }), el("span", { class: "cohort-sub", text: what }), rm]),
        el("div", { class: "cohort-form" }, [field("Classmate's name", g.name), field("Their LinkedIn profile link (keeps classmates out of shared contacts)", g.url)]),
        g.status]);
      if (missing) { g.status.textContent = "No Connections.csv in this folder, so it can't be loaded."; g.status.className = "cohort-status bad"; g.skip = true; }
      return g;
    }
    function field(label, input) { return el("label", { class: "cohort-field" }, [el("span", { text: label }), input]); }

    function draw() {
      queueBox.textContent = "";
      queue.forEach(function (g) { queueBox.appendChild(g.card); });
      note.textContent = ignored ? plural(ignored, "other file was", "other files were") + " left out and never sent (messages, invitations and so on)." : "";
      var n = pending().length;
      go.textContent = n ? "Load " + plural(n, "classmate", "classmates") : "Load classmates";
      go.disabled = running || !n || !consent.checked || !D.can_upload;
    }
    function pending() { return queue.filter(function (g) { return !g.done && !g.skip; }); }
    consent.addEventListener("change", draw);

    // ---- loading, one export at a time ----
    go.addEventListener("click", function () {
      running = true; draw(); after.textContent = "";
      var todo = pending(), ok = 0;
      (function next(i) {
        if (i >= todo.length) {
          running = false; draw();
          after.className = "cohort-status ok";
          after.textContent = plural(ok, "classmate", "classmates") + " loaded. ";
          if (ok) { changed = true; after.appendChild(reloadBtn()); }
          return;
        }
        var g = todo[i];
        g.status.className = "cohort-status";
        g.status.textContent = "Loading… reading the export, matching companies, uploading to the database.";
        send(g).then(function (r) {
          g.done = true; ok++;
          g.status.className = "cohort-status ok";
          g.status.textContent = "Loaded " + r.name + ": " + plural(r.connections, "connection", "connections") + ", " +
            plural(r.contacts_keyed, "contact", "contacts") + " fingerprinted, at " + plural(r.companies, "company", "companies") + "." +
            (r.profile_url_source === "Invitations.csv" ? " Found their profile link in the export: " + r.profile_url
              : r.profile_url ? "" : " No profile link: add it in Connect on LinkedIn.") +
            (r.replaced ? " Replaced their earlier data." : "");
          upsertPerson(r);
        }).catch(function (e) {
          g.status.className = "cohort-status bad";
          g.status.textContent = "Not loaded: " + e.message;
        }).then(function () { next(i + 1); });
      })(0);
    });

    function send(g) {
      var qs = new URLSearchParams({ filename: g.label, name: g.name.value.trim(), profile_url: g.url.value.trim(), ai: ai.checked ? "1" : "0" });
      var body = g.kind === "zip" ? Promise.resolve(g.file) : Promise.all(Object.keys(g.files).map(function (n) {
        return g.files[n].text().then(function (t) { return [n, t]; });
      })).then(function (pairs) {
        var files = {}; pairs.forEach(function (p) { files[p[0]] = p[1]; });
        return JSON.stringify({ files: files });
      });
      return body.then(function (b) {
        return fetch("/api/upload?" + qs, { method: "POST", body: b,
          headers: { "Content-Type": g.kind === "zip" ? "application/zip" : "application/json" } });
      }).then(function (r) { return r.ok ? r.json() : r.text().then(function (t) { throw new Error(t || "error " + r.status); }); });
    }

    // ---- loaded classmates ----
    function upsertPerson(r) {
      D.people = (D.people || []).filter(function (p) { return p.id !== r.person_id; });
      D.people.push({ id: r.person_id, name: r.name, contacts: r.contacts_keyed, fingerprinted: true, updated: new Date().toISOString().slice(0, 10) });
      D.people.sort(function (a, b) { return a.name.localeCompare(b.name); });
      drawPeople();
    }
    function reloadBtn() {
      var b = el("button", { class: "linkbtn", type: "button", text: "Refresh the board to see their connections" });
      b.addEventListener("click", function () { location.reload(); });
      return b;
    }
    function drawPeople() {
      peopleBox.textContent = "";
      var ppl = D.people || [];
      if (!ppl.length) { peopleBox.appendChild(el("div", { class: "empty", text: "Nobody loaded yet." })); return; }
      peopleBox.appendChild(el("ul", { class: "cohort-list" }, ppl.map(function (p) {
        var rm = el("button", { class: "cohort-del", type: "button", text: "Remove" });
        rm.addEventListener("click", function () {
          if (!confirm("Remove " + p.name + " and everything loaded from their export? This also deletes it from the cloud database.")) return;
          rm.disabled = true;
          fetch("/api/people/" + encodeURIComponent(p.id), { method: "DELETE" }).then(function (r) {
            if (!r.ok) return r.text().then(function (t) { throw new Error(t); });
            D.people = D.people.filter(function (x) { return x.id !== p.id; });
            changed = true; drawPeople();
          }).catch(function (e) { rm.disabled = false; alert("Not removed: " + e.message); });
        });
        return el("li", {}, [el("b", { text: p.name }), plural(p.contacts || 0, "contact", "contacts"),
          el("span", { class: "cohort-src", text: p.fingerprinted ? "fingerprinted" : "totals only: load again for shared contacts" }),
          p.updated ? el("span", { class: "cohort-src", text: "loaded " + p.updated }) : null, rm]);
      })));
      if (changed) peopleBox.appendChild(el("p", {}, [reloadBtn()]));
    }
    draw();
  });
})();
