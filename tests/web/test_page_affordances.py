"""What the page offers a visitor, and whether the offer is real.

Every assertion here comes from a cycle-6 finding measured on the live site by
the designer or the debugger, and each names the mutation that reddens it.
These are structural checks on `web/app.js` and `web/index.html`: app.js is a
2,600-line ES module needing MapLibre and a layout engine, so the measurements
themselves live in `scripts/browser_verify.sh`, which drives the deployed page.
"""

import re

from transport_maps import config

APP = (config.ROOT / "web" / "app.js").read_text(encoding="utf-8")
HTML = (config.ROOT / "web" / "index.html").read_text(encoding="utf-8")
CSS = re.sub(r"/\*.*?\*/", "", HTML, flags=re.S)


def test_every_css_variable_the_page_reads_is_one_it_defines():
    """`.reading .trouble` asked for `--text-1`, which has never existed.

    The declaration was inert and the colour fell through to the inherited
    `--text`, so the one message explaining a blank globe was painted in the
    body colour rather than the muted one it was designed in. `var()` fails
    silently by design, which is why nothing ever reported it -- so check the
    whole class rather than the one instance.

    Mutation performed and reverted: put `--text-1` back -> red.
    """
    defined = set(re.findall(r"(--[a-z0-9-]+)\s*:", CSS))
    # Some tokens are set at runtime rather than in the stylesheet, which is
    # still a definition -- `--ocean-now` is written by the scheme picker.
    defined |= set(re.findall(r'setProperty\(\s*"(--[a-z0-9-]+)"', APP))
    used = set(re.findall(r"var\(\s*(--[a-z0-9-]+)", CSS))
    used |= set(re.findall(r"var\(\s*(--[a-z0-9-]+)", APP))
    # A var() with a fallback still works when the token is missing.
    with_fallback = set(re.findall(r"var\(\s*(--[a-z0-9-]+)\s*,", CSS + APP))
    missing = sorted((used - defined) - with_fallback)
    assert not missing, f"the page reads CSS variables it never defines: {missing}"


def _media(query: str) -> str:
    i = CSS.index(query)
    depth, j = 0, CSS.index("{", i)
    k = j
    while True:
        if CSS[k] == "{":
            depth += 1
        elif CSS[k] == "}":
            depth -= 1
            if depth == 0:
                return CSS[j:k]
        k += 1


def test_the_itinerary_is_not_trapped_in_a_scroll_box_inside_a_scroll_box():
    """`.legs{max-height:20vh}` inside a `.rail` that already scrolls.

    Measured hidden below the fold: 99 px at 390x844 and 209 px -- seven of
    nine legs -- at 844x390, under a 94 %-opaque sticky total that reads as the
    end of the list, with an overlay scrollbar and no fade to say otherwise.

    Mutation performed and reverted: restore `max-height:20vh` -> red.
    """
    small = _media("@media (max-width:860px)")
    assert "overflow-y:auto" in small.split(".rail{")[1][:400], (
        "the small-layout rail no longer scrolls; re-derive this test")
    for block in re.findall(r"\.legs\{([^}]*)\}", small):
        assert "max-height:none" in block.replace(" ", ""), (
            f"the itinerary is capped inside a scrolling rail: {block!r}")


def test_the_route_panel_scrolls_itself_into_view_on_the_desktop():
    """The `noScroll` guard is a small-layout measure and was applied to both.

    At 1280x800 choosing a destination left "Clear" and "Copy link to this
    journey" at y 972-1000 with `rail.scrollTop` still 0: the two things a
    visitor does next were below the fold with no cue they existed.

    Mutation performed and reverted: drop `&& SMALL.matches` -> red.
    """
    m = re.search(r"function openRoutePanel\(\) \{(.*?)\n\}", APP, re.S)
    assert m, "openRoutePanel has moved; re-derive this test"
    body = re.sub(r"^\s*//.*$", "", m.group(1), flags=re.M)
    assert "SMALL.matches" in body, (
        "the route panel suppresses its scroll-into-view at every viewport")
    # ...and SMALL must be declared above its readers. U25 shipped a blank page
    # from a const read before its declaration; openRoutePanel is 700 lines
    # above where SMALL used to live.
    assert APP.index('const SMALL = window.matchMedia') < APP.index("function openRoutePanel")


