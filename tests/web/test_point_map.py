"""The map from a dropped point: asked for, waited on, drawn, read, abandoned.

The owner's request of 2026-10-04 (plan/2026-09-14-c13-solver-service.md,
"The map from any point"): a departure dragged away from the charted cities
gets the whole MAP from that point, from `/api/map`, and the wait for it must
be plain. Every rule below is a branch in `web/app.js`, so each is sliced out
and RUN under node against a stubbed network, a stubbed MapLibre and the real
vendored h3 -- a substring test of a branch passes while the branch is dead:

1. Armed only by index.json. Unarmed, a held point asks for nothing and says
   nothing; with a mode avoided it asks for nothing and says why.
2. While the map is computed, the reading panel AND the notice over the globe
   say so, with a Cancel, and the city's map stays on screen underneath.
3. When it lands it is drawn as res-4 hexagons in a GeoJSON layer under the
   coastline, the city's tile layer is hidden, every reading comes from the
   point's array, and the panel says it is the point's map, door to door, on
   a coarser grid.
4. Every failure -- each wire code, a captive portal, another build's array --
   leaves the city's map where it was, with the sentence why, and never
   reaches fatal().
5. Cancel and "Back to <city>'s map" drop the point and restore the city's
   layer; an answer that arrives after either is ignored.
6. `dep=` restores the point and asks for its map, armed; never otherwise.
7. A hexagon across the antimeridian is split into its two halves, as the
   pipeline splits it for the tiles.
"""

from __future__ import annotations

import base64
import json
import re
import shutil
import struct
import subprocess

import h3
import pytest

from tests.web import _js
from transport_maps import config

APP = (config.ROOT / "web" / "app.js").read_text(encoding="utf-8")
H3_JS = (config.ROOT / "web" / "vendor" / "h3.js").as_uri()

CONST_SRC = APP[APP.index("const SOLVER_PATH = "):]
CONST_SRC = CONST_SRC[:CONST_SRC.index("\n", CONST_SRC.index("let solverEnabled = ")) + 1]
CONSTS = "\n".join(_js.statement(a) for a in (
    "const SOLVER_MAP_PATH = ", "const SOLVER_MAP_VERSION = ", "const POINT_SOURCE = ",
    "const POINT_GRID = ", "const POINT_DRAW_MS = ", "const ANTIMERIDIAN_SPAN_DEG = ",
    "const EXACT_NOTE = ", "const POINT_NOTE = ", "const AVOIDABLE = "))
FUNCS = "\n".join(_js.function(n, with_async=True) for n in (
    "solveMap", "pointShown", "pointMapKey", "refreshPointMap", "startPointMap",
    "failPointMap", "endPointMap", "cancelPointMap", "retryPointMap", "drawPointLayer",
    "removePointLayer", "drawExactPoint", "hexSlice", "primeHexRings", "hexRing",
    "splitAtAntimeridian", "clipAtLongitude", "pointFeatures", "pointMapReading",
    "paintPointMap", "tickBusyClock", "stopBusyClock", "forgetExactFrom", "restoreDep",
    "refreshExact", "bandIndexOf", "fmtKm", "cellIndex", "lookupRaw", "carryOnSaving",
    "exactReading"))

CITIES = [
    {"slug": "seoul", "name": "Seoul", "lat": 37.5665, "lon": 126.978},
    {"slug": "tokyo", "name": "Tokyo", "lat": 35.6762, "lon": 139.6503},
]
# About 35 km from Seoul, the point a drag leaves behind.
POINT = {"lat": 37.80, "lon": 127.25}
URL = "./api/map?from=37.80000,127.25000"

# Five hover cells: the point's own, two neighbours, a cell on Fiji that
# straddles the antimeridian, and one far away. Sorted, as hover_cells.bin is.
CELLS = sorted({h3.latlng_to_cell(POINT["lat"], POINT["lon"], 4),
                h3.latlng_to_cell(37.5665, 126.978, 4),
                h3.latlng_to_cell(35.6762, 139.6503, 4),
                "849b5ddffffffff",
                h3.latlng_to_cell(-33.87, 151.21, 4)}, key=lambda c: int(c, 16))
WRAP = CELLS.index("849b5ddffffffff")
OWN = CELLS.index(h3.latlng_to_cell(POINT["lat"], POINT["lon"], 4))
MINUTES = [37, 65535, 430, 1210, 65535]
EDGES = [30, 45, 60, 120, 240, 480, 960, 1440, 2880]


