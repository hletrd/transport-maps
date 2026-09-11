"""Run web/boot.js and check what it DOES, not what it contains.

`tests/web/test_app_constants.py` pins boot.js with three `substring in BOOT`
checks. That is the vacuity CLAUDE.md warns about: changing `cities > 0` to
`cities >= 0` -- one character -- leaves the watchdog permanently inert and
every one of those assertions still green.

boot.js is a 62-line classic-script IIFE with no imports and no awaits, so it
runs unchanged under a small DOM shim in Node. Each test below drives the real
listeners boot.js installs and asserts on the class it does or does not put on
<body>, which is the only thing that matters: `index.html` turns `body.fatal`
into `display:none` over the entire side rail.

The mutations each test is written against are named in its docstring, and each
was performed and reverted before this file was committed.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BOOT = ROOT / "web" / "boot.js"

#: A DOM small enough to be obviously correct and large enough to run boot.js.
#: Nothing here is a mock of boot.js: it is a mock of the browser, and every
#: assertion is on boot.js's own observable effect.
HARNESS = r"""
const fs = require("fs");
const src = fs.readFileSync(process.argv[2], "utf8");
const opts = JSON.parse(process.argv[3]);

const listeners = Object.create(null);
const classes = new Set();
const elements = Object.create(null);
const timers = [];

const element = (id) => (elements[id] ||= { id, textContent: "" });

const warnings = [];
const window = {
  addEventListener(type, fn) { (listeners[type] ||= []).push(fn); },
  // boot.js sends an unattributable rejection here instead of condemning the
  // page. Capture it, so a test can assert it was reported rather than eaten.
  console: { warn: (...a) => warnings.push(a.map(String).join(" ")) },
};
const document = {
  body: {
    classList: {
      contains: (c) => classes.has(c),
      add: (c) => classes.add(c),
    },
  },
  getElementById: element,
  // The watchdog reads a flag app.js sets as its last statement. It used to
  // count departure-city buttons, which is the SEARCH-FILTERED list -- typing
  // an airport code emptied it and the watchdog called a healthy page dead.
  // `opts.ready` is whether app.js finished starting.
  documentElement: { dataset: opts.ready ? { appReady: "1" } : {} },
  // Still provided, so a watchdog that goes back to counting rows is running
  // against a list that is EMPTY on a page that started fine -- which is the
  // bug, and the test below would then fail as it should.
  querySelectorAll: () => new Array(opts.cities || 0).fill({}),
};
const location = { href: opts.href, origin: new URL(opts.href).origin };
const setTimeout = (fn, ms) => timers.push({ fn, ms }) - 1;

// boot.js reads these as globals; hand them in as parameters instead of
// polluting Node's own.
new Function("window", "document", "location", "setTimeout", "URL", src)(
  window, document, location, setTimeout, URL);

const fire = (type, event) => (listeners[type] || []).forEach((fn) => fn(event));

for (const step of opts.steps) {
  if (step.kind === "resourceError") {
    fire("error", { target: { tagName: step.tagName || "SCRIPT", src: step.src } });
  } else if (step.kind === "scriptError") {
    fire("error", { target: window, message: step.message });
  } else if (step.kind === "rejection") {
    // A real PromiseRejectionEvent's reason is usually an Error, whose stack
    // names the script that raised it. That stack is the only attribution
    // boot.js has -- the event carries no URL the way a resource error does.
    var reason = { message: step.message };
    if (step.stack !== undefined) reason.stack = step.stack;
    fire("unhandledrejection", { reason: reason });
  } else if (step.kind === "settle") {
    // The page finishes loading, then the watchdog's timer comes due.
    fire("load", {});
    timers.filter((t) => t.ms >= 20000).forEach((t) => t.fn());
  } else {
    throw new Error("unknown step " + step.kind);
  }
}

