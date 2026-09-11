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
