"""The headline number must not outlive the thing it was measuring.

Both defects below produced a correct, confidently-worded figure for the wrong
question -- the failure class CLAUDE.md's deploy rule and this repository's own
USER-5..USER-8 write-up single out as worse than an obvious error, because
nothing in the console says anything at all.

These are structural assertions on app.js. It is a 2,600-line ES module that
needs MapLibre and a layout engine, so there is no harness that can run it the
way test_boot_behaviour.py runs boot.js; what is pinned here is the invariant
that would otherwise drift, with the mutation named on each test.
"""

import re

from transport_maps import config

APP = (config.ROOT / "web" / "app.js").read_text(encoding="utf-8")

#: app.js with line comments stripped, so prose that merely describes an
#: assignment cannot satisfy an assertion about the assignment.
CODE = re.sub(r"^\s*//.*$", "", APP, flags=re.M)


def test_clearing_the_pin_also_drops_the_pointer_it_froze():
    """Every site that clears `pinB` must clear `lastPointer` with it.

    `lastPointer` is written only inside `showReading`, and the hover branch
    takes `lookup()` instead while a destination is pinned -- so it freezes at
    the pin and stops following the mouse. Neither site that clears a pin reset
    it, so `settle()` -> `rereadPointer()` resurrected the dismissed location as
    a live headline reading for the newly chosen city. The "Depart from X"
    handler clears the pin and switches origin in one synchronous click, so no
    mouse move can intervene, and on touch nothing overwrites it afterwards.

    Mutation performed and reverted: drop `lastPointer = null` from either the
    `clearRoute()` assignment or the "Depart from" handler -> red.
    """
    # `let pinB = null` is the declaration, not a clearing site.
    sites = [m for m in re.finditer(r"(?<!let )pinB\s*=\s*null", CODE)]
    assert len(sites) >= 2, "the pin-clearing sites have moved; re-derive this test"
    for m in sites:
        # The whole statement: from the start of the line to the end of the
        # next one, which is where a paired assignment can legitimately sit.
        start = CODE.rfind("\n", 0, m.start()) + 1
        end = CODE.find("\n", CODE.find("\n", m.end()) + 1)
        window = CODE[start:end]
        assert "lastPointer = null" in window, (
            f"pinB is cleared without clearing lastPointer: {window.strip()!r}")


def test_the_failure_path_stops_saying_it_is_still_reading():
    """The catch that marks an origin failed must clear the headline too.

    `paintOrigin` puts "Reading the travel times from Nairobi…" into `#time`.
    On a `{slug}.bin` failure it was never taken out, so the page showed that
    string in 50 px directly above `#where`'s "Times unavailable for Nairobi"
    -- while `#status` and the departure card were both already correct.

    Mutation performed and reverted: delete the `clearTime(...)` call from the
    catch block -> red.
    """
    m = re.search(r"origin\.failed = err\.message;.*?\n    \}\);", CODE, re.S)
    assert m, "the origin-failure catch block has moved; re-derive this test"
    assert re.search(r"clearTime\(", m.group(0)), (
        "the failure path leaves #time claiming it is still reading")
