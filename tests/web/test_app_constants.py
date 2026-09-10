"""The page re-types a handful of the pipeline's constants; keep them equal.

The channel order of .modes.bin, the two uint16 sentinels, the unreachable
band id, the tile layer name and the airports.json column order are read by
app.js as literals (or as fallbacks when index.json predates the field). A
change on one side that the other does not follow is a wrong route panel with
no error, so the literals are pinned to the emitters here.
"""

import re

from transport_maps import config, validate
from transport_maps.contour import bands
from transport_maps.emit import (
    airports_json,
    index,
    itinerary,
    modes,
    rail_detail,
    tiles,
)

APP = (config.ROOT / "web" / "app.js").read_text(encoding="utf-8")


def _js_list(name: str) -> list[str]:
    m = re.search(rf'{name}\s*=\s*meta\.\w+\s*\?\?\s*\[([^\]]*)\]', APP) or re.search(rf'const {name}\s*=\s*\[([^\]]*)\]', APP)
    assert m, f"{name} not found in app.js"
    return re.findall(r'"([^"]+)"', m.group(1))


def _js_const(name: str) -> str:
    m = re.search(rf'const {name}\s*=\s*([^;]+);', APP)
    assert m, f"{name} not found in app.js"
    return m.group(1).strip()


def test_mode_channel_fallback_matches_the_emitter():
    assert _js_list("MODE_NAMES") == list(modes.CHANNELS)


def test_sentinels_match_the_emitters():
    assert int(_js_const("NO_AIRPORT"), 16) == itinerary.NO_AIRPORT
    assert int(_js_const("NO_RAIL"), 16) == rail_detail.NO_RAIL
    assert int(_js_const("UNREACHABLE_BAND")) == bands.UNREACHABLE_BAND


def test_the_page_reads_the_tile_layer_the_emitter_writes():
    assert f'"source-layer": "{tiles.LAYER}"' in APP


def test_airports_json_column_order_matches_the_reads():
    """app.js reads a[0]=code, a[1]=name, a[2]=country, a[3]=lat, a[4]=lon, a[5]=size.

    The slice used to stop at five, so dropping "size" from the emitter left
    93 tests green -- and app.js reads it as `SIZE_RANK[a[5]] ?? 3`, where the
    `??` swallows `undefined`. Every airport would silently rank equal and
    T9's fix would come back: "tok" returning ACC Kotoka, ENT Eniwetok, FYN
    Koktokay and GTA Gatokae before HND. check_dist would stay green too,
    because it checks that airports.json exists.
    """
    fields = airports_json.FIELDS
    assert fields == ("iata", "name", "country", "lat", "lon", "size"), fields
    # ...and each position is actually read at that index in the page.
    for i, name in enumerate(("code", "name", "country", "lat", "lon", "size")):
        assert f"a[{i}]" in APP or f"x[{i}]" in APP, f"nothing reads column {i} ({name})"
    assert "SIZE_RANK[" in APP, "the size column is emitted and never used"


def test_every_index_json_key_the_page_reads_is_written(tmp_path):
    import json

    out = tmp_path / "index.json"
    index.write_index([{"slug": "s", "name": "S", "lat": 0.0, "lon": 0.0}], out,
                      hover_cell_count=1, graph={"rail": True, "ferry": True}, identity=index.build_identity())
    written = set(json.loads(out.read_text()))
    read = set(re.findall(r"meta\.(\w+)", APP))
    assert read <= written, f"app.js reads {sorted(read - written)} which write_index never writes"


def _tick_rule(targets, edges, hour_bonus=0.6):
    """paintScale's selection, ported: snap each target to the nearest edge by
    log distance, an exact hour winning when it is nearly as close."""
    import math

    picked = []
    for t in targets:
        best, best_err = -1, math.inf
        for i, e in enumerate(edges):
            err = abs(math.log(e / t)) * (hour_bonus if e % 60 == 0 else 1.0)
            if err < best_err:
                best, best_err = i, err
        picked.append(edges[best])
    return picked