def _times(minutes=MINUTES) -> str:
    return base64.b64encode(struct.pack(f"<{len(minutes)}H", *minutes)).decode()


def _body(**over) -> dict:
    body = {"v": 1, "status": "ok", "mapVersion": 1, "hoverRes": 4, "count": len(CELLS),
            "buildId": "b1", "snappedKm": 0.0, "snappedLat": 37.8, "snappedLon": 127.25,
            "times": _times()}
    body.update(over)
    return body


@pytest.fixture(scope="module")
def node() -> str:
    exe = shutil.which("node")
    if exe is None:
        pytest.skip("node is not on PATH; the page functions cannot be run")
    return exe


def _run(node: str, tmp_path, body: str) -> dict:
    script = tmp_path / "probe.mjs"
    # A request left hanging keeps the page's 45 s timeout and the overlay's
    # one-second clock alive, exactly as they should; the probe has said what
    # it came to say by then, so it leaves once stdout has drained.
    script.write_text(body + '\nawait new Promise((r) => process.stdout.write("", r));\n'
                      "process.exit(0);\n", encoding="utf-8")
    out = subprocess.run([node, str(script)], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


def _page(armed: bool = True, build_id: str | None = "b1") -> str:
    """The module state, the real functions, and stubs for the network, the
    map and the DOM. `requests[i].answer(body)` / `.status(code, body)` /
    `.html()` answer the i-th request; until then it hangs, as a 6 s solve
    does, which is what lets a test look at the loading state."""
    meta = {"origins": CITIES, "buildId": build_id, **({"solver": {"wire": 1}} if armed else {})}
    ids = ", ".join(f"0x{c}n" for c in CELLS)
    return f"""
import * as h3 from {json.dumps(H3_JS)};
class El {{
  constructor(tag = "div") {{ this.tag = tag; this.hidden = false; this.kids = []; this.attrs = {{}};
    this.dataset = {{}}; this.className = ""; this._text = null; this.on = {{}}; }}
  replaceChildren(...k) {{ this.kids = k; this._text = null; }}
  append(...k) {{ this.kids.push(...k); }}
  addEventListener(ev, fn) {{ this.on[ev] = fn; }}
  querySelector(sel) {{ const c = sel.replace(".", "");
    const walk = (n) => n.className === c ? n : (n.kids || []).map(walk).find(Boolean);
    return walk(this); }}
  set textContent(t) {{ this._text = t; this.kids = []; }}
  get textContent() {{ return this._text ?? this.kids.map((k) => k.textContent ?? k.text).join(""); }}
}}
globalThis.document = {{ createTextNode: (text) => ({{ text }}), createElement: (t) => new El(t) }};
const _els = {{ pointmap: new El(), pointbusy: new El() }};
_els.pointmap.hidden = _els.pointbusy.hidden = true;
const $ = (id) => (_els[id] ||= new El());
const buttons = (id) => {{ const out = [];
  const walk = (n) => {{ if (n.tag === "button") out.push(n); (n.kids || []).forEach(walk); }};
  walk($(id)); return out; }};
const click = (id, label) => buttons(id).find((b) => b.textContent === label).on.click();

const meta = {json.dumps(meta)};
const MAX_MINUTES = 65534, HOVER_RES = 4, UNREACHABLE = 65535, NO_AIRPORT = 0xFFFF;
const EDGES = {json.dumps(EDGES)};
const hoverCells = new BigUint64Array([{ids}]);
let lastReadingRes = HOVER_RES;
let exactFrom = null, exactAbort = null, exactKey = "", exactResult;
let pointMap = null, hexRings = null, busyClock = 0;
let pinB = null, avoid = null, carryOn = false, lastPointer = null;
let active = meta.origins[0];
const origin = {{ times: null, reading: null, air: null }};
const readingParents = null;
let notice = null;
const snapNotice = (...p) => {{ notice = p.length ? p.map((x) => typeof x === "string" ? x : x.b).join("") : null; }};
const said = [];
const announce = (t) => said.push(t);
const syncPermalink = () => {{}};
const paintExact = () => {{}};
const solvePoint = () => new Promise(() => {{}});
const fitReading = () => {{}};
let changed = 0;
const pointMapChanged = () => {{ changed++; }};
const bandColorExpression = () => ["get", "band"];
const fineRoute = () => null;
const readingIndex = () => -1;
const fmtCoord = (lat, lon) => `${{lat}},${{lon}}`;

// MapLibre, as far as these functions use it.
const layers = new Map([["bands", {{ vis: "visible" }}], ["water", {{ vis: "visible" }}]]);
const sources = new Map([["exactpt", {{ setData(d) {{ this.data = d; }} }}]]);
const handlers = {{}};
const map = {{
  getLayer: (id) => layers.get(id), getSource: (id) => sources.get(id),
  addSource: (id, spec) => sources.set(id, {{ spec }}),
  addLayer: (spec, before) => layers.set(spec.id, {{ spec, before, vis: "visible" }}),
  removeLayer: (id) => layers.delete(id), removeSource: (id) => sources.delete(id),
  setLayoutProperty: (id, k, v) => {{ layers.get(id).vis = v; }},
  on: (ev, fn) => (handlers[ev] ||= new Set()).add(fn),
  off: (ev, fn) => handlers[ev]?.delete(fn),
  isSourceLoaded: () => true,
}};
const fire = (ev, e) => [...(handlers[ev] || [])].forEach((fn) => fn(e));

const requests = [];
globalThis.fetch = (url, opts) => new Promise((resolve, reject) => {{
  const r = {{ url, signal: opts.signal,
    status: (status, body) => resolve({{ ok: status < 400, status, json: () => Promise.resolve(body) }}),
    html: () => resolve({{ ok: true, status: 200, json: () => Promise.reject(new SyntaxError("<html>")) }}) }};
  r.answer = (body) => r.status(200, body);
  opts.signal.addEventListener("abort", () => reject(opts.signal.reason), {{ once: true }});
  requests.push(r);
}});
const tick = () => new Promise((r) => setTimeout(r, 0));
const settle = async () => {{ for (let i = 0; i < 5; i++) await tick(); }};
const state = () => ({{
  calls: requests.length, url: requests[0]?.url ?? null,
  aborted: requests.map((r) => r.signal.aborted),
  pm: pointMap && {{ state: pointMap.state, key: pointMap.key }},
  panel: $("pointmap").hidden ? null : $("pointmap").kids[0].textContent,
  panelButtons: $("pointmap").hidden ? [] : buttons("pointmap").map((b) => b.textContent),
  busy: $("pointbusy").hidden ? null : $("pointbusy").textContent,
  busyButtons: $("pointbusy").hidden ? [] : buttons("pointbusy").map((b) => b.textContent),
  bands: layers.get("bands").vis,
  point: layers.has("pointbands") ? {{ before: layers.get("pointbands").before,
    tolerance: sources.get("pointbands").spec.tolerance }} : null,
  exactFrom, notice, said, changed,
  marker: sources.get("exactpt").data?.features.length ?? 0,
}});
{CONSTS}
{CONST_SRC}
{FUNCS}
"""


DROP = f"exactFrom = {json.dumps(POINT)};\nrefreshPointMap();\nawait settle();\n"


# ---------------------------------------------------------------- arming ---

def test_unarmed_a_held_point_asks_for_no_map_and_says_nothing(node, tmp_path):
    """The page without `solver` in index.json is the page as it was, even
    with a point held from a `dep=` link.

    Mutations performed and reverted, each red: drop `solverEnabled &&` from
    pointMapKey (solveMap's own guard answers, but the panel then shows a
    failure for a service the page never offered); drop it from
    drawExactPoint (the point is drawn on the globe for a map never asked for).
    """
    got = _run(node, tmp_path, _page(armed=False) + DROP + "console.log(JSON.stringify(state()));")
    assert got["calls"] == 0 and got["pm"] is None
    assert got["panel"] is None and got["busy"] is None and got["marker"] == 0


def test_with_a_mode_avoided_no_map_is_asked_for_and_the_panel_says_why(node, tmp_path):
    """The service solves the full network; a map from it under "avoid
    flights" would measure other journeys from everything else on screen.
    Clearing the avoided mode asks for the map.

    Mutation performed and reverted: drop `!avoid` from pointMapKey -> red.
    """
    got = _run(node, tmp_path, _page() + 'avoid = "air";\n' + DROP + """
const during = state();
avoid = null;
refreshPointMap();
await settle();
console.log(JSON.stringify({ during, after: state() }));
""")
    assert got["during"]["calls"] == 0
    assert got["during"]["panel"] == (
        "No map is computed from the point you chose while the map avoids flights: the "
        "service that computes it uses every mode. The map is Seoul's, the nearest charted "
        "departure city.")
    assert got["after"]["calls"] == 1 and got["after"]["url"] == URL


# ---------------------------------------------------------- loading state ---

def test_while_it_computes_both_the_panel_and_the_globe_say_so(node, tmp_path):
    """The owner's one requirement. One request, the city's layer still on
    screen, the panel and the notice over the globe both saying what is
    happening and that the city's map stays until it is ready, each with a
    Cancel -- and the dropped point drawn on the globe.

    Mutations performed and reverted, each red: drop `busy` from the loading
    branch of pointMapReading; skip paintPointMap in refreshPointMap; hide the
    bands layer in startPointMap.
    """
    got = _run(node, tmp_path, _page() + DROP + "console.log(JSON.stringify(state()));")
    assert got["calls"] == 1 and got["url"] == URL
    assert got["pm"] == {"state": "loading", "key": "37.80000,127.25000"}
    assert got["bands"] == "visible" and got["point"] is None
    title = "Computing travel times from the point you chose…"
    sub = "This takes a few seconds. Seoul's map stays on screen until it is ready."
    assert got["panel"] == f"{title} {sub}" and got["panelButtons"] == ["Cancel"]
    # The title, the sentence, the seconds so far, then the button's label.
    assert got["busy"] == f"{title}{sub}0 sCancel", "the overlay is not saying the wait"
    assert got["busyButtons"] == ["Cancel"]
    assert got["marker"] == 1
    assert "Computing travel times from the point you chose. This takes a few seconds." in got["said"]


def test_the_answer_is_drawn_under_the_coast_and_every_reading_comes_from_it(node, tmp_path):
    """Drawing, then shown once MapLibre says the source has loaded: the
    GeoJSON layer goes in before `water`, unsimplified; the city's tile layer
    is hidden, not removed; the panel names the point's map, door to door, on
    the coarser grid; lookupRaw reads the point's array at res 4.

    Mutations performed and reverted, each red: add the layer without the
    `"water"` anchor; drop `tolerance: 0`; skip hiding "bands"; read
    `origin.times` in lookupRaw regardless; leave the overlay up when shown.
    """
    got = _run(node, tmp_path, _page() + DROP + f"""
requests[0].answer({json.dumps(_body())});
await settle();
const drawing = state();
fire("sourcedata", {{ sourceId: "pointbands" }});
const shown = state();
lastReadingRes = 6;
const own = lookupRaw({POINT["lat"]}, {POINT["lon"]});
const res = lastReadingRes;
const sea = lookupRaw(0, -30);
console.log(JSON.stringify({{ drawing, shown, own, res, sea }}));
""")
    d, s = got["drawing"], got["shown"]
    assert d["pm"]["state"] == "drawing" and d["bands"] == "visible"
    assert d["panel"].startswith("Drawing the map from the point you chose…")
    assert d["point"] == {"before": "water", "tolerance": 0}
    assert s["pm"]["state"] == "shown" and s["bands"] == "none" and s["busy"] is None
    assert s["panel"] == (
        "This map is measured from the point you chose, door to door, computed on demand "
        "on a grid of cells about 45 km across (22 km a side), coarser than a charted "
        "city's map.")
    assert s["panelButtons"] == ["Back to Seoul's map"]
    assert s["changed"] == 1, "the readings were not redone when the map changed hands"
    assert "The map from the point you chose is ready. Its times are door to door." in s["said"]
    assert got["own"] == MINUTES[OWN] and got["res"] == 4 and got["sea"] is None


def test_a_moved_point_and_carry_on_are_said(node, tmp_path):
    """Mutation performed and reverted: drop the `bag` clause -> red."""
    got = _run(node, tmp_path, _page() + "carryOn = true;\n" + DROP + f"""
requests[0].answer({json.dumps(_body(snappedKm=4.2))});
await settle();
fire("sourcedata", {{ sourceId: "pointbands" }});
console.log(JSON.stringify(state()));
""")
    assert got["panel"].endswith("coarser than a charted city's map. The point was moved 4 km "
                                 "to the nearest land. Its times assume a checked bag.")


def test_carry_on_takes_nothing_off_a_point_maps_reading(node, tmp_path):
    """The point's array does not say which cells were reached by air, so the
    city's airport arrays must not be read for a saving under it.

    Mutation performed and reverted: drop `|| pointShown()` from
    carryOnSaving -> red.
    """
    got = _run(node, tmp_path, _page() + "carryOn = true;\n"
               "meta.carryOn = { departureMin: 15, arrivalMin: 10 };\n"
               "origin.air = new Uint16Array(5).fill(3);\n" + DROP + f"""
const before = carryOnSaving({POINT["lat"]}, {POINT["lon"]});
requests[0].answer({json.dumps(_body())});
await settle();
fire("sourcedata", {{ sourceId: "pointbands" }});
console.log(JSON.stringify({{ before, after: carryOnSaving({POINT["lat"]}, {POINT["lon"]}) }}));
""")
    assert got == {"before": 25, "after": 0}


# -------------------------------------------------------------- failures ---

@pytest.mark.parametrize("code,status", [
    ("not_on_land", 422), ("busy", 503), ("timeout", 504), ("unavailable", 503),
    ("bad_request", 400), ("out_of_range", 400), ("teapot", 418)])
def test_every_failure_keeps_the_citys_map_and_says_why(node, tmp_path, code, status):
    """Each wire code (and one the page does not know) ends with the city's
    map on screen, no point layer, the overlay gone, the code's sentence and
    the city it is still measured from, and a Try again that asks again.

    Mutations performed and reverted, each red: leave the overlay up on
    failure (skip stopBusyClock + the busy branch); drop SOLVER_FALLBACK from
    the failed branch; make Try again a no-op.
    """
    got = _run(node, tmp_path, _page() + DROP + f"""
requests[0].status({status}, {{ v: 1, status: "error", code: {json.dumps(code)}, message: "x" }});
await settle();
const failed = state();
click("pointmap", "Try again");
await settle();
console.log(JSON.stringify({{ failed, retried: state() }}));
""")
    f = got["failed"]
    want = {"teapot": "unavailable"}.get(code, code)
    sentence = {
        "not_on_land": "There is no land within about 13 km of that point, so there is nothing to depart from.",
        "busy": "Too many points are being computed at once.",
        "timeout": "That point took too long to compute.",
        "unavailable": "The service that computes an uncharted departure did not answer.",
        "bad_request": "That point could not be computed.",
        "out_of_range": "That point is not on the Earth.",
    }[want]
    assert f["pm"]["state"] == "failed" and f["busy"] is None and f["point"] is None
    assert f["bands"] == "visible"
    assert f["panel"] == ("The map from the point you chose could not be computed. " + sentence
                          + " The times on the map are still measured from Seoul, the nearest "
                            "charted departure city.")
    assert f["panelButtons"] == ["Try again"]
    assert got["retried"]["calls"] == 2 and got["retried"]["pm"]["state"] == "loading"


UNTRUSTED = [
    ("a captive portal's HTML", "requests[0].html();"),
    ("another wire version", f"requests[0].answer({json.dumps(_body(v=2))});"),
    ("another map layout", f"requests[0].answer({json.dumps(_body(mapVersion=2))});"),
    ("another build", f"requests[0].answer({json.dumps(_body(buildId='b0'))});"),
    ("another grid", f"requests[0].answer({json.dumps(_body(hoverRes=5))});"),
    # Four cells, consistently: only the count against hover_cells.bin says no.
    ("another cell count",
     f"requests[0].answer({json.dumps(_body(count=4, times=_times(MINUTES[:4])))});"),
    ("a short array", f"requests[0].answer({json.dumps(_body(times=_times(MINUTES[:4])))});"),
    ("not base64", f"requests[0].answer({json.dumps(_body(times='%%%%'))});"),
    ("no snap distance", f"requests[0].answer({json.dumps(_body(snappedKm=None))});"),
    ("an ok status with a 500", f"requests[0].status(500, {json.dumps(_body())});"),
]


@pytest.mark.parametrize("why,answer", UNTRUSTED,
                         ids=[why.replace(" ", "_").replace("'", "") for why, _ in UNTRUSTED])
def test_an_answer_the_page_cannot_trust_is_unavailable(node, tmp_path, why, answer):
    """Each of these would otherwise paint plausible times in the wrong place,
    or throw. All end as `unavailable`, with the city's map on screen.

    Mutations performed and reverted, each red on its row: drop the buildId
    test; drop the count test; drop the decoded-length test; drop the
    mapVersion test.
    """
    got = _run(node, tmp_path, _page() + DROP + answer + """
await settle();
console.log(JSON.stringify(state()));
""")
    assert got["pm"]["state"] == "failed", why
    assert "The service that computes an uncharted departure did not answer." in got["panel"], why
    assert got["point"] is None and got["bands"] == "visible", why


def test_a_build_with_no_id_does_not_refuse_every_map(node, tmp_path):
    """An index.json from before `buildId` cannot be compared; the count and
    the grid still are."""
    got = _run(node, tmp_path, _page(build_id=None) + DROP + f"""
requests[0].answer({json.dumps(_body(buildId=None))});
await settle();
console.log(JSON.stringify(state()));
""")
    assert got["pm"]["state"] == "drawing"


def test_no_path_reaches_fatal():
    """`fatal()` hides the rail: a solver outage reaching it would delete the
    city list and the legend over a map that is still correct.

    Mutation performed and reverted: a `fatal("...")` in failPointMap -> red.
    """
    for name in ("solveMap", "startPointMap", "failPointMap", "drawPointLayer",
                 "refreshPointMap", "paintPointMap", "pointFeatures", "restoreDep"):
        code = re.sub(r"//[^\n]*", "", _js.function(name, with_async=True))
        assert "fatal(" not in code and "fetchOk(" not in code, name


# ------------------------------------------------------- cancel and back ---

def test_cancel_while_it_computes_goes_back_to_the_city(node, tmp_path):
    """Cancel aborts the request, drops the point and its marker, clears both
    notices, and what the abandoned request does next is ignored.

    Mutations performed and reverted, each red: drop `pm.ctl.abort` from
    endPointMap; drop the `pointMap !== pm` test in startPointMap's answer
    (the abort's own rejection is then announced as a failure).
    """
    got = _run(node, tmp_path, _page() + DROP + f"""
click("pointbusy", "Cancel");
await settle();
requests[0].answer({json.dumps(_body())});
await settle();
console.log(JSON.stringify(state()));
""")
    assert got["aborted"] == [True]
    assert got["exactFrom"] is None and got["pm"] is None and got["marker"] == 0
    assert got["panel"] is None and got["busy"] is None
    assert got["point"] is None and got["bands"] == "visible"
    assert "Back to Seoul's map." in got["said"]
    # The abandoned request rejects as it is aborted; that rejection is not a
    # failure of anything the visitor still wants, and must not be announced.
    assert not any("could not be computed" in s for s in got["said"]), got["said"]


def test_back_to_the_city_removes_the_points_map(node, tmp_path):
    """Mutation performed and reverted: skip removePointLayer in endPointMap
    -> red (the layer stays, the city's stays hidden)."""
    got = _run(node, tmp_path, _page() + DROP + f"""
requests[0].answer({json.dumps(_body())});
await settle();
fire("sourcedata", {{ sourceId: "pointbands" }});
click("pointmap", "Back to Seoul's map");
await settle();
console.log(JSON.stringify(state()));
""")
    assert got["point"] is None and got["bands"] == "visible"
    assert got["exactFrom"] is None and got["pm"] is None and got["panel"] is None
    assert got["changed"] == 2, "the readings were not redone when the city's map came back"


def test_moving_the_point_abandons_the_request_in_flight(node, tmp_path):
    """Mutation performed and reverted: in refreshPointMap, start without
    ending the previous map -> red (the first request is never aborted)."""
    got = _run(node, tmp_path, _page() + DROP + """
exactFrom = { lat: 37.9, lon: 127.3 };
refreshPointMap();
await settle();
console.log(JSON.stringify(state()));
""")
    assert got["calls"] == 2 and got["aborted"] == [True, False]
    assert got["pm"]["key"] == "37.90000,127.30000"


def test_refreshing_the_exact_line_refreshes_the_map():
    """Every route that moves, drops or restores the point ends in
    refreshExact(), so that is where the map is kept in step.

    Mutation performed and reverted: delete `refreshPointMap();` from
    refreshExact -> red.
    """
    assert _js.function("refreshExact").split("{", 1)[1].lstrip().startswith("refreshPointMap();")


# ------------------------------------------------------------- permalink ---

@pytest.mark.parametrize("armed", [True, False])
def test_dep_restores_the_point_and_asks_for_its_map_only_when_armed(node, tmp_path, armed):
    """Mutation performed and reverted: drop `refreshExact()` from restoreDep
    -> red on the armed row (no request). The unarmed row holds that nothing
    is asked, said or drawn; every function restoreDep could reach checks
    solverEnabled on its own, and test_unarmed_a_held_point... mutates those."""
    got = _run(node, tmp_path, _page(armed=armed) + f"""
restoreDep({json.dumps(POINT)}, meta.origins[0]);
await settle();
console.log(JSON.stringify(state()));
""")
    assert got["exactFrom"] == POINT
    if armed:
        assert got["calls"] == 1 and got["pm"]["state"] == "loading"
        assert got["notice"] == ("Seoul is the nearest departure city to the point in this "
                                 "link. The map from that exact point is computed on demand.")
    else:
        assert got["calls"] == 0 and got["notice"] is None and got["marker"] == 0


# -------------------------------------------------------------- geometry ---

def test_hexagons_are_h3s_own_outlines_and_split_at_the_antimeridian(node, tmp_path):
    """An ordinary cell is its h3 boundary, closed. The Fiji cell is two
    polygons, both inside [-180, 180], meeting on the meridian, whose areas add
    up to the cell's own -- what contour/bands.py `_split_at_antimeridian`
    gives the tiles.

    Mutations performed and reverted, each red: drop the split (draw the
    wrapping cell whole); shift the east piece by +360 instead of -360; keep
    only the west piece.
    """
    got = _run(node, tmp_path, _page() + f"""
const fc = pointFeatures(new Uint16Array({json.dumps(MINUTES)}));
const own = hexRing({OWN});
const ownH3 = h3.cellToBoundary(hoverCells[{OWN}].toString(16)).map(([y, x]) => [x, y]);
const halves = hexRings.split.get({WRAP});
// Shoelace, in the unwrapped frame for the cell and per piece for the halves.
const area = (r) => Math.abs(r.slice(0, -1).reduce((s, [x, y], k) => s + x * r[k + 1][1] - r[k + 1][0] * y, 0)) / 2;
const whole = h3.cellToBoundary(hoverCells[{WRAP}].toString(16)).map(([y, x]) => [x < 0 ? x + 360 : x, y]);
whole.push(whole[0]);
console.log(JSON.stringify({{
  bands: fc.features.map((f) => [f.properties.band, f.geometry.coordinates.length]).sort((a, b) => a[0] - b[0]),
  ownClosed: JSON.stringify(own[0]) === JSON.stringify(own[own.length - 1]),
  ownMatches: JSON.stringify(own.slice(0, -1)) === JSON.stringify(ownH3),
  pieces: halves.length,
  inRange: halves.every(([r]) => r.every(([x]) => x >= -180 && x <= 180)),
  onMeridian: halves.map(([r]) => r.some(([x]) => Math.abs(Math.abs(x) - 180) < 1e-9)),
  areas: [halves.reduce((s, [r]) => s + area(r), 0), area(whole)],
}}));
""")
    assert got["ownClosed"] and got["ownMatches"]
    assert got["pieces"] == 2 and got["inRange"] and got["onMeridian"] == [True, True]
    assert got["areas"][0] == pytest.approx(got["areas"][1], rel=1e-9)
    # One feature per band, -1 for no route, each holding its cells' polygons:
    # 37 min is band 1, 430 band 5, the two unreachable cells -1, and 1210
    # band 7 -- which is the Fiji cell, so it holds that cell's two halves.
    by = dict(map(tuple, got["bands"]))
    assert by == {-1: 2, 1: 1, 5: 1, 7: 2}, got["bands"]


def test_the_scheme_repaints_the_points_layer_too():
    """A colour scheme picked while the point's map is up must reach it.

    Mutation performed and reverted: back to `if (map.getLayer("bands"))`
    alone in pickRamp -> red.
    """
    body = _js.function("pickRamp")
    assert re.search(r'for \(const id of \["bands", POINT_SOURCE\]\)', body)
    assert 'setPaintProperty(id, "fill-color", bandColorExpression())' in body
