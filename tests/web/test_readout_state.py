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


# --- cycle 7 -----------------------------------------------------------------
def test_the_failure_notice_is_not_cleared_by_a_pointer_move_onto_land():
    """`showReading` must separate `null` (open water) from `undefined` (times
    missing or failed).

    `if (t == null) clearTime()` caught both, so the first pointer move onto
    land after a failed origin fetch replaced "Travel times unavailable." with
    the idle prompt inviting the visitor to point at a globe that has no
    numbers. The headline then disagreed with #where, #status and the
    departure card, all three of which were correct.

    Mutation performed and reverted: `t === null` -> `t == null`, and delete
    the `else if (t === undefined)` branch -> red on both.
    """
    body = CODE[CODE.index("function showReading("):]
    body = body[:body.index("\n}")]
    assert "t === null" in body, "showReading uses loose equality for open water again"
    assert re.search(r"t\s*==\s*null", body) is None, (
        "showReading compares the reading against null loosely; undefined takes that branch too")
    assert "t === undefined" in body and "Travel times unavailable" in body, (
        "showReading no longer keeps the failure notice standing for a land cell "
        "whose times are missing")


def test_the_city_list_is_rebuilt_when_an_origin_fetch_fails():
    """The failure path must clear `listTimesFor` and re-render.

    `settle()` rebuilds the 553-row list only when `origin.times` arrives, so
    on the failure path it never rebuilt: the list kept the PREVIOUS city's
    times under the new city's caption, showed the new departure as a
    destination with a travel time to the city you are departing from, and
    left the old departure marked "departing".

    Mutation performed and reverted: delete `listTimesFor = null` from the
    catch block -> red.
    """
    catch = CODE[CODE.index('console.error("hover data unavailable:"'):]
    catch = catch[:catch.index("\n    });")]
    assert "listTimesFor = null" in catch, (
        "the origin-failure path does not reset the city list's stamp, so the list "
        "keeps the previous city's times")
    assert re.search(r"render\(\$\(\"q\"\)\.value\)", catch), (
        "the origin-failure path resets the stamp but never re-renders the list")


def test_the_departure_card_returns_to_its_column_not_to_the_body():
    """Crossing the small/wide breakpoint UPWARD must put `.depart-card` back
    into `.topleft`.

    `.depart-card` has no `position` of its own: it is a flex child of the
    fixed column that also holds the masthead. `document.body.insertBefore`
    dropped it to the document origin as a static block, 269 x 96 px of it
    under the masthead, with the h1 winning `elementFromPoint` over the
    departure city's own button. Any tablet rotated portrait to landscape
    reaches it, and two of the four viewports CLAUDE.md's deploy rule names
    sit on opposite sides of the breakpoint.

    Mutation performed and reverted: `topleft.append(card)` ->
    `document.body.insertBefore(card, reading)` -> red.
    """
    body = CODE[CODE.index("function layoutForSize("):]
    body = body[:body.index("\n}")]
    # The small-screen branch legitimately does rail.insertBefore(card, ...);
    # it is only <body> that has no column for the card to sit in.
    assert re.search(r"body\.insertBefore\(\s*card", body) is None, (
        "layoutForSize still moves the departure card into <body>, where it has no "
        "position of its own and falls to (0,0) under the masthead")
    assert "topleft" in body and re.search(r"topleft\.append\(card\)", body), (
        "layoutForSize does not return the departure card to the .topleft column")


def test_both_colour_pickers_are_keyboard_operable():
    """The ocean picker had a click listener and nothing else.

    Only the checked radio is a tab stop, so with no arrow handling five of
    the six ocean colours could not be reached by keyboard at all -- WCAG
    2.1.1, Level A. The ramp picker answered ArrowDown and ArrowUp only.

    Mutation performed and reverted: drop the `rovingRadios($("oceans"), ...)`
    call -> red; remove ArrowLeft/ArrowRight from the handler -> red.
    """
    assert re.search(r'rovingRadios\(\$\("ramps"\)', CODE), "the ramp picker lost its arrow keys"
    assert re.search(r'rovingRadios\(\$\("oceans"\)', CODE), (
        "the ocean picker has no arrow-key handler, so five of its six colours are "
        "unreachable by keyboard")
    handler = CODE[CODE.index("function rovingRadios("):]
    handler = handler[:handler.index("\n}")]
    for key in ("ArrowDown", "ArrowUp", "ArrowLeft", "ArrowRight", "Home", "End"):
        assert key in handler, f"the radio groups do not answer {key}"


def test_the_page_says_when_the_number_came_from_a_coarser_cell_than_the_ring():
    """The method panel states "the outlined hexagon under the pointer is the
    cell the time is read from". That is only true once the reading tier has
    landed, so the reading line must qualify it in every other case -- the
    tier still in flight, absent from this build, or declined under
    Save-Data.

    The comparison is against SOLVE_RES, which the ring is drawn at and which
    every index.json carries, NOT against READING_RES, which is null on a
    build made before the tier existed. Gated on READING_RES the qualifier
    never appeared against the live data and the method panel's sentence
    stood unqualified.

    Mutation performed and reverted: compare against READING_RES -> red.
    """
    body = CODE[CODE.index("function showReading("):]
    body = body[:body.index("\n}")]
    assert "readingGrid() !== SOLVE_RES" in body, (
        "the reading line does not compare the grid it read against the grid the ring "
        "is drawn at, so it cannot say when the two differ")
    assert "wider cell than the outline" in body
    html = (config.ROOT / "web" / "index.html").read_text(encoding="utf-8")
    flat = " ".join(html.split())
    assert "the cell the time is read from" in flat, (
        "the method panel no longer says where the number is read; this guard exists to "
        "keep that sentence and its qualifier in step")
