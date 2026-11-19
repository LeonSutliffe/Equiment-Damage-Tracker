// Equipment Damage Tracker: long-press history popup, photo previews, small helpers.
(function () {
  "use strict";
  var LONG_PRESS_MS = 500;
  var dialog = document.getElementById("history-dialog");
  var body = document.getElementById("history-body");

  function openHistory(url) {
    if (!dialog || !url) return;
    body.textContent = "Loading…";
    if (typeof dialog.showModal === "function") dialog.showModal(); else dialog.setAttribute("open", "");
    fetch(url, { credentials: "same-origin", headers: { "X-Requested-With": "fetch" } })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.text(); })
      .then(function (html) { body.innerHTML = html; })
      .catch(function () { body.textContent = "Couldn't load the history. Check your connection and try again."; });
  }

  // Close the dialog when tapping the backdrop.
  if (dialog) dialog.addEventListener("click", function (e) { if (e.target === dialog) dialog.close(); });

  function historyTarget(el) { return el && el.closest ? el.closest("[data-history]") : null; }

  // Long press (touch or mouse held ~0.5 s) on a field's label or box.
  var timer = null, startX = 0, startY = 0, fired = false;
  document.addEventListener("pointerdown", function (e) {
    var t = historyTarget(e.target);
    if (!t || e.button > 0 || e.target.closest("[data-history-open]")) return;
    fired = false; startX = e.clientX; startY = e.clientY;
    clearTimeout(timer);
    timer = setTimeout(function () {
      fired = true;
      if (navigator.vibrate) navigator.vibrate(20);
      openHistory(t.getAttribute("data-history"));
    }, LONG_PRESS_MS);
  });
  function cancel() { clearTimeout(timer); timer = null; }
  document.addEventListener("pointerup", cancel);
  document.addEventListener("pointercancel", cancel);
  document.addEventListener("pointermove", function (e) {
    if (timer && (Math.abs(e.clientX - startX) > 10 || Math.abs(e.clientY - startY) > 10)) cancel();
  });
  // Swallow the click that follows a long press, so it doesn't also change a radio button.
  document.addEventListener("click", function (e) {
    if (fired) { fired = false; if (historyTarget(e.target)) { e.preventDefault(); e.stopPropagation(); } }
  }, true);

  // Right-click on a PC (and the long-press context menu on phones).
  document.addEventListener("contextmenu", function (e) {
    var t = historyTarget(e.target);
    if (!t) return;
    e.preventDefault();
    if (!fired) openHistory(t.getAttribute("data-history"));
  });

  // The small clock icon next to each field.
  document.addEventListener("click", function (e) {
    var btn = e.target.closest && e.target.closest("[data-history-open]");
    if (!btn) return;
    e.preventDefault();
    var t = historyTarget(btn);
    if (t) openHistory(t.getAttribute("data-history"));
  });

  // Confirm before destructive buttons.
  document.addEventListener("click", function (e) {
    var btn = e.target.closest && e.target.closest("[data-confirm]");
    if (btn && !window.confirm(btn.getAttribute("data-confirm"))) e.preventDefault();
  });

  // Photos: "Take photo" opens the camera, "From gallery" the picker. Each time a
  // photo is chosen, that input is parked (so it is still sent on Save) and a fresh
  // one takes its place, so several photos can be taken one after another.
  document.querySelectorAll("[data-photo-picker]").forEach(function (picker) {
    var form = picker.closest("form");
    var store = form.querySelector("[data-photo-store]");
    var preview = form.querySelector("[data-photo-preview]");

    function render() {
      preview.innerHTML = "";
      var count = 0;
      store.querySelectorAll("input[type=file]").forEach(function (input) {
        Array.prototype.forEach.call(input.files, function (f) {
          count++;
          var fig = document.createElement("figure");
          fig.className = "pending";
          var img = document.createElement("img");
          img.src = URL.createObjectURL(f);
          img.alt = f.name;
          var drop = document.createElement("button");
          drop.type = "button";
          drop.className = "drop";
          drop.setAttribute("aria-label", "Don't add this photo");
          drop.textContent = "\u00d7";
          drop.addEventListener("click", function () { input.remove(); render(); });
          fig.appendChild(img);
          fig.appendChild(drop);
          preview.appendChild(fig);
        });
      });
      if (count) {
        var note = document.createElement("p");
        note.className = "muted small";
        note.textContent = count + (count === 1 ? " photo" : " photos") + " will be added when you save.";
        preview.appendChild(note);
      }
    }

    picker.addEventListener("change", function (e) {
      var input = e.target;
      if (input.type !== "file" || !input.files.length) return;
      var fresh = input.cloneNode();
      fresh.value = "";
      input.parentNode.insertBefore(fresh, input);
      input.removeAttribute("id");
      store.appendChild(input);
      render();
    });
  });

  // Whole table rows clickable.
  document.addEventListener("click", function (e) {
    var row = e.target.closest && e.target.closest("tr[data-href]");
    if (row && !e.target.closest("a,button,input,select")) window.location = row.getAttribute("data-href");
  });

  // Theme: Auto (follows the device) -> Light -> Dark, remembered on this device.
  var toggle = document.querySelector("[data-theme-toggle]");
  if (toggle) {
    var names = { "": "Auto", light: "Light", dark: "Dark" };
    var show = function () { toggle.textContent = "Theme: " + names[document.documentElement.dataset.theme || ""]; };
    show();
    toggle.addEventListener("click", function () {
      var order = ["", "light", "dark"];
      var next = order[(order.indexOf(document.documentElement.dataset.theme || "") + 1) % 3];
      if (next) document.documentElement.dataset.theme = next; else delete document.documentElement.dataset.theme;
      try { if (next) localStorage.setItem("theme", next); else localStorage.removeItem("theme"); } catch (e) {}
      show();
    });
  }

  // Prevent double submits (e.g. a slow photo upload tapped twice).
  document.addEventListener("submit", function (e) {
    var form = e.target;
    // Only POST forms: GET forms (e.g. report downloads) stay on the page and can be re-used.
    if ((form.getAttribute("method") || "get").toLowerCase() !== "post") return;
    if (form.dataset.submitting) { e.preventDefault(); return; }
    form.dataset.submitting = "1";
    form.querySelectorAll("button[type=submit]").forEach(function (b) { b.setAttribute("aria-busy", "true"); });
  });
  // Bulk actions: "select all" and a count of ticked tickets.
  document.querySelectorAll("[data-bulk]").forEach(function (bar) {
    var boxes = function () { return document.querySelectorAll('input[name="tickets"][form="bulk-form"]'); };
    var all = bar.querySelector("[data-bulk-all]");
    var count = bar.querySelector("[data-bulk-count]");
    function update() {
      var n = 0;
      boxes().forEach(function (b) { if (b.checked) n++; });
      count.textContent = n + " selected";
      all.checked = n > 0 && n === boxes().length;
    }
    all.addEventListener("change", function () {
      boxes().forEach(function (b) { b.checked = all.checked; });
      update();
    });
    document.addEventListener("change", function (e) {
      if (e.target.matches && e.target.matches('input[name="tickets"]')) update();
    });
    update();
  });
  // Reports: "Choose fields…" popup. The choice is remembered on this device.
  var fieldsDialog = document.getElementById("fields-dialog");
  if (fieldsDialog) {
    var boxes = fieldsDialog.querySelectorAll('input[name="fields"]');
    var summary = document.querySelector("[data-fields-summary]");
    var KEY = "reportFields";
    function showSummary() {
      var n = 0;
      boxes.forEach(function (b) { if (b.checked) n++; });
      summary.textContent = n === boxes.length ? "All fields included" : n + " of " + boxes.length + " fields included";
    }
    function save() {
      var chosen = [];
      boxes.forEach(function (b) { if (b.checked) chosen.push(b.value); });
      try { localStorage.setItem(KEY, JSON.stringify(chosen)); } catch (e) {}
    }
    // A fresh visit (not a submitted report) starts from the last choice.
    if (window.location.search.indexOf("fields_set=") === -1) {
      try {
        var saved = JSON.parse(localStorage.getItem(KEY) || "null");
        if (Array.isArray(saved) && saved.length) {
          boxes.forEach(function (b) { b.checked = saved.indexOf(b.value) !== -1; });
        }
      } catch (e) {}
    }
    showSummary();
    document.querySelector("[data-fields-open]").addEventListener("click", function () { fieldsDialog.showModal(); });
    fieldsDialog.querySelector("[data-fields-close]").addEventListener("click", function () { fieldsDialog.close(); });
    fieldsDialog.querySelector("[data-fields-all]").addEventListener("click", function () {
      boxes.forEach(function (b) { b.checked = true; }); save(); showSummary();
    });
    fieldsDialog.querySelector("[data-fields-none]").addEventListener("click", function () {
      boxes.forEach(function (b) { b.checked = false; }); save(); showSummary();
    });
    boxes.forEach(function (b) { b.addEventListener("change", function () { save(); showSummary(); }); });
  }

})();
