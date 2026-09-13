"""Run the route geometry and check what it DRAWS.

`greatCircle` and `unwrap` are the newest feature's entire geometry, and the
only thing pinning them was three `assert "..." in APP` substring checks:
gutting either left all 94 `tests/web/` tests green while Seoul -> Honolulu was
drawn 357.8 degrees the wrong way round the globe and Seoul -> New York reached
40.6N instead of 77.8N. A flat line between two points is a perfectly plausible
drawing; nothing about it errors.

Both are pure functions of arrays of numbers, with no DOM, no MapLibre and no
module imports, so they can be sliced out of `app.js` by brace matching and run
under Node -- the same approach `test_boot_behaviour.py` takes to boot.js. The
expected values are computed here from spherical trigonometry, independently of
the implementation, so this is a comparison against the mathematics rather than
against a recorded output of the code under test.
"""

from __future__ import annotations

import itertools
import json
import math
import re
import shutil
import subprocess

import pytest

from transport_maps import config

APP = (config.ROOT / "web" / "app.js").read_text(encoding="utf-8")

SEOUL = (126.98, 37.57)
NEW_YORK = (-73.78, 40.64)
HONOLULU = (-157.92, 21.32)
LONDON = (-0.46, 51.47)


def _function(name: str) -> str:
    """The verbatim source of a top-level function, by brace matching."""
    start = APP.index(f"function {name}(")
    i = APP.index("{", start)
    depth = 0
    for j in range(i, len(APP)):
        if APP[j] == "{":
            depth += 1
        elif APP[j] == "}":
            depth -= 1
            if depth == 0:
                return APP[start:j + 1]
    raise AssertionError(f"function {name} is not brace-balanced")


@pytest.fixture(scope="module")
def node() -> str:
    exe = shutil.which("node")
    if exe is None:
        pytest.skip("node is not on PATH; the route geometry cannot be run")
    return exe


@pytest.fixture(scope="module")
def run(node: str, tmp_path_factory):
    src = _function("unwrap") + "\n" + _function("greatCircle") + "\n"
    path = tmp_path_factory.mktemp("geom") / "geom.cjs"
    path.write_text(
        src + "const [fn, args] = JSON.parse(process.argv[2]);\n"
        "process.stdout.write(JSON.stringify(({unwrap, greatCircle})[fn](...args)));\n",
        encoding="utf-8")

    def call(fn: str, *args):
        done = subprocess.run([node, str(path), json.dumps([fn, list(args)])],
                              capture_output=True, text=True, check=True)
        return json.loads(done.stdout)
    return call


def _max_latitude(a, b) -> float:
    """The highest latitude the great circle through a and b reaches between
    them, from Clairaut's relation -- derived here, not taken from app.js."""
    r = math.radians
    lo1, la1, lo2, la2 = r(a[0]), r(a[1]), r(b[0]), r(b[1])
    best = max(a[1], b[1])
    d = 2 * math.asin(math.sqrt(
        math.sin((la2 - la1) / 2) ** 2
        + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2))
    for i in range(2001):
        f = i / 2000
        A, B = math.sin((1 - f) * d) / math.sin(d), math.sin(f * d) / math.sin(d)
        x = A * math.cos(la1) * math.cos(lo1) + B * math.cos(la2) * math.cos(lo2)
        y = A * math.cos(la1) * math.sin(lo1) + B * math.cos(la2) * math.sin(lo2)
        z = A * math.sin(la1) + B * math.sin(la2)
        best = max(best, math.degrees(math.atan2(z, math.hypot(x, y))))
    return best


def test_a_flight_is_drawn_as_a_great_circle_not_a_straight_line(run):
    """Seoul -> New York passes near the pole. Drawn flat it would cross the
    Pacific at the latitude of its endpoints.

    Mutation performed and reverted: make greatCircle return `unwrap([a, b])`
    unconditionally -> red (reaches 40.6N, not 77.8N).
    """
    pts = run("greatCircle", list(SEOUL), list(NEW_YORK))
    assert len(pts) > 8, "the arc is not sampled; it is a straight segment"
    top = max(p[1] for p in pts)
    expected = _max_latitude(SEOUL, NEW_YORK)
    assert expected > 70, "the reference calculation is wrong; re-derive it"
    assert abs(top - expected) < 1.0, (
        f"the drawn flight reaches {top:.1f}N where the great circle through "
        f"the same two points reaches {expected:.1f}N")
    # ...and it still starts and ends where the itinerary says it does.
    assert abs(pts[0][0] - SEOUL[0]) < 1e-6 and abs(pts[0][1] - SEOUL[1]) < 1e-6
    assert abs(pts[-1][1] - NEW_YORK[1]) < 1e-6
    assert abs(((pts[-1][0] - NEW_YORK[0] + 180) % 360) - 180) < 1e-6


