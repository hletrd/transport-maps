"""When the two tiers contradict each other, the page must not print the lie.

`emit/hover.py:write_reading` fills every slot of a res-3 block with the
UNREACHABLE sentinel and then writes only the slots that are land cells. The
res-4 tier has no such gap: `_representative_children` falls back to the
fastest child when a parent's centre cell is water. So a point inside a land
res-4 cell whose own res-6 cell is absent from the land mask reads a real
duration at one zoom and "no scheduled route" at another, from the same build.

Measured on the shipped `dist/` by two review lanes independently: **553 of 553
origins** do this at Kota Kinabalu -- 10 h 18 min from Kolkata at res 4, 65535
at res 6 -- and 13 of 34,135 labelled places and 47 of 4,008 airports sit on
such a cell, Bodo, Tarawa, Bora Bora and the Galapagos among them. Once the
1,464-origin build lands, departing from Kota Kinabalu and pointing at Kota
Kinabalu reads "no scheduled route" from itself.

The page ships no res-6 land set, so it cannot tell a padding slot from a
genuinely unreachable land cell -- which is why `plan/deferred.md:582` deferred
this. What it CAN tell is that the coarse tier, whose land set it does ship,
has a real answer for the cell the pointer is in. Printing that, with the
"read from the wider grid" disclosure the page already carries (and, since C3,
a hover ring drawn on that grid's cell), replaces a false statement with a true and qualified one.

`lookup()` is run here rather than asserted about, because the defect is a
branch and a substring check stays green when a branch is deleted.
"""

from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from tests.web import _js
from transport_maps import config

APP = (config.ROOT / "web" / "app.js").read_text(encoding="utf-8")


def _function(name: str) -> str:
    return _js.function(name)


# The tier logic lives in lookupRaw; lookup() wraps it with the carry-on
# adjustment, which tests/web/test_carry_on_and_route_detail.py runs.
LOOKUP = _function("lookupRaw")
GRID = _function("readingGrid")


def test_the_slices_contain_the_branch_under_test():
    assert "origin.reading" in LOOKUP and "cellIndex(" in LOOKUP
    assert "MAX_MINUTES" in LOOKUP, "lookup no longer compares against the sentinel"
    assert "lastReadingRes" in GRID, "readingGrid no longer reports the tier used"


@pytest.fixture(scope="module")
def node() -> str:
    exe = shutil.which("node")
    if exe is None:
        pytest.skip("node is not on PATH; lookup() cannot be run")
    return exe


def _run(node: str, tmp_path, *, land: bool, fine, coarse, has_reading=True) -> dict:
    """Run lookup() once. `fine` and `coarse` are the two tiers' raw uint16
    values; `None` for `coarse` means the coarse array has not arrived."""
    harness = f"""
const MAX_MINUTES = 65534;
const HOVER_RES = 4, READING_RES = 6;
let lastReadingRes = HOVER_RES;
// The map from a dropped point is not on screen here (test_point_map.py runs it).
const pointShown = () => false;
const LAND = {str(land).lower()};
const origin = {{
  reading: {"[" + str(fine) + "]" if has_reading else "null"},
  times: {"null" if coarse is None else "[" + str(coarse) + "]"},
}};
const readingParents = {"[1n]" if has_reading else "null"};
const cellIndex = () => (LAND ? 0 : -1);
const readingIndex = () => 0;
{LOOKUP}
{GRID}
const out = lookupRaw(5.9749, 116.0724);
console.log(JSON.stringify({{ value: out === undefined ? "undefined" : out,
                             grid: readingGrid() }}));
"""
    path = tmp_path / "lookup.mjs"
    path.write_text(harness, encoding="utf-8")
    done = subprocess.run([node, str(path)], capture_output=True, text=True, timeout=20)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_the_kota_kinabalu_case_stops_printing_no_scheduled_route(node, tmp_path):
    """The defect itself: res-6 says 65535, res-4 says 618 minutes.

    Mutation performed and reverted: delete the disagreement branch from
    lookup() -> red (value 65535, which the page renders as "No scheduled
    route" in the headline and announces as "no scheduled route from Seoul"
    over a full door-to-door breakdown in the Route panel).
    """
    seen = _run(node, tmp_path, land=True, fine=65535, coarse=618)
    assert seen["value"] == 618, (
        "the page still prints the finer tier's sentinel over a coarse tier "
        "that has a real answer for the same cell")


