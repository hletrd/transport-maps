"""The hover reads the cell the band tiles draw, from the solver's blocks.

At zoom 7+ the tiles draw res-7 cells where the build split a base cell; from
zoom 3 to 6 they draw res-6 cells, a split one coloured by its fastest child
(contour/bands.py, LODS). The reading tier holds every res-6 cell's centre
child, so the hover printed one cell's time inside a ring drawn around others
-- the hexagon the owner saw "grow and shrink". `/api/cells` answers a res-3
block of the cells themselves (docs/contract.md, "The cells of a block"), and
`fineReading` picks the one the tiles draw under the pointer.

Everything here is lifted from web/app.js and run in node against the real
vendored h3, because the slot arithmetic is exactly what a stub would get
right by construction.
"""

from __future__ import annotations

import base64
import json
import shutil
import subprocess

import h3
import pytest

from tests.web import _js
from transport_maps import config
from transport_maps.service import wire

H3_JS = (config.ROOT / "web" / "vendor" / "h3.js").as_uri()
SEOUL = (37.5665, 126.978)
# The middle of a res-7 cell that is NOT its base cell's centre child, so the
# cell's own time and the reading tier's (the centre child's) differ.
_BASE = h3.latlng_to_cell(*SEOUL, 6)
POINT = h3.cell_to_latlng(next(c for c in sorted(h3.cell_to_children(_BASE, 7))
                               if c != h3.cell_to_center_child(_BASE, 7)))


@pytest.fixture(scope="module")
def node() -> str:
    exe = shutil.which("node")
    if not exe:
        pytest.skip("node is not installed")
    return exe


def _slot(cell: str, res: int) -> int:
    v, slot = int(cell, 16), 0
    for r in range(4, res + 1):
        slot = slot * 7 + ((v >> (45 - 3 * r)) & 7)
    return slot


def _block_at(lat, lon, *, here=33, siblings=(50, 20, 60, 70, 80, 90), split=True):
    """A block with the res-7 cell under (lat, lon) at `here` and its six
    siblings at `siblings`; every other slot is no cell."""
    cell = h3.latlng_to_cell(lat, lon, 7)
    s = _slot(cell, 7)
    base = s // 7
    times = [wire.NO_CELL] * 2401
    others = iter(siblings)
    for k in range(base * 7, base * 7 + 7):
        times[k] = here if k == s else next(others)
    flags = [0] * 343
    flags[base] = 1 if split else 0
    return h3.cell_to_parent(cell, 3), times, flags