def test_the_short_way_round_is_the_way_drawn(run):
    """Seoul -> Honolulu crosses the antimeridian.

    Without unwrapping, longitude jumps 126.98 -> -157.92 and the line is drawn
    357.8 degrees the wrong way round the globe, straight through Africa.

    Mutation performed and reverted: make unwrap `return pts` -> red.
    """
    for a, b in ((SEOUL, HONOLULU), (HONOLULU, SEOUL), (SEOUL, NEW_YORK)):
        pts = run("greatCircle", list(a), list(b))
        span = abs(pts[-1][0] - pts[0][0])
        assert span <= 180.0 + 1e-6, (
            f"{a} -> {b} is drawn {span:.1f} degrees round the globe; the short "
            "way is at most 180")
        for p, q in itertools.pairwise(pts):
            assert abs(q[0] - p[0]) <= 180.0, (
                "a consecutive pair jumps more than 180 degrees of longitude, "
                "which MapLibre draws as a line across the whole map")


def test_unwrap_moves_longitudes_only_by_whole_turns(run):
    """It may shift a point by 360 to keep the line continuous; it must never
    move it anywhere else, or the drawn line leaves the itinerary's places."""
    pts = [[170.0, 10.0], [-175.0, 11.0], [178.0, 12.0], [-170.0, 13.0]]
    out = run("unwrap", pts)
    assert len(out) == len(pts)
    for original, moved in zip(pts, out):
        assert moved[1] == original[1], "unwrap moved a latitude"
        turns = (moved[0] - original[0]) / 360
        assert abs(turns - round(turns)) < 1e-9, (
            f"unwrap moved {original[0]} to {moved[0]}, which is not a whole turn")
    for p, q in itertools.pairwise(out):
        assert abs(q[0] - p[0]) <= 180.0


def test_two_points_in_the_same_place_still_give_a_drawable_line(run):
    """A connection at an airport is two chain nodes at one coordinate, and the
    arc formula divides by sin(d). The guard is `if (!(d > 1e-9))`."""
    pts = run("greatCircle", list(LONDON), list(LONDON))
    assert len(pts) >= 2
    for p in pts:
        assert all(isinstance(v, (int, float)) and math.isfinite(v) for v in p), (
            f"a zero-length leg produced {p}; NaN removes the whole line")


# --- the hover ring, which had the same defect the flight arc was fixed for --

def test_the_hover_ring_on_the_antimeridian_is_one_hexagon_not_a_band(run):
    """highlight() draws the H3 cell under the pointer as a polygon. A cell
    straddling the antimeridian has vertices at about +179 and about -179, and a
    polygon whose longitudes jump 358 degrees is rendered the long way round --
    a band right across the globe under the pointer instead of one hexagon.

    unwrap() is the fix the flight arc already uses; highlight() did not call it.
    Checked two ways: the real unwrap must close the seam, and highlight() must
    be the thing that calls it.

    Mutation performed and reverted: drop the unwrap() from highlight() -> red on
    the second assertion, which is the one about the call site.
    """
    # A res-6-sized hexagon sitting on the seam, in the [lon, lat] order
    # highlight() hands to unwrap after its own [lat, lon] -> [lon, lat] swap.
    ring = [[179.6, 10.0], [179.9, 10.2], [-179.8, 10.1],
            [-179.8, 9.8], [179.9, 9.6], [179.6, 9.8]]
    spread = max(p[0] for p in ring) - min(p[0] for p in ring)
    assert spread > 180, "the fixture does not actually straddle the seam"

    out = run("unwrap", ring)
    assert len(out) == len(ring)
    got = max(p[0] for p in out) - min(p[0] for p in out)
    assert got < 1.0, (
        f"unwrap left the ring {got:.1f} degrees wide; a hexagon is under one "
        "degree across at this size and the seam is still open")
    for before, after in zip(ring, out):
        turns = (after[0] - before[0]) / 360
        assert abs(turns - round(turns)) < 1e-9, "a vertex moved by part of a turn"
        assert after[1] == before[1], "unwrap moved a latitude"

    # ...and highlight() is what calls it. Comments stripped first: the standing
    # rule is that an assertion over source text a comment can satisfy is
    # vacuous, and this one is explained by a comment naming unwrap.
    body = re.sub(r"//[^\n]*", "", _function("highlight"))
    assert "unwrap(" in body, (
        "highlight() builds its ring without unwrap(), so a cell on the "
        "antimeridian paints a 360-degree band across the globe")
    assert "cellToBoundary" in body


