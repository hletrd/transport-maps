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
