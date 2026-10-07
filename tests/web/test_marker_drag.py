"""Dragging the departure must not be allowed to lie.

The destination may be any point on Earth. The departure may not: only the
cities in index.json have a precomputed surface, and every figure on the page
-- the headline, the itinerary, the Route panel's Time row, the band under the
cursor -- is measured from it. So a departure dropped on an uncharted point has
exactly two honest outcomes, and "show a number for where it was dropped" is
not one of them.

The rules this file holds:

1. The nearest charted city is found with NO distance limit. `originNear`, the
   function an implementer reaches for first, returns null past 80 km -- which
   would make most drags do nothing and say nothing.
2. The marker ends on the city, not on the dropped point. A marker left where
   it was dropped is the lie, whatever the text beside it says.
3. The page says the substitution happened, names the city, and gives the
   distance.
4. The notice belongs to one drag: any other route to a new departure clears
   it.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess

import pytest

from tests.web import _js
from transport_maps import config

APP = (config.ROOT / "web" / "app.js").read_text(encoding="utf-8")
HTML = (config.ROOT / "web" / "index.html").read_text(encoding="utf-8")


def _function(name: str) -> str:
    """The verbatim source of a top-level function.

    This file found C12-10: the old per-file slicers took `APP.index("{",
    start)` as the body brace, which for a DESTRUCTURED PARAMETER --
    `paintOrigin(o, { keepZoom = false } = {})` -- is the parameter's, so the
    slice was the signature alone and an `assert "x" in body` over it passed
    for nothing. `_js.function` walks the parameter list to its close first;
    the test below keeps it honest on the one real function with that shape.
    """
    return _js.function(name)


def test_the_slicer_reaches_the_body_and_not_just_the_signature():
    """The guard on the guard: paintOrigin has a destructured parameter, and
    a naive matcher stops at its closing brace.
    """
    body = _function("paintOrigin")
    assert "keepZoom" in body and "originGen" in body, (
        "paintOrigin was sliced to its signature; every assertion over it "
        "would pass vacuously")
    assert len(body) > 500


@pytest.fixture(scope="module")
def node() -> str:
    exe = shutil.which("node")
    if exe is None:
        pytest.skip("node is not on PATH")
    return exe


# Four real charted cities, from data/origins.toml.
CITIES = [
    {"slug": "seoul", "name": "Seoul", "lat": 37.5665, "lon": 126.978},
    {"slug": "tokyo", "name": "Tokyo", "lat": 35.6762, "lon": 139.6503},
    {"slug": "reykjavik", "name": "Reykjavik", "lat": 64.1466, "lon": -21.9426},
    {"slug": "honolulu", "name": "Honolulu", "lat": 21.3069, "lon": -157.8583},
]


@pytest.fixture(scope="module")
def run(node: str, tmp_path_factory):
    src = (_function("haversineKm") + "\n" + _function("nearestOrigin") + "\n"
           + _function("fmtKm") + "\n"
           + f"const meta = {{ origins: {json.dumps(CITIES)} }};\n")
    path = tmp_path_factory.mktemp("drag") / "drag.cjs"
    path.write_text(
        src + "const [fn, args] = JSON.parse(process.argv[2]);\n"
        "process.stdout.write(JSON.stringify(({nearestOrigin, fmtKm, haversineKm})"
        "[fn](...args)));\n", encoding="utf-8")

    def call(fn, *args):
        done = subprocess.run([node, str(path), json.dumps([fn, list(args)])],
                              capture_output=True, text=True, check=True)
        return json.loads(done.stdout)
    return call


def test_the_nearest_city_is_found_with_no_distance_limit(run):
    """Mid-Pacific, thousands of km from anywhere. `originNear`'s 80 km cap
    would return null here and the drag would silently do nothing.

    Mutation performed and reverted: give nearestOrigin `bestKm = 80` instead
    of `Infinity` -> red, returns null.
    """
    got = run("nearestOrigin", 10.0, -170.0)
    assert got is not None, "a drag into open ocean found no departure city"
    assert got["origin"]["slug"] == "honolulu"
    assert got["km"] > 1500, "Honolulu is about 1,810 km from that point"


def test_it_returns_the_nearest_and_not_the_first(run):
    """Iteration order puts Seoul first. A point beside Tokyo must not come
    back as Seoul.

    Mutation performed and reverted: `if (km < bestKm)` -> `if (best === null)`
    -> red.
    """
    got = run("nearestOrigin", 35.6, 139.7)
    assert got["origin"]["slug"] == "tokyo"
    assert got["km"] < 20


@pytest.mark.parametrize("km,expected", [
    (0.4, "less than a kilometre"),
    (33.8, "34 km"),
    (99.4, "99 km"),
    (464.0, "460 km"),
    (781.0, "780 km"),
])
def test_the_distance_is_stated_without_false_precision(run, km, expected):
    assert run("fmtKm", km) == expected


# ------------------------------------------------------------- the wiring ---

def _handler(name: str) -> str:
    return _function(name)


def test_the_marker_is_returned_to_the_city_it_snapped_to():
    """The honesty invariant. If the marker stays where it was dropped, every
    number on the page is being read as a measurement from that point.

    Mutation performed and reverted: delete the `originMarker.setLngLat`
    calls from originDragEnd -> red.
    """
    body = _handler("originDragEnd")
    assert body.count("originMarker.setLngLat(") >= 2, (
        "originDragEnd does not put the marker back on a charted city; it "
        "would be left on the dropped point, which nothing computed")
    # ...on BOTH exits: the no-origins case and the normal case.
    assert "[o.lon, o.lat]" in body


def test_the_snap_is_stated_in_words_with_the_city_and_the_distance():
    """Mutation performed and reverted: drop the fmtKm(km) interpolation ->
    red; drop the whole snapNotice call -> red.
    """
    body = _handler("originDragEnd")
    assert "snapNotice(" in body, "the drag says nothing about what it did"

    # Per BRANCH, not per function: the "Kept" branch also calls fmtKm, so a
    # whole-function `"fmtKm(km)" in body` passes while the "Moved to" message
    # has lost its distance entirely. That mutation survived the first version
    # of this test.
    moved = body[body.index('"Moved to '):]
    moved = moved[:moved.index(");") + 2]
    kept = body[body.index('"Kept "'):]
    kept = kept[:kept.index(");") + 2]

    for label, branch in (("moved", moved), ("kept", kept)):
        assert "fmtKm(km)" in branch, (
            f"the {label} message does not state how far the departure is "
            "from where the marker was dropped")
        assert "{ b: o.name }" in branch, (
            f"the {label} message does not name the city it snapped to")
    assert "not from that point" in moved, (
        "the notice does not say the times are NOT measured from where the "
        "marker was dropped, which is the one thing it exists to say")


def test_the_notice_cannot_be_given_markup_to_render():
    """It took an HTML string first, relying on every call site to remember
    esc() -- the same shape that made railVia() a stored XSS waiting for a
    second caller. A city name from index.json is not attacker-controlled
    today, but "safe because of who calls it" is what this repository has
    already had to fix once.

    Mutation performed and reverted: `el.innerHTML = parts.join("")` -> red.
    """
    body = _function("snapNotice")
    assert "innerHTML" not in body, (
        "the snap notice writes HTML, so its safety is a property of its "
        "callers rather than of itself")
    assert "createTextNode" in body and "textContent" in body


def test_the_switch_goes_through_the_one_guarded_entry_point():
    """paintOrigin is epoch-guarded and clears the previous origin's arrays.
    Assigning `active` directly, or fetching here, reintroduces the stale-array
    bug the generation counter exists to prevent.
    """
    body = _handler("originDragEnd")
    assert "paintOrigin(o, { keepZoom: true })" in body
    assert "dropDestination()" in body, (
        "the pin survives the origin switch, so a stale lastPointer is "
        "re-read as a live reading for a place the pointer left")
    assert "active =" not in body, "the drag assigns active behind paintOrigin"


def test_the_notice_is_written_after_the_switch_not_before():
    """paintOrigin clears the notice, so writing it first shows the message for
    one frame and then erases it.

    Mutation performed and reverted: move the snapNotice call above
    paintOrigin -> red.
    """
    body = _handler("originDragEnd")
    moved = body.index("Moved to")
    paint = body.index("paintOrigin(o,")
    assert paint < moved, (
        "the snap notice is written before paintOrigin, which clears it")


def test_any_other_route_to_a_new_departure_clears_a_stale_notice():
    """A notice describing one drag must not outlive the departure it named.

    Mutation performed and reverted: delete `snapNotice("")` from paintOrigin
    -> red.
    """
    body = _handler("paintOrigin")
    assert "snapNotice();" in body, (
        "paintOrigin does not clear the snap notice, so picking a city from "
        "the list leaves a message about a drag that no longer applies")


def test_the_live_feedback_speaks_in_the_future_tense():
    """During the drag the numbers on screen still belong to the ORIGIN THAT
    HAS NOT CHANGED. A live line saying "departing from X" would be false for
    as long as the drag lasts.
    """
    body = _handler("originDragMove")
    assert "Release to" in body, (
        "the live drag line does not distinguish what WOULD happen from what "
        "has happened")
    for claim in ("Departing from", "Times are measured"):
        assert claim not in body, (
            f"the live line claims {claim!r} before the switch has happened")


def test_the_departure_marker_is_actually_draggable():
    block = APP[APP.index("const originMarker = new maplibregl.Marker("):]
    block = block[:block.index(");") + 2]
    assert "draggable: true" in block


def test_the_destination_has_a_drag_handle_with_a_real_touch_target():
    """The drawn pin is a 9 px circle. A 9 px touch target is not one.

    The handle is separate from the circle layers on purpose: converting the
    pin to a marker would take it out of the layer order that keeps the route
    line underneath it, which test_app_constants.py asserts.
    """
    assert 'pinHandleEl.className = "pinhandle"' in APP
    block = APP[APP.index("const pinHandle = new maplibregl.Marker("):]
    assert "draggable: true" in block[:block.index(");") + 2]

    css = re.search(r"\.pinhandle\{([^}]*)\}", HTML)
    assert css, ".pinhandle has no style, so it has no hit area at all"
    size = re.search(r"width:(\d+)px", css.group(1))
    assert size and int(size.group(1)) >= 24, (
        f"the destination drag handle is {size and size.group(1)}px; 24 is the "
        "documented minimum touch target")

    # The pin layers must survive: removing them is what breaks the layer order.
    for layer in ("pin-halo", "pin-dot"):
        assert f'id: "{layer}"' in APP, f"{layer} was removed"


def test_dragging_the_destination_commits_through_the_shared_path():
    """commitDestination is the one path that keeps the headline, the
    itinerary and the permalink in step. The map-click handler has its own
    body and a comment saying why; a third body would be the third place to
    forget half the job.
    """
    block = APP[APP.index('pinHandle.on("dragend"'):]
    block = block[:block.index("\n});") + 4]
    assert "commitDestination(" in block
    assert "syncPermalink" not in block, (
        "the handle syncs the permalink itself instead of letting "
        "commitDestination do it; that is how the two get out of step")


def test_the_snap_notice_has_somewhere_to_be_written():
    assert 'id="snapped"' in HTML, "#snapped is not in the page"
    where = HTML.index('id="snapped"')
    reading = HTML.index('<section class="reading"')
    legend = HTML.index('<div class="legend">')
    assert reading < where < legend, (
        "#snapped is not inside the reading block, above the legend")
    assert re.search(r"\.reading \.snapped\{", HTML), "#snapped has no style"


def _pin_handler(event: str) -> str:
    block = APP[APP.index(f'pinHandle.on("{event}"'):]
    return block[:block.index("\n});") + 4]


def test_the_drawn_destination_dot_follows_the_drag():
    """The visible pin is two circle layers fed by the "pin" source; the
    handle that is dragged is an invisible marker. Moving only the handle left
    the dot where the drag began until release (owner, 2026-10-07).

    Mutation performed and reverted: the `getSource("pin")` line removed from
    the drag handler -> red.
    """
    drag = _pin_handler("drag")
    m = re.search(r'map\.getSource\("pin"\)\?\.setData\(pinDotData\(lng, lat\)\)', drag)
    assert m, "the drag handler no longer moves the drawn dot to the handle"
    assert drag.index("pinHandle.getLngLat()") < m.start()


def test_the_route_line_is_put_away_for_the_drag_and_redrawn_on_release():
    """The line belongs to the committed destination; mid-drag it would point
    at the old spot. dragend commits through commitDestination, whose
    renderLegs draws it again.

    Mutation performed and reverted: `|| pinDragging` removed from
    renderRoute's guard -> red.
    """
    start, end = _pin_handler("dragstart"), _pin_handler("dragend")
    assert "pinDragging = true" in start
    assert 'map.getSource("route")?.setData(pinDotData(null))' in start
    assert end.index("pinDragging = false") < end.index("commitDestination(")
    route = _function("renderRoute")
    assert re.search(r"if \(!pinB \|\| !active \|\| pinDragging\) return clear\(\);", route), \
        "renderRoute no longer stays clear while the destination is dragged"
    commit = _function("commitDestination")
    assert "renderLegs()" in commit
    assert "renderRoute();" in APP[APP.index("function renderLegs()"):][:120]
