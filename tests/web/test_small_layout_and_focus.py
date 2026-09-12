"""Three defects a visitor hits before they have done anything at all.

All three were measured in a browser against the live site and all three are
about what is on screen, not about what the code contains -- so each assertion
below is written to fail on the real rule, with the mutation named.

1. The focus ring on the controls that float over the globe sat 1px OUTSIDE the
   button, i.e. on the band colour rather than on the control's own surface.
   Measured 1.00-1.08:1 against real pixels on the default Muted scheme; WCAG
   2.2 SC 1.4.11 and 2.4.11 want 3:1.
2. Folding the phone sheet took the travel time with it. #time and #where are
   direct children of .reading, and `.tip` is display:none at this width
   because "the sheet readout carries the value" -- so folded, nothing carried
   it. At 844x390 no travel time was visible anywhere, while #status (the live
   region) was deliberately kept alive: a screen-reader user was told the
   number and a sighted user was not.
3. layoutForSize() ran after `await map.on("load")`, so for the whole load the
   bottom sheet sat on top of "Loading the map...". Measured occluded from
   372 ms to 4,031 ms on a portrait phone.
"""

from __future__ import annotations

import re

from transport_maps import config

HTML = (config.ROOT / "web" / "index.html").read_text(encoding="utf-8")
APP = (config.ROOT / "web" / "app.js").read_text(encoding="utf-8")

#: The <style> block with its comments removed. Cycle 6's standing rule: an
#: assertion over source text that a comment can satisfy is vacuous, and every
#: rule below is explained by a comment that quotes the selector it explains.
CSS = re.sub(r"/\*.*?\*/", " ",
             HTML[HTML.index("<style>"): HTML.index("</style>")], flags=re.S)

#: Controls that float over the globe. A focus ring drawn outside these lands
#: on whatever band colour happens to be beneath, which is not a contrast the
#: page controls.
OVER_THE_MAP = (".mapbtn", "#q")


def _rule(selector: str) -> str:
    m = re.search(re.escape(selector) + r":focus-visible\{([^}]*)\}", CSS)
    assert m, f"{selector}:focus-visible no longer has a rule of its own"
    return m.group(1)


def test_a_focus_ring_over_the_globe_is_drawn_inside_its_control() -> None:
    """Mutation performed and reverted: `outline-offset:1px` on .mapbtn -> red."""
    for sel in OVER_THE_MAP:
        body = _rule(sel)
        off = re.search(r"outline-offset:\s*(-?[\d.]+)px", body)
        assert off, f"{sel}:focus-visible sets no outline-offset: {body!r}"
        assert float(off.group(1)) <= 0, (
            f"{sel}:focus-visible draws its ring {off.group(1)}px outside the "
            "control, i.e. on the band colour behind it. Measured 1.00-1.08:1 "
            "there against the 3:1 WCAG 2.2 asks for. Use a negative offset, as "
            ".results button does (7.11:1).")
        assert "outline:" in body, f"{sel}:focus-visible sets an offset but no outline"


def test_the_folded_sheet_keeps_the_travel_time() -> None:
    """Mutation performed and reverted: drop `:not(#time)` from the fold rule
    -> red, which is the state the live site shipped in."""
    hide = [ln for ln in CSS.splitlines()
            if ".rail.folded .reading >" in ln and ":not(" in ln]
    assert hide, "the folded sheet's hide rule is gone; re-read this guard"
    for line in hide:
        assert "#time" in line, (
            "the folded phone sheet hides #time, so no travel time is visible "
            "anywhere at 844x390 while the screen-reader live region still "
            f"announces one: {line.strip()}")


def test_the_travel_time_survives_every_rule_that_hides_a_reading_child() -> None:
    """The fold rule is not the only one that could take it. Any rule inside the
    small-screen block that hides direct children of .reading must spare #time.
    """
    small = CSS[CSS.index("@media (max-width:860px)"):]
    for m in re.finditer(r"([^{}]*\.reading\s*>[^{}]*)\{([^}]*)\}", small):
        selector, body = m.group(1).strip(), m.group(2)
        if "display:none" not in body.replace(" ", ""):
            continue
        assert "#time" in selector, (
            f"{selector} hides every direct child of .reading it matches, "
            "#time included, and nothing else on a phone shows the number "
            "(.tip is display:none at this width)")


def test_the_small_layout_is_decided_before_the_globe_is_waited_for() -> None:
    """layoutForSize() is what moves .reading into the rail and makes the rail a
    bottom sheet. Until it runs the small layout is not in place, and the sheet
    covers the one sentence that explains a blank globe.

    Mutation performed and reverted: move the call back below the await -> red.
    """
    call = APP.index("\nlayoutForSize();")
    await_at = APP.index("\nawait Promise.race([")
    assert call < await_at, (
        "layoutForSize() is called after the globe's load await, so the bottom "
        "sheet sits on top of 'Loading the map...' for the whole load "
        "(measured occluded 372 ms to 4,031 ms on a portrait phone)")
    # ...and the message it must not cover is the one that is on screen then.
    assert 'id="time"' in HTML and "Loading the map" in HTML
