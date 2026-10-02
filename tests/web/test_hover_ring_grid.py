"""C3: the hover ring outlines the cell the number beside it was read from.

The ring was drawn at SOLVE_RES (res 6) whatever the number came from. Where
the reading fell back to the res-4 array -- the reading tier still in flight,
declined under Save-Data, absent from the build, or contradicting the coarse
tier (test_tier_disagreement.py) -- a 6.5 km hexagon sat around a number read
from a 45 km one, and the line under the number had to say "read from a wider
cell than the outline". Now `highlight` takes the grid `readingGrid()` reports
for the lookup just made, and `reoutline` redraws a ring under a still pointer
when the data that lands moves the reading to another grid.

The res-7 half of C3 -- outlining the refined cell where the surface was
solved finer -- is NOT here: the reading tier holds one value per res-6 cell
(the centre res-7 child's, emit/hover.py), so a res-7 ring would outline a
cell the number does not come from. It needs the split-cell set from the
emitter and a rebuild.

The handler, `highlight` and `reoutline` are lifted from app.js and run in
node with the page stubbed around them.

Mutations performed and reverted:
- mousemove calls `highlight(lat, lng)` without the grid -> red, the res-4
  readings get a res-6 ring (3 failed);
- `highlight` ignores `res` and uses SOLVE_RES -> red;
- `rereadPointer` no longer calls `reoutline()` -> red in the still-pointer
  test, which keeps the res-4 ring after the res-6 tier lands.
- `reoutline` skips its lookup and redraws whatever it had -> red in the
  went-away test.
"""

from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from tests.web import _js

HANDLER = _js.block('map.on("mousemove"', opener="(") + ";"


@pytest.fixture(scope="module")
def node() -> str:
    exe = shutil.which("node")
    if not exe:
        pytest.skip("node is not installed")
    return exe


def _run(node: str, script: str) -> dict:
    src = f"""
const SOLVE_RES = 6, MAX_MINUTES = 65534;
const drawn = [];
let GRID = 6, VALUE = 300, pinB = null, namePlaces = false, raf = 0;
let hoveredCell = null, hoveredAt = null;
const handlers = {{}};
const map = {{
  on: (ev, fn) => {{ handlers[ev] = fn; }},
  getSource: () => ({{ setData: (d) => drawn.push(d) }}),
}};
// The cell id carries its resolution, so the test can read back which grid
// the ring was drawn on without a real h3.
const h3 = {{
  latLngToCell: (lat, lon, res) => `r${{res}}:${{lat.toFixed(1)}},${{lon.toFixed(1)}}`,
  cellToBoundary: () => [[0, 0], [0, 1], [1, 1]],
}};
const unwrap = (pts) => pts;
const requestAnimationFrame = (fn) => {{ fn(); return 0; }};
const tip = {{ hidden: true, innerHTML: "", offsetWidth: 10, offsetHeight: 10, style: {{}} }};
const $ = () => tip;
const window = {{ innerWidth: 1280, innerHeight: 800 }};
const onGlobe = () => true;
const lookup = () => VALUE;
const showReading = () => VALUE;
const readingGrid = () => GRID;
const fmtTime = (t) => [String(t), "min"];
const fmtCoord = () => "0N 0E";
const esc = (s) => s;
const nearestPlace = () => null, placeLead = () => null;
let lastPointer = null;
const onNearSide = () => true;
map.project = () => ({{ x: 1, y: 1 }});
{_js.function("highlight")}
{_js.function("clearHighlight")}
{_js.function("reoutline")}
{_js.function("rereadPointer")}
{HANDLER}
const move = (lat, lng) => handlers.mousemove({{
  point: {{ x: 1, y: 1 }}, lngLat: {{ lat, lng }},
  originalEvent: {{ clientX: 1, clientY: 1 }},
}});
const out = {{}};
{script}
out.cell = hoveredCell;
process.stdout.write(JSON.stringify(out));
"""
    done = subprocess.run([node, "-e", src], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_a_res4_reading_gets_a_res4_ring(node) -> None:
    got = _run(node, "GRID = 4; move(37.5, 127.0);")
    assert got["cell"].startswith("r4:"), (
        f"the number came from the res-4 grid and the ring was drawn on {got['cell']}")


def test_a_res6_reading_keeps_the_res6_ring(node) -> None:
    got = _run(node, "GRID = 6; move(37.5, 127.0);")
    assert got["cell"].startswith("r6:"), got


def test_with_a_destination_pinned_the_ring_follows_the_hover_lookup(node) -> None:
    # The headline is the pin's; the ring is the pointer's, read by lookup().
    got = _run(node, "pinB = { lat: 0, lon: 0 }; GRID = 4; move(37.5, 127.0);")
    assert got["cell"].startswith("r4:"), got


def test_highlight_draws_on_the_grid_it_is_given(node) -> None:
    got = _run(node, """
highlight(37.5, 127.0, 4); out.a = hoveredCell;
highlight(37.5, 127.0); out.b = hoveredCell;
out.draws = drawn.length;
""")
    assert got["a"].startswith("r4:") and got["b"].startswith("r6:"), got
    assert got["draws"] == 2, "the same point on a new grid must be redrawn"


def test_a_still_pointer_gets_its_ring_redrawn_when_the_reading_tier_lands(node) -> None:
    # rereadPointer() is what the page runs when an origin's arrays or the
    # reading tier land; the stubbed showReading leaves lastPointer unset, so
    # this is also the "no reading to redo" path, where the ring still counts.
    got = _run(node, """
GRID = 4; move(37.5, 127.0); out.before = hoveredCell;
GRID = 6; rereadPointer();
""")
    assert got["before"].startswith("r4:"), got
    assert got["cell"].startswith("r6:"), (
        "the res-6 tier landed under a still pointer and the ring stayed on the "
        f"res-4 cell: {got['cell']}")


def test_reoutline_draws_nothing_where_there_is_no_ring(node) -> None:
    got = _run(node, "reoutline(); out.draws = drawn.length;")
    assert got["draws"] == 0 and got["cell"] is None, got


def test_reoutline_drops_a_ring_whose_reading_went_away(node) -> None:
    got = _run(node, "move(37.5, 127.0); VALUE = undefined; reoutline();")
    assert got["cell"] is None, got

