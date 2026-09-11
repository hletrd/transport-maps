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
    // NOT an em dash: that is the 50px piece of punctuation the empty state
    // was built to get rid of, and writing it here wiped a correct reading.
    // The message goes in #where; this only clears a stale figure.
    if (time) time.textContent = "";
    if (where) {
      where.textContent = "The page could not start (" + kind + ": "
        + String(detail || "no detail").slice(0, 160) + "). Reloading usually "
        + "clears it; if it does not, the browser may be blocking a file this "
        + "page needs.";
    }
  }

  // A capturing listener on window receives `error` from EVERY element whose
  // subresource fails -- which is exactly how ad-block detectors are built.
  // This page loads one cross-origin subresource, the analytics tag, and it is
  // blocked for a large and ordinary population: ad-blocker extensions,
  // Pi-hole and NextDNS households, corporate resolvers, and everyone behind
  // the Great Firewall. Treating that as "the page could not start" set
  // body.fatal, and index.html's `body.fatal .rail{display:none}` then deleted
  // the city list, the search box, Settings and the sources panel from a page
  // whose globe was drawing perfectly -- and latched `shown`, so the real
  // 25-second watchdog could never fire afterwards.
  //
  // The guard exists for THIS origin's files: app.js, boot.js, the vendored
  // bundles, the fonts. Nothing third-party is load-bearing.
  function ourOwn(url) {
    if (!url) return true;              // no URL to judge: assume it is ours
    try {
      return new URL(url, location.href).origin === location.origin;
    } catch (err) {
      return true;                      // unparseable: fail towards reporting
    }
  }

  window.addEventListener("error", function (e) {
    // Resource errors (a 404 on a <script> or a font) do not bubble as
    // ErrorEvent.error; they arrive with a target instead.
    if (e && e.target && e.target !== window && e.target.tagName) {
      var url = e.target.src || e.target.href || "";
      if (!ourOwn(url)) return;
      say("a file did not load", url || e.target.tagName);
      return;
    }
    say("script error", e && (e.message || e.error));
  }, true);

  window.addEventListener("unhandledrejection", function (e) {
    var r = e && e.reason;
    say("unhandled error", r && (r.message || r));
  });

  // ...and the case with no error at all: everything resolved, nothing drew.
  //
  // The test is a flag app.js sets as its last statement, NOT the canvas and
  // NOT the city list. The canvas is wrong because MapLibre creates one before
  // it throws on a missing WebGL context. The city list is wrong because it is
  // search-filtered: typing an airport code empties it, and this page invites
  // exactly that, so the watchdog fired on healthy pages and replaced a correct
  // reading with "The page could not start". Shipped, seen live, fixed here.
  window.addEventListener("load", function () {
    setTimeout(function () {
      if (document.body.classList.contains("fatal")) return;
      if (document.documentElement.dataset.appReady === "1") return;
      say("nothing finished loading",
          "the page did not finish starting within 25 seconds and reported no error");
    }, 25000);
  });
})();
