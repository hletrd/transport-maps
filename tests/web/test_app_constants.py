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
    # ...and the case with no error at all. The signal is app.js's own start
    # flag, not a count of rows in the search-filtered city list -- that is
    # what made the watchdog fire on healthy pages.
    assert "setTimeout" in BOOT and "appReady" in BOOT, (
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


def test_the_bands_layer_turns_off_fill_antialias():
    """MapLibre's fill-antialias defaults to true and draws a 1px outline
    around every polygon, so a shared band rim composited darker than either
    side: a hairline tracing the boundary. With 37 bands, most of them one
    cell wide near the origin, almost every hexagon edge IS a band boundary,
    and the map read as hexagons with outlines drawn between them.

    Measured on the bands layer alone at z7.2, everything else hidden: 236
    one-pixel dark seams with antialiasing, 15 without.

    Across the four CLAUDE.md viewports, classifying every pixel the setting
    changes against the aliased render as ground truth: 39,448 were a colour
    DARKER than anything that belongs there -- pure artifact -- and 46,176
    were antialiasing a real edge. Of that second group 84% step by under 6
    grey levels, which is less than one ramp step and therefore invisible,
    and the high-contrast remainder steps every 1-2 px, so it reads as a
    diagonal rather than a staircase.

    None of the twelve cycle-4 reviewers found this; the user did.
    """
    block = APP[APP.index('id: "bands", type: "fill"'):]
    block = block[:block.index('}, "water");')]
    assert '"fill-antialias": false' in block, (
        "the bands layer is back to MapLibre's antialiased default, which draws "
        "a dark hairline along every band boundary")
    # The neighbouring settings this depends on: opaque fills painted slow to
    # fast, so an aliased edge lands on the adjacent band rather than on space.
    assert '"fill-opacity": 1' in block
    assert "fill-sort-key" in APP[APP.index('id: "bands", type: "fill"'):][:1200]


# --- the journey drawn on the globe ----------------------------------------

def test_the_route_line_is_built_from_the_same_walk_as_the_itinerary():
    """Two readings of one chain is how a map and its caption drift apart.

    renderLegsInto() and renderRoute() both walk the chain legsTo() returns,
    and they must agree on what it means: chain[0] is reached from the
    departure city by ground, an "arr" node is a flight from the node before
    it, a "dep" node is a connection at an airport already stood in, and the
    last node is where the journey lands. So renderRoute is driven from
    renderLegs and from nowhere else.
    """
    assert "function renderLegs() { renderLegsInto(); renderRoute(); fitReading(); }" in APP
    # The semicolon is what distinguishes a call from the definition and from
    # the comment that names it.
    assert APP.count("renderRoute();") == 1, (
        "renderRoute must have exactly one call site; a second one is a second "
        "interpretation of the same chain")
    body = APP[APP.index("function renderRoute()"):]
    body = body[:body.index("\nfunction ")]
    # A connection is the same airport twice; drawing it would be a zero-length
    # segment claiming a movement that did not happen.
    assert 'chain[k].kind !== "arr"' in body and "continue" in body


def test_flights_are_great_circles_and_ground_legs_are_not():
    """A flight really does follow a great circle, and Seoul to New York
    passes near the pole -- drawn as a straight line in longitude and latitude
    it would cross the Pacific instead. A ground leg is a straight line between
    two points the model never routed between, so it is drawn as one, dashed,
    rather than pretending to a path it does not have."""
    body = APP[APP.index("function renderRoute()"):]
    body = body[:body.index("\nfunction ")]
    assert 'add(greatCircle(a, b), "air")' in body
    assert 'unwrap([from, to]), "ground"' in body or 'unwrap([from, first]), "ground"' in body
    assert "function greatCircle" in APP and "function unwrap" in APP


def test_the_route_layers_exist_and_sit_under_the_pins():
    """Three layers: one dark halo under both kinds, then solid for air and
    dashed for ground -- line-dasharray is not data-driven in MapLibre, so one
    layer cannot do both. They are lifted above the borders with the rest, but
    before the pins, so a destination marker is never hidden by its own line."""
    for layer in ("route-halo", "route-air", "route-ground"):
        assert f'id: "{layer}"' in APP, f"{layer} is not added"
    lifted = APP[APP.index('for (const id of ["route-halo"'):]
    lifted = lifted[:lifted.index("]")]
    for layer in ("route-halo", "route-ground", "route-air"):
        assert layer in lifted, f"{layer} is not lifted above the borders"
    assert lifted.index("route-air") < lifted.index("pin-halo"), (
        "the route must be lifted before the pins, so the pins end up on top")


def test_the_boot_watchdog_tests_a_start_signal_not_the_visible_list():
    """It counted `.results button[data-slug]`, the SEARCH-FILTERED city list.

    Typing an airport code empties that list, and the page invites exactly
    that -- so twenty-five seconds after load the watchdog declared a healthy
    page broken, wiped a correct reading and wrote "The page could not start".
    Reproduced live: the writes to #time were "17 h 17 min" and then an em
    dash, while the itinerary below it still read ICN to JFK correctly.

    The signal has to be a fact about app.js having run to the end, and one a
    visitor cannot change.
    """
    assert 'dataset.appReady === "1"' in BOOT, "the watchdog does not test the start flag"
    assert "data-slug" not in BOOT, (
        "the watchdog is back to counting the search-filtered city list")
    # ...and app.js has to actually set it, as its last statement.
    assert 'document.documentElement.dataset.appReady = "1";' in APP
    assert APP.index("dataset.appReady") > APP.index("paintOrigin(requested"), (
        "the flag must be set after startup, not before it")


def test_the_boot_guard_does_not_write_an_em_dash():
    """say() put an em dash in #time, which is the 50px piece of punctuation
    the empty state exists to avoid, and it overwrote a correct reading. The
    message belongs in #where; #time is only cleared."""
    assert '"—"' not in BOOT, "the boot guard writes an em dash again"


def test_the_pointer_must_be_on_the_globe_before_it_is_read():
    """MapLibre's unproject does not tell you when it has left the Earth.

    Past the silhouette it CLAMPS to the nearest point on the limb and returns
    that same coordinate for every pixel further out. Measured live at zoom 2:
    every sample from 200 px to 640 px from centre returned 154.87W 8.50N while
    the round trip drifted from 30 px to 470 px. Eight directions were sampled
    and four of the clamp points land on inhabited ground, so the page reported
    a real town and a real travel time for a pointer sitting in black sky --
    at 225 degrees it read "Munster, Lower Saxony, Germany, 16 h 58 min" with
    the cursor 600 px out in space, and a click there pinned a destination in
    Germany.

    Both the hover readout and the click have to ask, because both take
    `e.lngLat` straight from the event.
    """
    assert "function onGlobe(point)" in APP
    move = APP[APP.index('map.on("mousemove"'):]
    move = move[:move.index("\nmap.on(")]
    assert "if (!onGlobe(e.point))" in move, "the hover readout reads space as a place"

    click = APP[APP.index('map.on("click"'):]
    click = click[:click.index("\n});") + 4]
    assert "if (!onGlobe(e.point)) return;" in click, "a click in space still pins"


def test_the_off_globe_tolerance_is_a_distance_not_a_guess():
    """project(unproject(p)) round-trips exactly on the globe and misses by the
    distance outside it beyond the limb, so the constant is a literal pixel
    tolerance. Measured: accepted to 1.37 px past the limb, refused from
    3.37 px, and the whole globe including the limb stays readable."""
    body = APP[APP.index("function onGlobe(point)"):]
    body = body[:body.index("\nfunction ")]
    assert "map.project(map.unproject(point))" in body, (
        "the test must be the round trip; nothing else measures how far out it is")
    assert "OFF_GLOBE_PX" in body
    tol = float(re.search(r"const OFF_GLOBE_PX = ([\d.]+);", APP).group(1))
    assert 0 < tol <= 3, f"{tol} px either rejects the limb itself or accepts open space"


def test_a_city_dot_is_anchored_by_the_dot_not_by_the_label_box():
    """A label carrying a dot claims the dot marks the city. It did not.

    With anchor "top" the coordinate is the top-centre of the whole box, which
    falls in the middle of the TEXT, while the dot sat to its left -- so the
    error grew with the length of the name. Measured live at zoom 5: 23 px
    from Tokyo, 27 from Beijing, 32 from Shanghai, 34 from Hangzhou, which is
    56 to 83 km on the ground. After: every dot within 1.2 px, 0.6 to 3 km,
    and that residue is places.json against origins.toml, not layout.

    Anchoring "left" puts the element's left edge, vertically centred, on the
    point, and the dot is placed there by CSS -- so no pixel offset exists to
    go stale when the font size changes at the phone breakpoint.
    """
    assert 'element: originLabel, anchor: "left"' in APP
    assert 'anchor: cityHere ? "left" : "top"' in APP, (
        "a bare place name should still hang below its point; only a dotted "
        "label is anchored by its dot")


def test_the_dot_is_a_real_element_positioned_by_css():
    """It was an inline ::before, so where it landed was a result of font
    metrics and margins rather than anything the code controlled."""
    assert "function setDottedLabel" in APP
    assert ".lbl.origin .dot{" in INDEX
    rule = INDEX[INDEX.index(".lbl.origin .dot{"):]
    rule = rule[:rule.index("}")]
    for part in ("position:absolute", "left:0", "top:50%", "margin:-2px 0 0 -2px"):
        assert part in rule, f"{part} missing from the dot rule: {rule}"


def test_the_label_does_not_override_maplibres_own_positioning():
    """The regression this fix first introduced, caught by measuring.

    MapLibre sets position:absolute on a marker element. Declaring
    position:relative on .lbl.origin overrode it, every label fell back into
    normal flow and stacked left to right, and Tokyo's dot ended up 726 km
    from Tokyo. An absolutely positioned element is already a containing block
    for its absolutely positioned children, so the dot needs nothing here.
    """
    rule = INDEX[INDEX.index(".lbl.origin{"):]
    rule = rule[:rule.index("}")]
    assert "position:relative" not in rule, (
        "position:relative overrides MapLibre's position:absolute and the "
        "markers stop being positioned at all")
