"""Carry-on only, the fine cell's own route, and the place-name threshold --
run in node, not grepped."""

from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from transport_maps import config

APP = (config.ROOT / "web" / "app.js").read_text(encoding="utf-8")


def _function(name: str) -> str:
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
        pytest.skip("node is not on PATH")
    return exe


def _run(node, tmp_path, body: str) -> dict:
    path = tmp_path / "h.mjs"
    path.write_text(body, encoding="utf-8")
    done = subprocess.run([node, str(path)], capture_output=True, text=True, timeout=20)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


# ---- the override file --------------------------------------------------------

def _override_bytes(entries):
    """entries: [(slot, airport, [6 minutes])] -> emit/override.py's layout."""
    import numpy as np
    slots = np.array([e[0] for e in entries], "<u4")
    ap = np.array([e[1] for e in entries], "<u2")
    mins = np.array([e[2] for e in entries], "<u2").reshape(-1)
    return list(slots.tobytes() + ap.tobytes() + mins.tobytes())


FINE_HARNESS = """
const MODE_NAMES = ["rail", "ferry", "highway", "major road", "minor road", "track"];
const bytes = new Uint8Array({bytes});
{parse}
{fine}
const origin = {{ reading: [0], over: parseOverride(bytes.buffer, "x") }};
const readingParents = [1n];
let SLOT = 0;
const readingIndex = () => SLOT;
const out = {{}};
for (const s of [10, 20, 30, 15]) {{
  SLOT = s;
  const r = fineRoute(0, 0);
  out[s] = r ? {{ airport: r.airport, modes: Array.from(r.modes) }} : null;
}}
let refused = null;
try {{ parseOverride(new ArrayBuffer(17), "bad"); }} catch (e) {{ refused = e.message; }}
out.refused = refused;
console.log(JSON.stringify(out));
"""


def test_the_fine_route_is_found_by_slot_and_nothing_else_is(node, tmp_path):
    b = _override_bytes([(10, 3, [0, 0, 5, 0, 0, 0]), (20, 65535, [0, 0, 0, 7, 0, 0]),
                         (30, 1, [1, 2, 3, 4, 5, 6])])
    got = _run(node, tmp_path, FINE_HARNESS.format(
        bytes=b, parse=_function("parseOverride"), fine=_function("fineRoute")))
    assert got["10"] == {"airport": 3, "modes": [0, 0, 5, 0, 0, 0]}
    assert got["20"]["airport"] == 65535
    assert got["30"] == {"airport": 1, "modes": [1, 2, 3, 4, 5, 6]}
    assert got["15"] is None, "a slot not in the file has no fine route"
    assert got["refused"] and "18-byte" in got["refused"], \
        "a file that is not whole entries must be refused, not read"


# ---- carry-on -----------------------------------------------------------------

CARRY_HARNESS = """
const MAX_MINUTES = 65534, NO_AIRPORT = 0xFFFF;
const meta = {{ carryOn: {{ departureMin: 15, arrivalMin: 10 }} }};
let carryOn = {on};
const RAW = {raw};
const AIR = {air};
function lookupRaw() {{ return RAW; }}
const origin = {{ air: [AIR] }};
const cellIndex = () => 0;
function fineRoute() {{ return {fine}; }}
{saving}
{lookup}
console.log(JSON.stringify({{ shown: lookup(0, 0), raw: lookupRaw(0, 0) }}));
"""


@pytest.mark.parametrize("on,raw,air,fine,want", [
    ("true", 600, 3, "null", 575),                       # flew: 15 + 10 off
    ("false", 600, 3, "null", 600),                      # off: untouched
    ("true", 600, 0xFFFF, "null", 600),                  # overland: nothing to save
    ("true", 65534, 3, "null", 65534),                   # unreachable stays unreachable
    ("true", 600, 0xFFFF, "{airport: 2, modes: []}", 575),  # the FINE cell flew
    ("true", 600, 3, "{airport: 0xFFFF, modes: []}", 600),  # the fine cell did not
])
def test_carry_on_takes_the_airport_minutes_off_a_journey_that_flew(node, tmp_path, on, raw, air, fine, want):
    got = _run(node, tmp_path, CARRY_HARNESS.format(
        on=on, raw=raw, air=air, fine=fine,
        saving=_function("carryOnSaving"), lookup=_function("lookup")))
    assert got["shown"] == want
    assert got["raw"] == raw, "the colours' reading must never be adjusted"


def test_the_band_colour_sampler_reads_the_raw_time():
    """The map is not reprinted for carry-on, so the one place a time becomes a
    band colour must not see the adjusted number."""
    assert "bandIndexOf(lookupRaw(ll.lat, ll.lng))" in APP
    assert "bandIndexOf(lookup(" not in APP


# ---- the place-name threshold -----------------------------------------------

@pytest.mark.parametrize("km,want", [(5, "Saipan"), (19, "Saipan"), (25, "near Saipan"),
                                     (200, "near Saipan"), (300, None)])
def test_a_place_more_than_a_hover_cell_away_is_near_not_here(node, tmp_path, km, want):
    got = _run(node, tmp_path, _function("placeLead") + f"""
console.log(JSON.stringify({{ v: placeLead({{ name: "Saipan", km: {km} }}) ?? null }}));""")
    assert got["v"] == want
