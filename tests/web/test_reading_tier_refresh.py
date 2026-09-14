"""When the finer array lands, everything that reads it must be redrawn.

`paintOrigin` fetches the coarse res-4 arrays first and the 10 MB res-6
reading array afterwards. The moment the finer one arrives, every number on the
page derived from `lookup()` changes -- the two tiers differ at 96.4% of land
points, median 26 min, 33% of them by an hour or more.

The arrival block redrew the headline, the itinerary, the city list, the
departure line and the zoom detail, and not the Route panel. So the panel's
"Time" row sat on the res-4 value while the "Door to door" line directly above
it showed res-6, and neither said why.

This is a structural test, not a substring one: it takes the set of renderers
the COARSE arrival runs and requires the FINE arrival to run them too. A new
renderer added to one and forgotten in the other fails here.
"""

from __future__ import annotations

import re

from transport_maps import config

APP = (config.ROOT / "web" / "app.js").read_text(encoding="utf-8")

#: Everything that turns a lookup() into something on screen.
RENDERERS = {"renderPins", "renderLegs", "renderDeparture", "render",
             "refreshScale", "rereadPointer"}


def _block(anchor: str, stop: str) -> str:
    start = APP.index(anchor)
    return APP[start:APP.index(stop, start)]


def test_the_finer_array_redraws_everything_the_coarse_one_does():
    """Mutation performed and reverted: delete `renderPins();` from the
    reading-tier arrival block -> red, naming renderPins.
    """
    fine = _block("// The zoom detail is sampled through lookup()",
                  "finer readings unavailable")
    # Walk backwards from the marker to the start of the .then() body.
    fine = APP[APP.index("if (pinB || lastPointer) rereadPointer();"):
               APP.index("finer readings unavailable")]
    called = {m for m in RENDERERS if re.search(rf"\b{m}\s*\(", fine)}

    settle = _block("  const settle = () => {", "\n  };")
    expected = {m for m in RENDERERS if re.search(rf"\b{m}\s*\(", settle)}
    assert expected, "the coarse settle() block was not found; the anchor moved"

    missing = expected - called
    assert not missing, (
        f"the finer array lands and {sorted(missing)} never run again, so "
        "those numbers stay on the res-4 value while the headline moves to "
        "res-6")


def test_the_route_panel_is_one_of_them():
    """Named explicitly, because it is the one that was missing and a future
    refactor of settle() must not quietly take it out of the comparison."""
    fine = APP[APP.index("if (pinB || lastPointer) rereadPointer();"):
               APP.index("finer readings unavailable")]
    assert re.search(r"\brenderPins\s*\(", fine), (
        "the Route panel's Time row is not redrawn when the finer array lands")