# --- the leading ground leg, which must not be drawn for a chain that cannot
#     say how the journey reached its first airport -------------------------

def _render_route_probe(partial: str) -> str:
    """Run the real `renderRoute` and report the features it hands the map.

    `legsTo` is stubbed because the property under test is a property OF the
    chain -- whether the walk could be completed -- and staging it is the whole
    point; `legsTo` itself is run for real in `tests/web/test_itinerary_grid.py`.
    Everything else here, `renderRoute`/`unwrap`/`greatCircle`, is app.js.
    """
    return f"""
const MAX_MINUTES = 65534;
const feats = [];
const map = {{ getSource: () => ({{ setData: (d) => feats.push(...d.features) }}) }};
// Seoul, and a pin in Mauritius: the journey the defect was reported on.
const active = {{ lat: 37.57, lon: 126.98, name: "Seoul" }};
const pinB = {{ lat: -20.162, lon: 57.499, label: "Port Louis" }};
const airports = [["KUL", "Kuala Lumpur", "MY", 2.746, 101.710],
                  ["MRU", "Sir Seewoosagur Ramgoolam", "MU", -20.430, 57.683]];
function lookup() {{ return 1121; }}
// Recorded rather than ignored: whether the flowing-dash loop is asked to run
// is part of what renderRoute decides, and the test below asserts it.
let flowAsked = null;
function setRouteFlow(on) {{ flowAsked = on; }}
function legsTo() {{
  const chain = [{{ code: "KUL", kind: "dep", min: 648 }},
                 {{ code: "MRU", kind: "arr", min: 1121 }}];
  chain.partial = {partial};
  return chain;
}}
{_function("unwrap")}
{_function("greatCircle")}
{_function("renderRoute")}
renderRoute();
console.log(JSON.stringify({{ flowAsked, feats: feats.map((f) => [f.properties.kind,
  f.geometry.coordinates[0], f.geometry.coordinates[f.geometry.coordinates.length - 1]]) }}));
"""


@pytest.fixture(scope="module")
def render_route(node: str, tmp_path_factory):
    def call(partial: bool):
        path = tmp_path_factory.mktemp("route") / "route.mjs"
        path.write_text(_render_route_probe("true" if partial else "false"),
                        encoding="utf-8")
        done = subprocess.run([node, str(path)], capture_output=True, text=True,
                              timeout=60)
        assert done.returncode == 0, done.stderr
        return json.loads(done.stdout.strip().splitlines()[-1])
    return call


def _feats(got: dict) -> list:
    return got["feats"]


def test_a_partial_chain_draws_no_leg_to_its_first_airport(render_route):
    """From Seoul, whose only land border is sealed, the page drew a ground line
    all the way to Kuala Lumpur: `legsTo` had lost the flights before KUL, and
    `renderRoute` joined the departure city to `chain[0]` regardless.

    A complete chain still draws that leg -- that is the common case and the
    control for this test. A partial one must not: nothing in the data says the
    journey went over the ground, and a line on a globe is an assertion.

    Mutation performed and reverted: drop `&& !chain.partial` from the leading
    `add(...)` in renderRoute -> red on the first assertion below.
    """
    partial = _feats(render_route(True))
    kinds = [k for k, _, _ in partial]
    assert kinds.count("ground") == 1, (
        f"a partial chain drew {kinds.count('ground')} ground legs; only the "
        f"one onward from MRU is substantiated: {partial}")
    starts = [start for kind, start, _ in partial if kind == "ground"]
    assert abs(starts[0][0] - 57.683) < 0.5, (
        f"the one ground leg should leave MRU, not Seoul: {starts[0]}")

    # The control: with the chain complete the leg to the first airport is
    # drawn, so the assertion above is about `partial` and not about the
    # feature count happening to be one.
    whole = _feats(render_route(False))
    assert [k for k, _, _ in whole].count("ground") == 2, (
        f"a complete chain must still draw both ground legs: {whole}")
    assert any(abs(start[0] - 126.98) < 0.5
               for kind, start, _ in whole if kind == "ground"), (
        f"the complete chain's first ground leg should leave Seoul: {whole}")

    # Both draw the flight itself.
    for name, got in (("partial", partial), ("complete", whole)):
        assert [k for k, _, _ in got].count("air") == 1, (
            f"the {name} chain lost the flight KUL -> MRU: {got}")
