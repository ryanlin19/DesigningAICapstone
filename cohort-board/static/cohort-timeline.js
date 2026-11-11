// Posting timeline: a histogram of when the roles in view were posted. Drag across the bars (or click one)
// to show only roles posted in that period. The board calls COHORT.drawTimeline on every render with the
// roles that pass every other filter, so the bars always describe what you're looking at.
(function () {
  var C = window.COHORT, el = C.el, plural = C.plural;
  var DAY = 864e5;
  var WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

  function getLocal(k, d) { try { return localStorage.getItem(k) || d; } catch (e) { return d; } }
  function setLocal(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* private mode */ } }

  var state = { view: "60", from: null, to: null };   // from/to: day numbers, inclusive

  function dayNum(s) {
    var m = /^(\d{4})-(\d{2})-(\d{2})/.exec(s || "");
    return m ? Math.floor(Date.UTC(+m[1], +m[2] - 1, +m[3]) / DAY) : null;
  }
  function today() { var d = new Date(); return Math.floor(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()) / DAY); }
  function fmt(n, withYear) {
    return new Date(n * DAY).toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC", year: withYear ? "numeric" : undefined });
  }
  function weekday(n) { return (new Date(n * DAY).getUTCDay() + 6) % 7; }            // Monday = 0
  function rel(n) {
    var a = today() - n;
    return a <= 0 ? "today" : a === 1 ? "yesterday" : a < 14 ? a + " days ago" : fmt(n, a > 300);
  }

  // ---- hooks the board calls ----
  C.inPeriod = function (j) {
    if (state.from === null) return true;
    var n = dayNum(j.posted);
    return n !== null && n >= state.from && n <= state.to;
  };
  C.clearPeriod = function (silent) { state.from = state.to = null; if (!silent) changed(); };
  C.newestNote = function (roles) {
    var sortNew = (document.getElementById("sort") || {}).value === "new";
    if (!roles || !roles.length || !(sortNew || state.from !== null)) return null;
    var n = roles.reduce(function (m, j) { var d = dayNum(j.posted); return d !== null && d > m ? d : m; }, -1);
    return n < 0 ? null : el("span", { class: "cohort-newest", text: "newest " + rel(n) });
  };
  function changed() {
    var p = document.getElementById("cohortPeriod");
    if (!p) return;
    p.value = state.from === null ? "" : state.from + "-" + state.to;
    p.dispatchEvent(new Event("change"));               // the board re-renders on this
  }

  C.drawTimeline = function (list) {
    var host = document.getElementById("cohortTimeline");
    if (!host) return;
    var box = host.querySelector(".cohort-tl");
    if (!box) { box = el("section", { class: "cohort-tl card", "aria-label": "Posting timeline" }); host.appendChild(box); }
    box.textContent = "";

    var t = today();
    var dated = [];
    list.forEach(function (j) { var n = dayNum(j.posted); if (n !== null && n <= t) dated.push(n); });
    var undated = list.length - dated.length;
    var earliest = dated.reduce(function (m, n) { return n < m ? n : m; }, t);
    var span = state.view === "all" ? Math.max(t - earliest + 1, 14) : +state.view;
    var weekly = span > 120;
    var binOf = function (n) { return weekly ? n - weekday(n) : n; };
    var first = binOf(t - span + 1), bins = [], index = {};
    for (var n = first; n <= t; n += weekly ? 7 : 1) { index[n] = bins.length; bins.push({ from: n, to: weekly ? n + 6 : n, count: 0 }); }
    var older = 0, byWeekday = [0, 0, 0, 0, 0, 0, 0];
    dated.forEach(function (n) {
      byWeekday[weekday(n)]++;
      if (n < first) { older++; return; }
      bins[index[binOf(n)]].count++;
    });
    var max = bins.reduce(function (m, b) { return Math.max(m, b.count); }, 0) || 1;
    var inPeriod = state.from === null ? 0 : dated.filter(function (n) { return n >= state.from && n <= state.to; }).length;

    // header: title, summary, view switch
    var viewBtns = el("span", { class: "cohort-sub", text: "Last 2 months" });   // always the last 2 months
    box.appendChild(el("div", { class: "cohort-tl-h" }, [
      el("b", { text: "Posting timeline" }),
      el("span", { class: "cohort-sub", text: plural(dated.length, "role", "roles") + " with a posting date" +
        (undated ? " · " + undated + " without" : "") + (weekly ? " · one bar per week" : " · one bar per day") }),
      viewBtns]));

    // bars
    var bars = el("div", { class: "cohort-tl-bars", role: "img", "aria-label": "Roles posted per " + (weekly ? "week" : "day") +
      " over the last " + (state.view === "all" ? "period" : span + " days") + ", up to " + max + " per bar" });
    bins.forEach(function (b, i) {
      var label = (weekly ? "Week of " + fmt(b.from) : new Date(b.from * DAY).toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric", timeZone: "UTC" })) +
        ": " + plural(b.count, "role", "roles");
      var bar = el("div", { class: "cohort-tl-bar", title: label, "data-i": String(i) }, [
        el("span", { class: "cohort-tl-fill", style: "height:" + (b.count ? Math.max(3, Math.round(100 * b.count / max)) : 0) + "%" })]);
      bars.appendChild(bar);
    });
    paintSelection(bars, bins);
    box.appendChild(bars);
    var mid = bins[Math.floor(bins.length / 2)];
    box.appendChild(el("div", { class: "cohort-tl-axis" }, [
      el("span", { text: fmt(bins[0].from, state.view === "all" || state.view === "365") }),
      el("span", { text: fmt(mid.from) }),
      el("span", { text: "today" })]));

    // selection line, or how to use it
    var line = el("div", { class: "cohort-tl-sel" });
    if (state.from !== null) {
      var clear = el("button", { type: "button", class: "linkbtn", text: "Clear" });
      clear.addEventListener("click", function () { C.clearPeriod(); });
      line.appendChild(el("span", {}, [el("b", { text: "Posted " + (state.from === state.to ? fmt(state.from, true) : fmt(state.from) + " – " + fmt(state.to, true)) }),
        ": " + plural(inPeriod, "role", "roles") + " shown" + (undated ? " (roles with no posting date are hidden)" : "") + ". "]));
      line.appendChild(clear);
    } else {
      line.appendChild(el("span", { class: "cohort-sub", text: "Drag across the bars, or click one, to show only roles posted in that period." +
        (older ? " " + plural(older, "role was", "roles were") + " posted before this range." : "") }));
    }
    box.appendChild(line);

    // when roles get posted, by weekday
    var wmax = Math.max.apply(null, byWeekday) || 1;
    box.appendChild(el("div", { class: "cohort-tl-week" }, [el("span", { class: "cohort-sub", text: "Posted on" })].concat(byWeekday.map(function (c, i) {
      return el("span", { class: "cohort-tl-wd", title: WEEKDAYS[i] + ": " + plural(c, "role", "roles") }, [
        el("span", { class: "cohort-tl-wdbar" }, [el("span", { style: "width:" + Math.round(100 * c / wmax) + "%" })]),
        el("span", { text: WEEKDAYS[i] })]);
    }))));

    brush(bars, bins);
  };

  function paintSelection(bars, bins, from, to) {
    if (from === undefined) { from = state.from; to = state.to; }
    Array.prototype.forEach.call(bars.children, function (bar, i) {
      var b = bins[i], on = from !== null && b.to >= from && b.from <= to;
      bar.classList.toggle("sel", on);
      bar.classList.toggle("dim", from !== null && !on);
    });
  }

  // drag to pick a period; a click picks one bar; clicking the only selected bar clears it
  function brush(bars, bins) {
    var anchor = null;
    function binAt(e) {
      var r = bars.getBoundingClientRect();
      return Math.max(0, Math.min(bins.length - 1, Math.floor((e.clientX - r.left) / r.width * bins.length)));
    }
    bars.addEventListener("pointerdown", function (e) {
      anchor = binAt(e);
      bars.setPointerCapture(e.pointerId);
      paintSelection(bars, bins, bins[anchor].from, bins[anchor].to);
      e.preventDefault();
    });
    bars.addEventListener("pointermove", function (e) {
      if (anchor === null) return;
      var i = binAt(e), lo = Math.min(anchor, i), hi = Math.max(anchor, i);
      paintSelection(bars, bins, bins[lo].from, bins[hi].to);
    });
    bars.addEventListener("pointerup", function (e) {
      if (anchor === null) return;
      var i = binAt(e), lo = Math.min(anchor, i), hi = Math.max(anchor, i);
      var from = bins[lo].from, to = bins[hi].to;
      anchor = null;
      if (lo === hi && state.from === from && state.to === to) { C.clearPeriod(); return; }
      state.from = from; state.to = to;
      changed();
    });
    bars.addEventListener("pointercancel", function () { anchor = null; paintSelection(bars, bins); });
  }
})();