def test_the_legend_tick_rule_lands_on_true_band_edges():
    """Every tick is a real band boundary -- the CLAUDE.md legend rule. The
    on-screen gap rule is measured in the browser (browser_verify.sh)."""
    m = re.search(r"const TICK_TARGETS_MIN = \[([^\]]+)\];", APP)
    targets = [int(x) for x in m.group(1).split(",")]
    edges = list(config.BAND_EDGES_MIN)
    picked = _tick_rule(targets, edges)
    assert picked == [60, 300, 1470, 4320]
    assert picked == sorted(set(picked)), "ticks must be distinct and ascending"
    assert picked[0] == min(e for e in edges if e >= targets[0])


def test_the_hour_bonus_is_a_rule_the_port_implements_not_a_constant_it_ignores():
    """The shipped ladder is blind to the hour bonus.

    On config.BAND_EDGES_MIN every target either IS an edge or has one so much
    closer than any hour edge that the factor never decides: 0.6, 1.0, 0.2 and
    0.9 all yield [60, 300, 1470, 4320], so a port that dropped `* 0.6`
    entirely would keep this file green while the page changed. Exercise the
    branch on a ladder where it decides, so the port is pinned to the rule and
    not to one outcome.
    """
    edges, targets = [114, 120], [100]
    assert _tick_rule(targets, edges, hour_bonus=0.6) == [120], "the hour edge wins with the bonus"
    assert _tick_rule(targets, edges, hour_bonus=1.0) == [114], "and loses without it"
    # And the factor the page actually ships is the one tested above.
    assert re.search(r"err \*= 0\.6;", APP), "app.js no longer applies the hour bonus"


def test_the_departure_card_excludes_the_cells_the_coverage_gate_excludes():
    """One rule for "land a route could reach in principle", not two.

    validate.check_coverage drops Antarctica from its denominator by name and
    says why: it is charted so the globe has no hole in it, but it has no
    scheduled passenger service, so every one of its cells is unreachable by
    construction. The departure card counted them, so Seoul, Tokyo, London and
    Sydney all printed exactly 10.2% "has no scheduled route from here" -- a
    fact about the dataset, not the city -- and 83.5% of that was Antarctica.
    Measured on the shipped dist/: 7,749 of 90,740 hover cells (8.54%).

    If the Python threshold moves and the page's does not, the card silently
    goes back to describing a different set of land from the gate.
    """
    assert float(_js_const("KNOWN_UNREACHABLE_MAX_LAT")) == validate.KNOWN_UNREACHABLE_MAX_LAT


def test_the_card_counts_only_the_cells_it_kept():
    """The denominator must be the mask, not the array length.

    Dividing the kept counts by the full array is the same bug in a subtler
    form: the numerators shrink and the denominator does not, so every figure
    reads low by the Antarctic share.
    """
    body = APP[APP.index("function renderDepartureInto"):]
    body = body[:body.index("\nfunction ")]
    assert "if (!mask[i]) continue;" in body, "the loop must skip the excluded cells"
    assert "denom++" in body and "/ (denom || 1)" in body, (
        "percentages must divide by the cells actually counted, not by t.length")
    assert "/ t.length" not in body, "t.length includes the cells the mask drops"


# --- U20: the failure CLAUDE.md names as this project's recurring one -------

BOOT = (config.ROOT / "web" / "boot.js").read_text(encoding="utf-8")
INDEX = (config.ROOT / "web" / "index.html").read_text(encoding="utf-8")