def test_the_one_tab_stop_in_the_city_list_is_the_city_you_depart_from():
    """With 553 origins the single roving tab stop was row 1, "Aba".

    Focusing it also reset `scrollTop` from 11,418 to 0, undoing by keyboard
    the scroll that puts the current departure in view -- so a keyboard visitor
    arrived at the top of an alphabet with no sign which city the page was
    measuring from.

    Mutation performed and reverted: go back to `box.querySelector("button")`
    alone -> red.
    """
    m = re.search(r"const first = (.*?);\n\s*if \(first\) first\.tabIndex = 0;", APP, re.S)
    assert m, "the roving tabindex has moved; re-derive this test"
    assert 'aria-current="true"' in m.group(1), (
        "the tab stop is the first row again, not the current departure")


def test_every_outcome_of_the_locate_button_is_announced():
    """`#here` is a plain `<p>`: painting it is silent (WCAG 2.2 SC 4.1.3).

    The page keeps exactly one live region by policy (T4), so the fix routes
    through `announce()` rather than making `#here` a second one -- which is
    why `test_only_one_live_region_exists` must still pass alongside this.

    Mutation performed and reverted: drop the `announce(text)` call from
    `sayHere` -> red; write `$("here").textContent` directly again -> red.
    """
    m = re.search(r"function sayHere\(text\) \{(.*?)\n\}", APP, re.S)
    assert m, "sayHere has gone; the locate outcomes are silent again"
    assert "announce(text)" in m.group(1)
    # No MESSAGE may bypass it. Clearing the line is allowed to be direct --
    # announcing an empty string says nothing to anyone -- but every non-empty
    # outcome has to go through sayHere or it is silent. The one assignment
    # inside sayHere itself is the exception.
    bypass = [
        m.group(0).strip()
        for m in re.finditer(r'\$\("here"\)\.textContent\s*=(?!=)\s*([^;\n]*)', APP)
        if m.group(1).strip() not in ('""', "''", "text")
    ]
    assert bypass == [], (
        f"these writes to #here bypass sayHere and are therefore silent: {bypass}")


def test_the_globe_can_be_given_a_destination_from_the_keyboard():
    """`role="application"`, arrows turn it, +/- zoom it, and its own name says
    "click to set a destination" -- which is not something a keyboard visitor
    can do. The page's whole point was pointer-only on the map surface.

    Mutation performed and reverted: remove the keydown listener -> red.
    """
    m = re.search(r'\$\("map"\)\.addEventListener\("keydown", \(e\) => \{(.*?)\n\}\);',
                  APP, re.S)
    assert m, "the globe has no keydown handler; Enter does nothing again"
    body = m.group(1)
    assert '"Enter"' in body and "setDestination(" in body
    # It must refuse a centre that is off the globe, the same way a click does
    # (USER-6: unproject clamps past the silhouette and returns a real town).
    assert "onGlobe(" in body, (
        "the keyboard route can pin a clamped coordinate out of empty space")
    # ...and the accessible name has to say the key exists, or nobody finds it.
    assert re.search(r'aria-label="Interactive globe[^"]*Enter sets the destination',
                     HTML), "the globe's accessible name does not mention Enter"


def test_the_journey_line_on_the_globe_has_a_key():
    """`214297d` drew solid great-circle arcs and dashed ground legs and
    explained the distinction only in a code comment.

    Mutation performed and reverted: delete the `linekey` append -> red.
    """
    assert 'key.className = "linekey"' in APP
    assert re.search(r"\.legs \.linekey\{", CSS), "the key has no style"
    body = APP[APP.index('key.className = "linekey"'):]
    body = body[:body.index("frag.append(key)")]
    assert "solid" in body and "dashed" in body, (
        "the key no longer says which line is which")
