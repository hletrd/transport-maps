// Loaded before app.js, as a classic script, so it is installed before any
// module runs. Not inline: `script-src 'self'` accepts a file from this origin
// with no CSP hash to keep in step, and deploy/worldmap-security-headers.conf
// therefore needs no change.
//
// CLAUDE.md names this project's recurring failure: "a module-load ordering
// error that threw before the map was created -- with no console error visible
// after the fact", twice shipped, twice a blank live site. app.js has fatal()
// for the failures it anticipates; nothing at all caught the ones it did not.
// A vendor file that 404s, a syntax error in a module, a WebGL context lost
// mid-setup, or a promise that never settles all produced the same thing: an
// empty page and, by the time anyone looked, an empty console.
(function () {
  "use strict";
  var shown = false;

  function say(kind, detail) {
    // fatal() has already written a specific, better message; do not paint
    // over it with a generic one.
    if (shown || document.body.classList.contains("fatal")) return;
    shown = true;
    document.body.classList.add("fatal");
    var where = document.getElementById("where");
    var time = document.getElementById("time");
    if (time) time.textContent = "—";
    if (where) {
      where.textContent = "The page could not start (" + kind + ": "
        + String(detail || "no detail").slice(0, 160) + "). Reloading usually "
        + "clears it; if it does not, the browser may be blocking a file this "
        + "page needs.";
    }
  }

  window.addEventListener("error", function (e) {
    // Resource errors (a 404 on a <script> or a font) do not bubble as
    // ErrorEvent.error; they arrive with a target instead.
    if (e && e.target && e.target !== window && e.target.tagName) {
      say("a file did not load", e.target.src || e.target.href || e.target.tagName);
      return;
    }
    say("script error", e && (e.message || e.error));
  }, true);

  window.addEventListener("unhandledrejection", function (e) {
    var r = e && e.reason;
    say("unhandled error", r && (r.message || r));
  });

  // ...and the case with no error at all: everything resolved, nothing drew.
  // The city list is the test, not the canvas -- MapLibre creates a <canvas>
  // before it throws on a missing WebGL context, so "the canvas exists" is
  // true on a page that can never paint.
  window.addEventListener("load", function () {
    setTimeout(function () {
      if (document.body.classList.contains("fatal")) return;
      var cities = document.querySelectorAll(".results button[data-slug]").length;
      if (cities > 0) return;
      say("nothing finished loading",
          "no departure cities after 25 seconds and no error was reported");
    }, 25000);
  });
})();