def test_the_boot_guard_is_installed_before_the_module_it_guards():
    """A guard loaded after app.js cannot catch app.js failing to load.

    Both twice-shipped blank-site incidents CLAUDE.md records were silent: by
    the time anyone looked, the console was empty. boot.js is a classic script,
    so it runs to completion before the module is even fetched.
    """
    boot = INDEX.index('src="./boot.js"')
    app = INDEX.index('src="./app.js"')
    assert boot < app, "boot.js must be earlier in the document than app.js"
    assert 'type="module"' not in INDEX[boot - 40:boot], (
        "boot.js must be a classic script; a module is deferred past app.js's fetch")


def test_the_boot_guard_covers_the_three_silent_failures():
    for hook in ("addEventListener(\"error\"", "addEventListener(\"unhandledrejection\""):
        assert hook in BOOT, f"boot.js does not listen for {hook}"
    assert "e.target" in BOOT, "a 404 on a <script> arrives with a target, not an error"
    # ...and the case with no error at all.
    assert "setTimeout" in BOOT and "data-slug" in BOOT, (
        "nothing covers 'everything resolved and nothing drew'")


def test_the_boot_guard_defers_to_fatal():
    """fatal() writes a specific message; a generic one must not paint over it."""
    assert 'classList.contains("fatal")' in BOOT


def test_webgl_is_checked_before_the_map_constructor_can_throw():
    """The Map constructor throws synchronously on a missing WebGL context, and
    everything that fills the page runs after it -- so fatal() was unreachable
    and the canvas HAD already been created, passing the deploy rule's own
    "confirm the canvas exists" check on a page that cannot paint."""
    guard = APP.index('getContext("webgl2")')
    ctor = APP.index("new maplibregl.Map(")
    assert guard < ctor, "the WebGL check must precede the Map constructor"
    assert "WebGL" in APP[guard:ctor], "the check must say what is missing"


def test_the_map_reports_its_own_errors():
    """MapLibre's default for an unlistened `error` is console.error only, so a
    missing tile archive gave a sea-coloured globe with no message."""
    assert 'map.on("error"' in APP
    assert "did not finish loading" in APP, "await map.on('load') has no timeout"


# --- U21 / TE4-6: two page-load guards no test could see -------------------
#
# Both were demonstrated deletable with all 34 tests in tests/web/ green, and
# both guard the blank-globe-with-no-console-error class CLAUDE.md names as
# this project's recurring failure. They live in browser code that pytest
# cannot execute, so the assertion is on the source: a future edit that
# removes the guard has to remove the reason too.

def test_a_stored_colour_scheme_cannot_be_a_prototype_property():
    """`RAMPS[r]` is truthy for "constructor", "toString" and "__proto__",
    none of which has a `.c`, so localStorage.ramp = "constructor" threw at
    module scope -- before fatal() existed to catch it -- and the globe was
    blank with nothing in the console."""
    i = APP.index('localStorage.getItem("ramp")')
    line = APP[i:i + 200]
    assert "Object.hasOwn(RAMPS" in line, (
        "the stored scheme is read back without an own-property check")
    assert "RAMPS[r] " not in line and "if (r && RAMPS[r])" not in line


def test_the_route_file_is_shape_checked_before_it_is_destructured():
    """The four .bin files are length-checked against hoverCells, but a rebuild
    that changes only the dense-split rule leaves the res-4 parent set
    bit-identical while offsets.airports moves by millions. Unguarded, the page
    then printed the POSITIVE claim "No flight on this journey: surface travel"
    with a full surface breakdown for a journey that flew."""
    i = APP.index("origin.routes = {")
    before = APP[max(0, i - 700):i]
    assert "Number.isFinite(off.airports)" in before
    assert "Number.isFinite(off.stations)" in before
    assert "Array.isArray(j.nodes)" in before


def test_the_rail_file_is_shape_checked_too():
    """T13 stopped one file short of its sibling: railVia() indexes
    rail.table on every rail-served cell, so a .rail.json without a stations
    array threw out of the click handler and left the previous destination's
    itinerary on screen."""
    i = APP.index("origin.rail = {")
    assert "Array.isArray(j.stations)" in APP[max(0, i - 500):i]