def test_the_fallback_says_it_came_from_a_wider_cell(node, tmp_path):
    """A number borrowed from a ~45 km cell while a ~6.5 km hexagon is
    outlined must be disclosed. The page already has that sentence; it is
    driven by readingGrid(), which used to answer from the presence of the
    reading array rather than from what was actually read.

    Mutation performed and reverted: make readingGrid() return READING_RES
    whenever origin.reading is set, as it did before -> red.
    """
    seen = _run(node, tmp_path, land=True, fine=65535, coarse=618)
    assert seen["grid"] == 4, (
        "the reading fell back to the res-4 tier and the page still claims it "
        "came from the res-6 grid, so the 'wider cell' disclosure never fires")


def test_a_genuine_res6_reading_is_untouched_and_still_says_res_6(node, tmp_path):
    """The overwhelmingly common case. A fallback that also fired here would
    throw away the reading tier the whole of cycle 7 built.

    Mutation performed and reverted: drop the `fine >= MAX_MINUTES` condition
    so the coarse value always wins -> red.
    """
    seen = _run(node, tmp_path, land=True, fine=412, coarse=618)
    assert seen["value"] == 412 and seen["grid"] == 6


def test_both_tiers_unreachable_still_reads_unreachable(node, tmp_path):
    """A cell that really has no route must keep saying so. Falling back to a
    coarse value that is also the sentinel changes nothing, and falling back
    to anything else would invent a journey.

    Mutation performed and reverted: drop the `coarse < MAX_MINUTES`
    condition -> red (the sentinel is returned as a res-4 reading, and the
    page then prints the 'wider cell' disclosure beside 'No scheduled route',
    which is a disclosure about nothing).
    """
    seen = _run(node, tmp_path, land=True, fine=65535, coarse=65535)
    assert seen["value"] == 65535 and seen["grid"] == 6


def test_open_water_is_still_open_water(node, tmp_path):
    """The res-4 land set remains the only thing that decides land or sea. A
    disagreement fallback that ran before that test would paint times over the
    ocean, which is worse than the defect it fixes.

    Mutation performed and reverted: move the `cellIndex(lat, lon) < 0` test
    below the reading lookup -> red.
    """
    seen = _run(node, tmp_path, land=False, fine=65535, coarse=618)
    assert seen["value"] is None


def test_a_reading_before_the_coarse_array_arrives_does_not_invent_a_number(node, tmp_path):
    """During the load the res-4 array can be absent while the reading tier is
    not. The fallback must not turn `undefined` into a reading.

    Mutation performed and reverted: compare `coarse < MAX_MINUTES` without
    the `coarse !== undefined` guard -> `undefined < 65534` is false in
    JavaScript so this one survives, which is why the assertion below checks
    the VALUE rather than trusting the comparison.
    """
    seen = _run(node, tmp_path, land=True, fine=65535, coarse=None)
    assert seen["value"] == 65535, (
        "with no coarse array there is nothing to fall back to; the sentinel "
        "is the honest answer")


def test_the_grid_is_captured_beside_the_lookup_it_describes():
    """`readingGrid()` answers about the LAST lookup, and `showReading` is not
    the only caller: `onScreenBandRange` and `capCities` each make hundreds.
    Reading it forty lines below the lookup it describes makes the disclosure
    depend on nothing in between ever calling `lookup()` again -- true today,
    and not a property anyone would think to preserve.

    Mutation performed and reverted: move the capture back to its use site ->
    red.
    """
    body = _function("showReading")
    lookup_at = body.index("lookup(lat, lng)")
    capture_at = body.index("const grid = readingGrid();")
    between = body[lookup_at:capture_at]
    assert capture_at > lookup_at, "the grid is captured before the lookup it describes"
    assert between.count("\n") <= 8, (
        "the grid is captured well after the lookup; anything added in between "
        "that calls lookup() silently changes what the disclosure describes")
    assert "readingGrid()" not in body[capture_at + 26:], (
        "readingGrid() is called twice in showReading; the second call can "
        "describe a different lookup from the first")