process.stdout.write(JSON.stringify({
  fatal: classes.has("fatal"),
  where: (elements.where || {}).textContent || "",
  time: (elements.time || {}).textContent || "",
  watchdogArmed: timers.some((t) => t.ms >= 20000),
  warnings: warnings,
}));
"""

SITE = "https://worldmap.atik.kr/"


@pytest.fixture(scope="module")
def harness(tmp_path_factory: pytest.TempPathFactory) -> Path:
    if shutil.which("node") is None:
        pytest.skip("node is not on PATH; boot.js cannot be executed")
    path = tmp_path_factory.mktemp("boot") / "harness.cjs"
    path.write_text(HARNESS, encoding="utf-8")
    return path


def run_boot(harness: Path, *steps: dict, ready: bool = False, cities: int = 0,
             href: str = SITE) -> dict:
    opts = {"ready": ready, "cities": cities, "href": href, "steps": list(steps)}
    out = subprocess.run(
        ["node", str(harness), str(BOOT), json.dumps(opts)],
        capture_output=True, text=True, check=True, cwd=ROOT)
    return json.loads(out.stdout)


GTAG = "https://www.googletagmanager.com/gtag/js?id=G-2NYW09JSK2"


def test_a_blocked_analytics_tag_does_not_declare_the_page_dead(harness: Path) -> None:
    """The cycle-5 defect three reviewers found independently.

    The page loads exactly one cross-origin subresource, and it is blocked for
    ad-blocker users, Pi-hole households, corporate resolvers and everyone
    behind the Great Firewall. `body.fatal` hides the whole side rail.

    Mutation: delete the `ourOwn(url)` test from boot.js's resource branch.
    """
    seen = run_boot(harness, {"kind": "resourceError", "src": GTAG}, ready=True)
    assert not seen["fatal"], (
        "a blocked third-party analytics tag set body.fatal, which hides the "
        "departure list, the search box, Settings and the sources panel")
    assert seen["where"] == "", "and it wrote a failure message over the map's readout"


def test_a_missing_file_from_this_origin_still_declares_the_page_dead(harness: Path) -> None:
    """The guard must keep doing the job it was added for.

    Mutation: make `ourOwn` return false unconditionally.
    """
    seen = run_boot(harness, {"kind": "resourceError", "src": SITE + "app.js"}, ready=False)
    assert seen["fatal"], "a 404 on this origin's own app.js must still be reported"
    assert "app.js" in seen["where"], "the message must name the file that failed"


def test_a_relative_url_counts_as_ours(harness: Path) -> None:
    """`src="./vendor/maplibre-gl.js"` resolves against location, not against
    nothing. Mutation: compare the raw string to location.origin.
    """
    seen = run_boot(harness, {"kind": "resourceError", "src": "./vendor/maplibre-gl.js"})
    assert seen["fatal"], "a relative vendor path is this origin's file"


def test_an_unparseable_url_fails_towards_reporting(harness: Path) -> None:
    """Better a false alarm than a silent blank page -- that is the whole point
    of boot.js. Mutation: return false from `ourOwn`'s catch.
    """
    seen = run_boot(harness, {"kind": "resourceError", "src": "http://[", "tagName": "LINK"})
    assert seen["fatal"], "an unparseable URL must be reported, not swallowed"


def test_the_blocked_tag_does_not_latch_the_watchdog_shut(harness: Path) -> None:
    """`say()` sets `shown = true`, so a spurious third-party report used to
    disarm the genuine 25-second watchdog for the rest of the session. This is
    the second half of the same defect and it needs its own assertion.

    Mutation: delete the `ourOwn(url)` test.
    """
    seen = run_boot(harness,
                    {"kind": "resourceError", "src": GTAG},
                    {"kind": "settle"},
                    ready=False)
    assert seen["fatal"], (
        "after a blocked analytics tag, the real 'nothing drew' watchdog never fired")
    assert "did not finish starting" in seen["where"]


def test_the_watchdog_fires_when_nothing_drew(harness: Path) -> None:
    """CLAUDE.md's named recurring failure: everything resolves, nothing paints.

    Mutation: make the appReady check unconditional (`return;`). The
    substring assertions in test_app_constants.py stay green while the
    watchdog is permanently inert.
    """
    seen = run_boot(harness, {"kind": "settle"}, ready=False)
    assert seen["watchdogArmed"], "no 25-second timer was ever scheduled"
    assert seen["fatal"], "a page that never finished starting went unreported"
    # NOT an em dash: that is the 50px piece of punctuation the empty state
    # exists to avoid, and writing it here overwrote a correct reading.
    assert seen["time"] == ""


def test_the_watchdog_stays_quiet_when_the_page_worked(harness: Path) -> None:
    """The other half of the same mutation: `cities >= 0` would make this fail
    too, which is what makes the pair non-vacuous in both directions.
    """
    seen = run_boot(harness, {"kind": "settle"}, ready=True, cities=553)
    assert not seen["fatal"], "a page that finished starting was called dead"


def test_a_script_error_and_our_own_rejection_are_both_reported(harness: Path) -> None:
    """Mutation: remove either listener."""
    err = run_boot(harness, {"kind": "scriptError", "message": "x is not defined"})
    assert err["fatal"] and "x is not defined" in err["where"]

    rej = run_boot(harness, {"kind": "rejection", "message": "fetch failed",
                             "stack": f"TypeError: fetch failed\n    at settle ({SITE}app.js:1166:9)"})
    assert rej["fatal"] and "fetch failed" in rej["where"]


def test_a_blocked_analytics_beacon_does_not_declare_the_page_dead(harness: Path) -> None:
    """The other half of the defect `f968217` fixed, down the other listener.

    That commit stopped a BLOCKED SCRIPT LOAD from setting body.fatal. It did
    nothing about a blocked fetch: gtag.js loads fine and then POSTs to its
    collection endpoint, and extensions, Pi-hole and corporate resolvers
    commonly intercept there rather than at the script load. The result is an
    unhandled "TypeError: Failed to fetch" whose stack names googletagmanager,
    not this origin -- and `index.html`'s `body.fatal .rail{display:none}` then
    deleted the city list, the search box, Settings and the sources panel from
    a page whose globe was drawing perfectly.

    Mutation performed and reverted: drop the `ourRejection` guard and call
    `say()` unconditionally -> this test goes red and the two below stay green,
    which is what makes the set non-vacuous in both directions.
    """
    seen = run_boot(harness, {
        "kind": "rejection", "message": "Failed to fetch",
        "stack": ("TypeError: Failed to fetch\n"
                  "    at https://www.googletagmanager.com/gtag/js?id=G-2NYW09JSK2:212:319"),
    }, ready=True)
    assert not seen["fatal"], (
        "a blocked analytics beacon declared a working page dead")
    assert seen["where"] == "", "it wrote the failure notice anyway"
    assert any("Failed to fetch" in w for w in seen["warnings"]), (
        "the rejection was swallowed entirely; it must still reach the console")


def test_a_rejection_with_no_stack_is_not_fatal_but_the_watchdog_still_arms(
        harness: Path) -> None:
    """A rejection that cannot be attributed must not condemn the page.

    A bare rejected string, or a cross-origin opaque failure, carries no stack.
    Guessing "ours" there is what hid the side rail; guessing "theirs" costs
    nothing, because if the page really did die then `appReady` is never set
    and the 25-second watchdog reports it anyway. That backstop is the reason
    this direction is safe, so assert it is still armed.
    """
    seen = run_boot(harness, {"kind": "rejection", "message": "nope"},
                    {"kind": "settle"}, ready=False)
    assert seen["fatal"], "the watchdog did not catch a page that never started"
    assert "nothing finished loading" in seen["where"], (
        "the rejection was reported as the cause when it could not be attributed")


def test_only_the_first_report_is_shown(harness: Path) -> None:
    """A generic message must not paint over a specific one.

    Mutation: remove the `shown` guard from `say()`.
    """
    seen = run_boot(harness,
                    {"kind": "resourceError", "src": SITE + "app.js"},
                    {"kind": "scriptError", "message": "secondary"})
    assert "app.js" in seen["where"] and "secondary" not in seen["where"]


def test_a_filtered_city_list_does_not_declare_a_working_page_dead(harness: Path) -> None:
    """The defect this watchdog shipped with, found on the live site.

    It counted `.results button[data-slug]`, which is the SEARCH-FILTERED
    departure list. Typing an airport code -- which the page invites, and which
    matches no city -- empties it, so twenty-five seconds later the watchdog
    declared a perfectly healthy page broken: it wiped a correct reading and
    wrote "The page could not start" over the readout, while the itinerary
    below it still listed ICN to JFK.

    Reproduced live with a MutationObserver on #time: the writes were
    "17 h 17 min" and then an em dash.

    Mutation: point the watchdog back at querySelectorAll -- this test goes red
    while every other test in this file stays green, which is what makes the
    pair meaningful.
    """
    seen = run_boot(harness, {"kind": "settle"}, ready=True, cities=0)
    assert not seen["fatal"], (
        "a page that started fine was called dead because the visitor had "
        "typed a search that matches no departure city")
    assert seen["where"] == "", "and it wrote a failure message over the readout"
    assert seen["time"] == "", "and it overwrote the reading"
