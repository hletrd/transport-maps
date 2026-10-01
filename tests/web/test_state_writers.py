"""Three places where one code path silently overwrote another's state.

None of these is a crash. Each is a thing on screen that the visitor put there
and the page removed without saying anything, which is the harder kind of defect
to notice and the easier kind to ship.

Every assertion below is made over the function's source with comments stripped
first -- the standing rule from cycle 6 is that an assertion a comment can
satisfy is vacuous, and all three fixes are explained by comments that name the
identifiers being asserted on.
"""

from __future__ import annotations

import re

from tests.web import _js
from transport_maps import config

APP = (config.ROOT / "web" / "app.js").read_text(encoding="utf-8")


def _body(opening: str) -> str:
    """The brace-balanced block that starts at `opening`, comments stripped."""
    return re.sub(r"//[^\n]*", "", _js.block(opening))


def test_rebuilding_the_city_list_does_not_delete_the_address_results() -> None:
    """searchAddress() PREPENDS <ul class="addresses"> to #results, and render()
    called replaceChildren on the same box. settle() renders once per origin, up
    to a second after a city is clicked, so a visitor reading their address
    results watched them vanish.

    The re-attach at the end of searchAddress() covers only the in-flight case:
    it runs when the fetch resolves, and does nothing for results already on
    screen.

    Mutation performed and reverted: delete the re-prepend from render() -> red.
    """
    body = _body("function render(filter = \"\")")
    assert "replaceChildren(list)" in body, "render no longer rebuilds the list"
    cut = body.index("replaceChildren(list)")
    before, after = body[:cut], body[cut:]
    assert '.addresses' in before, (
        "render() replaces #results' children without first capturing the "
        "address results that searchAddress() prepended there")
    assert "prepend(" in after, (
        "render() captures the address results and never puts them back")
    # ...and it must be able to tell whether they still answer the live query,
    # or a stale list would outlive the search that produced it.
    assert "dataset.q" in body, (
        "render() keeps the address results without checking they still answer "
        "what is in the search box")
    assert 'ul.dataset.q = q' in APP, (
        "searchAddress() does not record which query its results answer")


def test_a_shared_link_does_not_overwrite_a_destination_the_visitor_chose() -> None:
    """The permalink restore retries every 250 ms for ten seconds waiting for
    origin.times, and guarded on nothing else. A visitor who pinned their own
    destination in that window, or switched departure city, had the link's pin
    written over the top with nothing said.

    Mutation performed and reverted: drop the `originGen !== forGen || pinB`
    clause -> red.
    """
    body = _body("  const restore = () =>")
    assert "origin.times" in body, "the restore no longer waits for the arrays"
    assert "pinB" in body, (
        "the permalink restore does not check whether the visitor has already "
        "set a destination of their own")
    assert "originGen" in body, (
        "the permalink restore does not check the departure city is still the "
        "one the link named")
    # The guard must come FIRST; after commitDestination it would be useless.
    assert body.index("pinB") < body.index("commitDestination"), (
        "the restore commits the link's destination before checking whether "
        "the visitor already chose one")


def test_escape_dismisses_what_is_on_top_before_it_deletes_the_route() -> None:
    """WCAG 2.2 SC 1.4.13: content shown on hover or focus must be dismissible
    without moving the pointer or the focus. The .ap and .mode glosses appear on
    focus and had no dismissal at all.

    Meanwhile Escape deleted the pinned route from anywhere on the page:
    verified in a browser by focusing the "ICN" gloss, pressing Escape, and
    watching the route disappear with focus dumped to <body>.

    Mutation performed and reverted: restore
    `if (e.key === "Escape" && pinB && document.activeElement !== $("q")) clearRoute();`
    -> red on both assertions.
    """
    handler = _body('document.addEventListener("keydown", (e) => {\n  if (e.key !== "Escape")')
    assert "legtip" in handler and "tip" in handler, (
        "Escape does not dismiss the tooltips, which SC 1.4.13 requires of "
        "content shown on hover or focus")
    assert handler.index("legtip") < handler.index("clearRoute"), (
        "Escape deletes the route before dismissing the tooltip it should have "
        "dismissed, so the tooltip is never dismissible")
    assert "closest" in handler, (
        "Escape clears the route from anywhere on the page; it must be scoped "
        "to where a destination is actually set")
    assert "clearRoute" in handler
