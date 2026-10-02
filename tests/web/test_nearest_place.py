"""`nearestPlace` names the nearest gazetteer town, across the antimeridian too.

M10 (DBG-8). The hover readout leads with "near <town>" from `nearestPlace`,
which ranks 34,000 gazetteer rows by an equirectangular distance. Its
longitude difference was raw, so across ±180 -- Fiji's Taveuni and Vanua Levu,
Chukotka, the far end of the Aleutians -- a town 5 km east of the cursor
measured ~360 degrees away and lost to one on the far side of the island (or
the strait), whose distance was then printed as the cursor's.

Run in node against the real function, with a staged gazetteer.

Mutation performed and reverted: drop the two wrap lines in `nearestPlace`
(`if (dLon > 180) ...`, `else if (dLon < -180) ...`) -> red on both
antimeridian cases; the ordinary case stays green.
"""

from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from tests.web import _js


@pytest.fixture(scope="module")
def node() -> str:
    exe = shutil.which("node")
    if not exe:
        pytest.skip("node is not installed")
    return exe


def _nearest(node: str, rows: list[list], lat: float, lon: float) -> dict | None:
    src = f"""
const rows = {json.dumps(rows)};
let places = {{
  lat: Float32Array.from(rows, (x) => x[3]),
  lon: Float32Array.from(rows, (x) => x[4]),
  rows,
}};
{_js.function("nearestPlace")}
{_js.function("nearestPlaceScan")}
process.stdout.write(JSON.stringify(nearestPlace({lat}, {lon})));
"""
    out = subprocess.run([node, "-e", src], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


# [name, region, country, lat, lon] -- places.json's row shape.
_FIJI = [
    ["East", "Northern", "Fiji", -16.80, -179.97],   # ~4 km east, across the line
    ["West", "Northern", "Fiji", -16.80, 179.50],    # ~50 km west, same side
]


def test_a_town_across_the_line_wins_from_the_west(node) -> None:
    got = _nearest(node, _FIJI, -16.80, 179.99)
    assert got["name"] == "East", got
    assert got["km"] < 10, f"East is ~4 km away, reported {got['km']:.0f} km"


def test_a_town_across_the_line_wins_from_the_east(node) -> None:
    rows = [["Uelen", "Chukotka", "Russia", 66.16, 179.90],      # ~4 km west
            ["Lavrentiya", "Chukotka", "Russia", 65.58, -171.00]]  # far east
    got = _nearest(node, rows, 66.16, -179.99)
    assert got["name"] == "Uelen", got
    assert got["km"] < 10, f"Uelen is ~4 km away, reported {got['km']:.0f} km"


def test_away_from_the_line_nothing_changes(node) -> None:
    rows = [["Seoul", "Seoul", "South Korea", 37.57, 126.98],
            ["Incheon", "Incheon", "South Korea", 37.46, 126.71]]
    got = _nearest(node, rows, 37.55, 126.97)
    assert got["name"] == "Seoul", got
    assert 1 < got["km"] < 4, got


# --- R8 (PR-12): one scan per pointer frame ---------------------------------
#
# describe() and the tooltip both ask nearestPlace about the same e.lngLat in
# the same frame, and each paid a full 34,135-row scan. Measured in node on
# the real gazetteer: 0.155-0.191 ms a frame for the pair, 0.085-0.094 ms with
# the second call answered from the first. The answer is kept on `places`, so
# a gazetteer that is replaced takes its memo with it.
#
# Mutations performed and reverted:
# - drop the `return memo.p` line -> red, 2 scans in the same-point test;
# - keep the memo in a module-level `let` instead of on `places` -> red in the
#   replaced-gazetteer test, which got the old gazetteer's town back.


def _scans(node: str, script: str) -> dict:
    src = f"""
const mk = (rows) => ({{
  lat: Float32Array.from(rows, (x) => x[3]),
  lon: Float32Array.from(rows, (x) => x[4]),
  rows,
}});
let places = null;
{_js.function("nearestPlace")}
{_js.function("nearestPlaceScan")}
// Count the scans: the memo is only worth anything if the second ask is not one.
let scans = 0;
const realScan = nearestPlaceScan;
nearestPlaceScan = (lat, lon) => {{ scans++; return realScan(lat, lon); }};
const out = {{}};
{script}
process.stdout.write(JSON.stringify(out));
"""
    done = subprocess.run([node, "-e", src], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


_SEOUL = [["Seoul", "Seoul", "South Korea", 37.57, 126.98],
          ["Incheon", "Incheon", "South Korea", 37.46, 126.71]]


def test_the_same_point_twice_is_one_scan(node) -> None:
    got = _scans(node, f"""
places = mk({json.dumps(_SEOUL)});
const a = nearestPlace(37.55, 126.97), b = nearestPlace(37.55, 126.97);
out.scans = scans; out.same = a === b; out.name = b.name;
""")
    assert got["name"] == "Seoul", got
    assert got["scans"] == 1, f"{got['scans']} scans for one pointer frame"
    assert got["same"], got


def test_a_new_point_is_a_new_scan(node) -> None:
    got = _scans(node, f"""
places = mk({json.dumps(_SEOUL)});
nearestPlace(37.55, 126.97);
out.name = nearestPlace(37.47, 126.70).name; out.scans = scans;
""")
    assert got == {"name": "Incheon", "scans": 2}, got


def test_a_replaced_gazetteer_is_asked_again(node) -> None:
    got = _scans(node, f"""
places = mk({json.dumps(_SEOUL)});
nearestPlace(37.55, 126.97);
places = mk({json.dumps([["Elsewhere", "", "", 37.55, 126.97]])});
out.name = nearestPlace(37.55, 126.97).name; out.scans = scans;
""")
    assert got == {"name": "Elsewhere", "scans": 2}, got