def _run(node: str, tmp_path, body: str) -> dict:
    script = tmp_path / "probe.mjs"
    script.write_text(body + '\nawait new Promise((r) => process.stdout.write("", r));\n'
                      "process.exit(0);\n", encoding="utf-8")
    out = subprocess.run([node, str(script)], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


def _page(block: str, times, flags) -> str:
    return f"""
import * as h3 from {json.dumps(H3_JS)};
const READING_RES = 6, READING_PARENT_RES = 3, SOLVE_RES = 6, FINE_RES = 7;
{_js.statement("const FINE_NO_CELL")}
{_js.statement("const FINE_NATIVE_ZOOM")}
{_js.statement("const FINE_BASE_ZOOM")}
let ZOOM = 8, avoid = null, POINT = false;
const map = {{ getZoom: () => ZOOM }};
const pointShown = () => POINT;
let active = {{ slug: "seoul", lat: {SEOUL[0]}, lon: {SEOUL[1]} }};
const fineCells = {{ armed: true, blocks: new Map() }};
fineCells.blocks.set("seoul|{block}", {{ times: Uint16Array.from({json.dumps(times)}),
                                         split: Uint8Array.from({json.dumps(flags)}) }});
{_js.function("readingSlot")}
{_js.function("fineLevel")}
{_js.function("fineReading")}
const at = () => fineReading({POINT[0]}, {POINT[1]});
"""


def test_zoom_7_reads_the_res7_cell_under_the_pointer(node, tmp_path):
    """Mutation performed and reverted: read `b.times[base * per]` (the
    centre child, the reading tier's value) at the native level -> RED."""
    got = _run(node, tmp_path, _page(*_block_at(*POINT)) + "console.log(JSON.stringify(at()));")
    assert got == {"t": 33, "res": 7}


def test_zooms_3_to_6_read_the_split_cell_by_its_fastest_child(node, tmp_path):
    """Mutation performed and reverted: take the centre child at the base
    level -> RED."""
    got = _run(node, tmp_path, _page(*_block_at(*POINT))
               + "ZOOM = 5.9; const a = at(); ZOOM = 3; const b = at();"
                 "console.log(JSON.stringify([a, b]));")
    assert got == [{"t": 20, "res": 6}, {"t": 20, "res": 6}]


def test_where_a_block_says_nothing_new_the_reading_tier_answers(node, tmp_path):
    """An unsplit base cell (the tier holds what is drawn), a slot with no
    cell, the res-4 tiles below zoom 3, an avoided mode (another solve's
    tiles), the map from a point, another departure city, and a solver that
    is not armed: null every time.

    Mutation performed and reverted: drop `avoid` from fineLevel -> RED.
    """
    block, times, flags = _block_at(*POINT)
    nosplit = _block_at(*POINT, split=False)
    s = _slot(h3.latlng_to_cell(*POINT, 7), 7)
    hole = list(times)
    hole[s] = wire.NO_CELL
    got = _run(node, tmp_path, _page(block, times, flags) + f"""
const out = {{}};
ZOOM = 2.9; out.coarse = at(); ZOOM = 8;
avoid = "air"; out.avoid = at(); avoid = null;
POINT = true; out.point = at(); POINT = false;
active = {{ slug: "tokyo" }}; out.other = at(); active = {{ slug: "seoul" }};
fineCells.armed = false; out.unarmed = at(); fineCells.armed = true;
fineCells.blocks.set("seoul|{block}", {{ times: Uint16Array.from({json.dumps(hole)}),
                                         split: Uint8Array.from({json.dumps(flags)}) }});
out.hole = at();
fineCells.blocks.set("seoul|{block}", {{ times: Uint16Array.from({json.dumps(nosplit[1])}),
                                         split: Uint8Array.from({json.dumps(nosplit[2])}) }});
out.unsplit = at();
console.log(JSON.stringify(out));
""")
    assert got == dict.fromkeys(("coarse", "avoid", "point", "other", "unarmed", "hole", "unsplit"))


def test_the_drawn_cell_wins_over_the_reading_tier_in_lookup(node, tmp_path):
    """lookupRaw returns the block's answer, and readingGrid() then says res
    7, which is the grid the ring is drawn on.

    Mutation performed and reverted: move the fineReading call below the
    reading tier's return -> RED.
    """
    got = _run(node, tmp_path, f"""
const MAX_MINUTES = 65534, HOVER_RES = 4, READING_RES = 6;
let lastReadingRes = HOVER_RES;
const pointShown = () => false;
const origin = {{ reading: [500], times: [600] }};
const readingParents = [1n];
const cellIndex = () => 0, readingIndex = () => 0;
let DRAWN = {{ t: 77, res: 7 }};
const fineReading = () => DRAWN;
{_js.function("lookupRaw")}
{_js.function("readingGrid")}
const a = [lookupRaw(1, 2), readingGrid()];
DRAWN = null;
const b = [lookupRaw(1, 2), readingGrid()];
console.log(JSON.stringify([a, b]));
""")
    assert got == [[77, 7], [500, 6]]


def _client(body) -> str:
    return f"""
const SOLVER_WIRE_VERSION = 1, SOLVER_TIMEOUT_MS = 45000, SOLVE_RES = 6, FINE_RES = 7;
const READING_PARENT_RES = 3;
const solverEnabled = true;
const meta = {{ buildId: "b1" }};
{_js.statement("const SOLVER_CODES")}
{_js.statement("const SOLVER_CELLS_PATH")}
{_js.statement("const FINE_CELLS_VERSION")}
let ASKED = null;
globalThis.fetch = async (url) => {{ ASKED = url; const b = {body};
  return {{ ok: true, json: async () => (typeof b === "string" ? JSON.parse(b) : b) }}; }};
{_js.function("solveCells", with_async=True)}
"""


def _body(**over):
    body = wire.cells_body(times=bytes(2 * 2401), split=bytes(343),
                           block=int("8330e1fffffffff", 16), solve_res=6, fine_res=7,
                           build_id="b1", snapped_km=0.0, snapped_lat=1.0, snapped_lon=2.0)
    body.update(over)
    return json.dumps(body)


@pytest.mark.parametrize("over,ok", [
    ({}, True),
    ({"block": "8330e3fffffffff"}, False),               # another block than asked
    ({"buildId": "b0"}, False),                          # another build
    ({"cellsVersion": 2}, False),
    ({"fineRes": 8}, False),
    ({"times": base64.b64encode(bytes(4800)).decode()}, False),
    ({"split": base64.b64encode(bytes(342)).decode()}, False),
    ({"times": "not base64!"}, False),
])
def test_the_client_believes_only_its_own_block(node, tmp_path, over, ok):
    """Mutation performed and reverted: drop the block comparison -> RED on
    the second row."""
    got = _run(node, tmp_path, _client(json.dumps(_body(**over))) + """
const r = await solveCells({ lat: 37.5665, lon: 126.978 }, "8330e1fffffffff");
console.log(JSON.stringify({ ok: r.ok, code: r.code ?? null, n: r.ok ? r.times.length : 0,
                             asked: ASKED }));
""")
    assert got["ok"] is ok, got
    if ok:
        assert got["n"] == 2401
        assert got["asked"] == ("./api/cells?from=37.56650,126.97800&block=8330e1fffffffff&build=b1")
    else:
        assert got["code"] == "unavailable"


def test_a_captive_portal_is_unavailable_not_a_crash(node, tmp_path):
    got = _run(node, tmp_path, _client('"<html>"') + """
const r = await solveCells({ lat: 1, lon: 2 }, "8330e1fffffffff");
console.log(JSON.stringify(r));
""")
    assert got["ok"] is False and got["code"] == "unavailable"


def test_the_page_and_the_service_agree_on_the_block_format():
    """Mutation performed and reverted: FINE_NO_CELL = 65535 -> RED."""
    import re

    assert int(re.search(r"^const FINE_CELLS_VERSION = (\d+);", _js.APP, re.M).group(1)) \
        == wire.CELLS_VERSION
    assert int(re.search(r"^const FINE_NO_CELL = (\d+);", _js.APP, re.M).group(1)) == wire.NO_CELL


def test_a_resting_pointer_asks_once_and_a_refusal_holds_requests_back(node, tmp_path):
    """One request per block after the pointer rests; none for a block
    already held; `busy` holds every request back until its Retry-After; a
    block that lands is kept and the readings are redone.

    Mutations performed and reverted, each RED: drop the `blocks.has(key)`
    test (the second rest asks again); drop the `retryAt` test (a request
    inside the hold).
    """
    got = _run(node, tmp_path, f"""
import * as h3 from {json.dumps(H3_JS)};
const READING_RES = 6, READING_PARENT_RES = 3, SOLVE_RES = 6, FINE_RES = 7;
{_js.statement("const FINE_NATIVE_ZOOM")}
{_js.statement("const FINE_BASE_ZOOM")}
{_js.statement("const FINE_REST_MS")}
{_js.statement("const FINE_KEEP")}
const avoid = null, map = {{ getZoom: () => 8 }}, pointShown = () => false;
const active = {{ slug: "seoul", lat: 37.5665, lon: 126.978 }};
const fineCells = {{ armed: true, blocks: new Map(), ctl: null, timer: 0, retryAt: 0 }};
let ASKED = 0, ANSWER = {{ ok: false, code: "busy" }}, REREAD = 0;
const solveCells = async () => {{ ASKED++; return ANSWER; }};
const rereadFine = () => {{ REREAD++; }};
{_js.function("fineLevel")}
{_js.function("wantFine")}
const rest = () => new Promise((r) => setTimeout(r, FINE_REST_MS + 50));
const out = {{}};
wantFine({POINT[0]}, {POINT[1]}); await rest(); out.first = ASKED;
wantFine({POINT[0]}, {POINT[1]}); await rest(); out.held = ASKED;
fineCells.retryAt = 0; ANSWER = {{ ok: true, times: new Uint16Array(2401), split: new Uint8Array(343) }};
wantFine({POINT[0]}, {POINT[1]}); await rest(); out.landed = [ASKED, fineCells.blocks.size, REREAD];
wantFine({POINT[0]}, {POINT[1]}); await rest(); out.again = ASKED;
wantFine(37.0, 127.5); wantFine({POINT[0]}, {POINT[1]}); await rest(); out.moved = ASKED;
console.log(JSON.stringify(out));
""")
    assert got == {"first": 1, "held": 1, "landed": [2, 1, 1], "again": 2, "moved": 2}, got

