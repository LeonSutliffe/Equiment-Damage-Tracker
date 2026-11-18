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

  // Preview photos chosen but not yet saved.
  document.querySelectorAll("input[type=file][multiple]").forEach(function (input) {
    var box = document.querySelector('[data-preview-for="' + input.id + '"]');
    if (!box) return;
    input.addEventListener("change", function () {
      box.innerHTML = "";
      Array.prototype.forEach.call(input.files, function (f) {
        if (!f.type || f.type.indexOf("image/") !== 0) return;
        var img = document.createElement("img");
        img.src = URL.createObjectURL(f);
        img.alt = f.name;
        box.appendChild(img);
      });
      if (input.files.length) {
        var note = document.createElement("p");
        note.className = "muted small";
        note.textContent = input.files.length + " photo(s) will be added when you save.";
        box.appendChild(note);
      }
    });
  });

  // Whole table rows clickable.
  document.addEventListener("click", function (e) {
    var row = e.target.closest && e.target.closest("tr[data-href]");
    if (row && !e.target.closest("a,button,input,select")) window.location = row.getAttribute("data-href");
  });

  // Prevent double submits (e.g. a slow photo upload tapped twice).
  document.addEventListener("submit", function (e) {
    var form = e.target;
    if (form.dataset.submitting) { e.preventDefault(); return; }
    form.dataset.submitting = "1";
    form.querySelectorAll("button[type=submit]").forEach(function (b) { b.setAttribute("aria-busy", "true"); });
  });
})();
