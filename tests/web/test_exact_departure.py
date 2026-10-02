"""The exact departure point: kept from a drag, asked of the solver, printed
as one extra line -- and none of it unless index.json arms the solver.

The interaction is the one plan/2026-09-14-c13-solver-service.md adopted: the
drag still snaps the MAP to the nearest charted city at once, and the point it
was dropped on (`exactFrom`) gets its own number from `/api/solve` once a
destination is pinned. The headline stays the city's.

Every function here is sliced out of `web/app.js` and RUN under node against
stubs, because each rule below is a branch, and a substring test of a branch
passes while the branch is dead:

1. Unarmed, nothing changes: no point is kept, the notice reads as it did, and
   no request is made whatever the state.
2. A drop more than a kilometre from the city keeps the point; any other route
   to a departure (the list, a permalink, "Depart from", a city's label)
   drops it, through paintOrigin, BEFORE its same-city guard.
3. A request goes out only with both points, once per pair, and the one in
   flight is abandoned when either point moves.
4. The extra line says what the answer is -- door to door, computed on
   demand, how far the point was moved -- and every failure names the city the
   map is still measured from.
5. `dep=` is restored only beside a `from=` naming the city nearest to it.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess

import pytest

from tests.web import _js
from transport_maps import config

APP = (config.ROOT / "web" / "app.js").read_text(encoding="utf-8")

# The SOLVER_* constants and the initialiser that arms them, as
# test_solver_client.py slices them.
CONST_SRC = APP[APP.index("const SOLVER_PATH = "):]
CONST_SRC = CONST_SRC[:CONST_SRC.index("\n", CONST_SRC.index("let solverEnabled = ")) + 1]

FN = {name: _js.function(name, with_async=True) for name in (
    "solvePoint", "exactReading", "refreshExact", "paintExact", "forgetExactFrom",
    "parseDep", "originDragEnd", "paintOrigin", "nearestOrigin", "haversineKm",
    "fmtKm", "fmtTime", "paintExactLegs", "exactLegRows", "solverAirport", "carryOnExact")}
CONSTS = "\n".join(_js.statement(a) for a in (
    "const EXACT_MIN_KM = ", "const EXACT_NOTE = ", "const fmtDur = ", "const AVOIDABLE = ",
    "const MODE_FALLBACK = "))

CITIES = [
    {"slug": "seoul", "name": "Seoul", "lat": 37.5665, "lon": 126.978},
    {"slug": "tokyo", "name": "Tokyo", "lat": 35.6762, "lon": 139.6503},
]
SEOUL, TOKYO = CITIES

# The page's sentences, stated once here so a test failing on copy says so.
LOADING = "Computing the time from the exact point you chose…"
FALLBACK_SEOUL = "The times on the map are still measured from Seoul"


@pytest.fixture(scope="module")
def node() -> str:
    exe = shutil.which("node")
    if exe is None:
        pytest.skip("node is not on PATH; the page functions cannot be run")
    return exe


def _run(node: str, tmp_path, body: str) -> dict:
    script = tmp_path / "probe.mjs"
    script.write_text(body, encoding="utf-8")
    out = subprocess.run([node, str(script)], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


# A DOM just big enough for paintExact, paintExactLegs and snapNotice-shaped
# parts. `html()` serialises a subtree, so a test reads what was built --
# element, class, attributes, text -- rather than what a helper returned.
_DOM = """
class El {
  constructor(tag = "p"){ this.tag = tag; this.hidden = true; this.kids = []; this.attrs = {};
    this.className = ""; this._text = null; }
  replaceChildren(...k){ this.kids = k; this._text = null; }
  append(...k){ this.kids.push(...k); }
  setAttribute(k, v){ this.attrs[k] = String(v); }
  set textContent(t){ this._text = t; this.kids = []; }
  get textContent(){ return this._text ?? this.kids.map((k) => k.textContent ?? k.text).join(""); }
}
const html = (n) => {
  if (n.text !== undefined) return n.text;
  const attrs = (n.className ? ` class="${n.className}"` : "")
    + Object.entries(n.attrs).map(([k, v]) => ` ${k}="${v}"`).join("");
  return `<${n.tag}${attrs}>${n._text ?? n.kids.map(html).join("")}</${n.tag}>`;
};
globalThis.document = {
  createTextNode: (text) => ({ text }),
  createElement: (tag) => { const e = new El(tag); e.hidden = false; return e; },
};
const _els = {};
const $ = (id) => (_els[id] ||= new El());
"""


def _page(armed: bool) -> str:
    """The module state and the real functions, with the network stubbed.

    `respond(i, body)` answers the i-th request; until then it hangs, which is
    what lets a test move a point while a request is in flight.
    """
    meta = {"origins": CITIES, **({"solver": {"wire": 1}} if armed else {})}
    return f"""
{_DOM}
const meta = {json.dumps(meta)};
const MAX_MINUTES = 65534;
const store = {{ get: () => true, set: () => {{}} }};
let exactFrom = null, exactAbort = null, exactKey = "", exactResult;
let pinB = null, avoid = null, carryOn = false, active = null;
const said = [];
const announce = (t) => said.push(t);
const fitReading = () => {{}};
const requests = [];
globalThis.fetch = (url, opts) => new Promise((resolve, reject) => {{
  const r = {{ url, signal: opts.signal,
    answer: (body) => resolve({{ ok: true, status: 200, json: () => Promise.resolve(body) }}) }};
  opts.signal.addEventListener("abort", () => reject(opts.signal.reason), {{ once: true }});
  requests.push(r);
}});
const tick = () => new Promise((r) => setTimeout(r, 0));
// The city's routes file and airports.json, as the page holds them: two
// airports, ICN (ordinal 0) and EWR (ordinal 2) after 100 cells, with four
// airports in the build, so the arrival nodes start at 104. JFK (ordinal 1)
// is in the build but not in this city's routes file.
const origin = {{ routes: {{ offsets: {{ cells: 0, airports: 100, stations: 108 }},
  byId: new Map([[100, {{ id: 100, kind: "dep", code: "ICN" }}],
                 [106, {{ id: 106, kind: "arr", code: "EWR" }}]]) }} }};
let airports = [["ICN", "Incheon International Airport", "KR", 37.46, 126.44, "large"],
                ["EWR", "Newark Liberty International Airport", "US", 40.69, -74.17, "large"]];
const countryName = (cc) => ({{ KR: "South Korea", US: "United States" }})[cc] ?? cc;
{CONSTS}
{CONST_SRC}
{FN["fmtTime"]}
{FN["fmtKm"]}
{FN["solvePoint"]}
{FN["exactReading"]}
{FN["carryOnExact"]}
{FN["refreshExact"]}
{FN["paintExact"]}
{FN["solverAirport"]}
{FN["exactLegRows"]}
{FN["paintExactLegs"]}
"""


OK = {"v": 1, "status": "ok", "reachable": True, "minutes": 432,
      "snappedKm": 0.0, "snappedLat": 37.6, "snappedLon": 127.1}


# ---------------------------------------------------------------- arming ---

def test_unarmed_nothing_reaches_the_network_and_nothing_is_shown(node, tmp_path):
    """The page with no `solver` in index.json is the page as it was.

    Mutation performed and reverted: drop `solverEnabled &&` from
    refreshExact's key -> red (a request is attempted; only solvePoint's own
    guard stops it reaching the network). Drop it from paintExact's test
    instead -> red (the line is shown under a map that offered nothing).
    """
    got = _run(node, tmp_path, _page(armed=False) + """
exactFrom = { lat: 37.60, lon: 127.10 };
pinB = { lat: 35.68, lon: 139.65, label: "Tokyo" };
active = meta.origins[0];
refreshExact();
await tick(); await tick();
console.log(JSON.stringify({ calls: requests.length, hidden: $("exact").hidden,
  text: $("exact").textContent, key: exactKey }));
""")
    assert got["calls"] == 0, "the solver is not armed and a request was made"
    assert got["hidden"] is True and got["text"] == ""
    assert got["key"] == ""


@pytest.mark.parametrize("have", ["neither", "exact only", "destination only"])
def test_a_request_needs_both_points(node, tmp_path, have):
    """Mutation performed and reverted: drop `pinB &&` from refreshExact's key
    -> red on "exact only" (it throws reading pinB.lat). Drop `exactFrom &&`
    -> red on "destination only".
    """
    setup = {
        "neither": "",
        "exact only": "exactFrom = { lat: 37.60, lon: 127.10 };",
        "destination only": 'pinB = { lat: 35.68, lon: 139.65, label: "Tokyo" };',
    }[have]
    got = _run(node, tmp_path, _page(armed=True) + setup + """
active = meta.origins[0];
refreshExact();
await tick();
console.log(JSON.stringify({ calls: requests.length, hidden: $("exact").hidden }));
""")
    assert got == {"calls": 0, "hidden": True}


def test_armed_with_both_points_one_request_goes_out_and_its_answer_is_printed(node, tmp_path):
    """The whole happy path through the real solvePoint: the line says it is
    computing, then says the answer -- door to door, computed on demand -- and
    the answer, not the loading line, is announced.

    Mutation performed and reverted: delete `paintExact(true)` from the
    response handler -> red (the line stays on "Computing…").
    """
    got = _run(node, tmp_path, _page(armed=True) + f"""
exactFrom = {{ lat: 37.60123, lon: 127.10456 }};
pinB = {{ lat: 35.68, lon: 139.65, label: "Tokyo" }};
active = meta.origins[0];
refreshExact();
const before = $("exact").textContent, shownBefore = !$("exact").hidden;
// Every other renderPins() before the answer lands: the same pair, no new request.
refreshExact(); refreshExact();
const calls = requests.length;
requests[0].answer({json.dumps(OK)});
await tick(); await tick();
console.log(JSON.stringify({{ before, shownBefore, calls, url: requests[0].url,
  after: $("exact").textContent, said }}));
""")
    assert got["calls"] == 1, "re-rendering the same pair asked the server again"
    assert got["url"] == "./api/solve?from=37.60123,127.10456&to=35.68000,139.65000"
    assert got["shownBefore"] and got["before"] == LOADING
    assert got["after"] == ("From the exact point you chose: 7 h 12 min door to door, "
                            "computed on demand.")
    assert got["said"] == [got["after"]], "the answer was not announced, or the loading line was"


def test_moving_either_point_abandons_the_request_in_flight(node, tmp_path):
    """A late answer for the old pair must not land on the new one.

    Mutation performed and reverted: delete `exactAbort?.abort("cancelled")`
    -> red (the first request is never aborted). Delete the `exactAbort !==
    ctl` check as well -> red (the stale answer is printed).
    """
    got = _run(node, tmp_path, _page(armed=True) + f"""
exactFrom = {{ lat: 37.60, lon: 127.10 }};
pinB = {{ lat: 35.68, lon: 139.65, label: "Tokyo" }};
active = meta.origins[0];
refreshExact();
pinB = {{ lat: 34.69, lon: 135.50, label: "Osaka" }};
refreshExact();
const firstAborted = requests[0].signal.aborted;
exactFrom = {{ lat: 37.50, lon: 127.00 }};
refreshExact();
const secondAborted = requests[1].signal.aborted;
// The abandoned requests have settled by now -- solvePoint turns a cancel
// into `unavailable` -- and that must be neither printed nor announced while
// the current pair is still being computed.
await tick(); await tick();
const meanwhile = $("exact").textContent, saidMeanwhile = said.slice();
requests[2].answer({json.dumps(dict(OK, minutes=95))});
await tick(); await tick();
console.log(JSON.stringify({{ calls: requests.length, firstAborted, secondAborted,
  meanwhile, saidMeanwhile, text: $("exact").textContent }}));
""")
    assert got["calls"] == 3
    assert got["firstAborted"] and got["secondAborted"]
    assert got["meanwhile"] == LOADING, "an abandoned request's outcome was printed"
    assert got["saidMeanwhile"] == [], "an abandoned request's outcome was announced"
    assert "1 h 35 min door to door" in got["text"]


def test_no_request_while_the_map_avoids_a_mode(node, tmp_path):
    """The service solves the full network. A figure from it beside a
    no-flights map would measure a different journey from every other number.

    Mutation performed and reverted: drop `&& !avoid` from the key -> red.
    """
    got = _run(node, tmp_path, _page(armed=True) + """
exactFrom = { lat: 37.60, lon: 127.10 };
pinB = { lat: 35.68, lon: 139.65, label: "Tokyo" };
active = meta.origins[0];
avoid = "air";
refreshExact();
await tick();
console.log(JSON.stringify({ calls: requests.length, text: $("exact").textContent }));
""")
    assert got["calls"] == 0
    assert "while the map avoids flights" in got["text"]


# ------------------------------------------------------- what it says ---

def _reading(node, tmp_path, res, **opts) -> str:
    """exactReading's parts, joined the way paintExact joins them."""
    return _run(node, tmp_path, _page(armed=True) + f"""
const parts = exactReading({json.dumps(res) if res is not None else "undefined"},
                           {json.dumps(opts)});
console.log(JSON.stringify(parts.map((p) => typeof p === "string" ? p : p.b).join("")));
""")


@pytest.mark.parametrize("res,opts,expected", [
    (None, {}, LOADING),
    ({"ok": True, "reachable": True, "minutes": 432, "snappedKm": 0.0}, {},
     "From the exact point you chose: 7 h 12 min door to door, computed on demand."),
    # Moved, and said so -- a figure measured somewhere else needs disclosing.
    ({"ok": True, "reachable": True, "minutes": 432, "snappedKm": 4.2}, {},
     "From the exact point you chose: 7 h 12 min door to door, computed on demand. "
     "The point was moved 4 km to the nearest land."),
    # Inside one solve cell: not worth a sentence.
    ({"ok": True, "reachable": True, "minutes": 432, "snappedKm": 0.5}, {},
     "From the exact point you chose: 7 h 12 min door to door, computed on demand."),
    ({"ok": True, "reachable": False, "minutes": None, "snappedKm": 0.0}, {},
     "From the exact point you chose: no scheduled route to this destination, "
     "computed on demand."),
    ({"ok": True, "reachable": True, "minutes": 432, "snappedKm": 0.0}, {"carryOnOn": True},
     "From the exact point you chose: 7 h 12 min door to door, computed on demand. "
     "It assumes a checked bag."),
])
def test_the_line_for_each_answer(node, tmp_path, res, opts, expected):
    """Mutation performed and reverted: `snappedKm > 0.5` -> `>= 0.5` -> red
    on the 0.5 row; drop `door to door` -> red on every reachable row.
    """
    assert _reading(node, tmp_path, res, **opts) == expected


@pytest.mark.parametrize("code,status", [
    ("not_on_land", 422), ("busy", 503), ("timeout", 504),
    ("unavailable", 503), ("bad_request", 400), ("out_of_range", 400),
    ("teapot", 418),                    # a code this page does not know
])
def test_every_failure_names_the_city_the_map_is_still_measured_from(node, tmp_path,
                                                                      code, status):
    """Through the REAL solvePoint, from the wire body the service sends, so a
    code the client and the line disagree about cannot pass.

    Mutation performed and reverted: drop `+ SOLVER_FALLBACK(city)` -> red on
    every row. Print `res.code` instead of `res.message` -> red.
    """
    body = {"v": 1, "status": "error", "code": code, "message": "server text"}
    got = _run(node, tmp_path, _page(armed=True) + f"""
exactFrom = {{ lat: 37.60, lon: 127.10 }};
pinB = {{ lat: 35.68, lon: 139.65, label: "Tokyo" }};
active = meta.origins[0];
refreshExact();
requests[0].answer({json.dumps(body)});
await tick(); await tick();
console.log(JSON.stringify({{ text: $("exact").textContent,
  message: SOLVER_CODES[{json.dumps(code)}] ?? SOLVER_CODES.unavailable }}));
""")
    text = got["text"]
    assert text.startswith("The time from the exact point you chose could not be computed. ")
    assert got["message"] in text, "the wire code's sentence is not in the line"
    assert "server text" not in text, "the service's own message text reached the page"
    assert FALLBACK_SEOUL in text


def test_a_captive_portal_is_a_failure_line_not_a_crash(node, tmp_path):
    """HTML with HTTP 200: solvePoint calls it unavailable, and the line says
    so and names the city rather than painting nothing."""
    got = _run(node, tmp_path, _page(armed=True) + """
exactFrom = { lat: 37.60, lon: 127.10 };
pinB = { lat: 35.68, lon: 139.65, label: "Tokyo" };
active = meta.origins[0];
globalThis.fetch = () => Promise.resolve({ ok: true, status: 200,
  json: () => Promise.reject(new SyntaxError("Unexpected token <")) });
refreshExact();
await tick(); await tick(); await tick();
console.log(JSON.stringify({ text: $("exact").textContent }));
""")
    assert "did not answer" in got["text"] and FALLBACK_SEOUL in got["text"]


# ------------------------------------------------------- the legs ---

# Seoul to New York as the service sends it: ordinals 0 (ICN), 2 (EWR) and 1
# (JFK, which this city's routes file does not list). 140 + 830 + 95 + 61 +
# 92 = 1,218 minutes, 20 h 18 min.
LEGS = [
    {"kind": "surface", "min": 140, "railMin": 52},
    {"kind": "fly", "from": 0, "to": 2, "min": 830},
    {"kind": "connect", "at": 2, "min": 95},
    {"kind": "fly", "from": 2, "to": 1, "min": 61},
    {"kind": "surface", "min": 92, "railMin": 0},
]
WITH_LEGS = dict(OK, minutes=1218, legs=LEGS)
ICN = ('<span class="ap" tabindex="0" '
       'data-tip="Incheon International Airport, South Korea">ICN</span>')
EWR = ('<span class="ap" tabindex="0" '
       'data-tip="Newark Liberty International Airport, United States">EWR</span>')


def _answered(node, tmp_path, body, setup="") -> dict:
    """refreshExact through the real solvePoint, answered with `body`; what
    the line and the legs box hold afterwards."""
    return _run(node, tmp_path, _page(armed=True) + f"""
exactFrom = {{ lat: 37.60, lon: 127.10 }};
pinB = {{ lat: 40.71, lon: -74.01, label: "New York" }};
active = meta.origins[0];
{setup}
refreshExact();
const loadingHidden = $("exactlegs").hidden;
requests[0].answer({json.dumps(body)});
await tick(); await tick();
const box = $("exactlegs");
console.log(JSON.stringify({{ line: $("exact").textContent, hidden: box.hidden,
  loadingHidden, rows: box.kids.map(html), text: box.kids.map((r) => r.textContent) }}));
""")


def test_the_legs_are_printed_under_the_line_in_the_itinerarys_words(node, tmp_path):
    """Airport codes glossed with their names from airports.json, the flight
    as "Fly ICN → EWR", the connection, the rail share under the leg it
    belongs to, and an airport the city's routes file does not list named as
    "an airport" rather than guessed.

    Mutations performed and reverted, each RED: drop the `legs:` line from
    solvePoint's result (the box stays hidden); read ordinal k as arrival
    node `a + k` in solverAirport (EWR is not found); print `leg.min` for the
    rail line instead of `leg.railMin`; swap the `landed`/`boards` tests so
    the first leg reads "Onward from".
    """
    got = _answered(node, tmp_path, WITH_LEGS)
    assert got["line"] == ("From the exact point you chose: 20 h 18 min door to door, "
                           "computed on demand.")
    assert got["loadingHidden"] is True, "legs were shown while the answer was computing"
    assert got["hidden"] is False
    assert got["text"] == [
        "2 h 20 minTo ICN, and through the airport52 min of it by rail",
        "13 h 50 minFly ICN → EWR",
        "1 h 35 minConnect at EWR",
        "1 h 1 minFly EWR → an airport",
        "1 h 32 minOnward from an airport",
    ]
    # The rail line is the itinerary's own .via line, and "rail" carries the
    # mode's gloss (MODE_FALLBACK here: this index.json has no modeDetail).
    assert got["rows"][0] == (
        '<div class="leg"><span class="t">2 h 20 min</span>'
        f'<span class="d">To <b>{ICN}</b>, and through the airport'
        '<span class="via">52 min of it by <span class="mode" tabindex="0" data-tip="'
        'Scheduled trains from OpenStreetMap route relations, stop to stop, plus boarding time.'
        '">rail</span></span></span></div>')
    assert got["rows"][1] == ('<div class="leg"><span class="t">13 h 50 min</span>'
                              f'<span class="d">Fly <b>{ICN} → {EWR}</b></span></div>')
    assert got["rows"][2].endswith(f"Connect at <b>{EWR}</b></span></div>")


def test_without_legs_the_line_is_the_figure_alone(node, tmp_path):
    """An older server, or a bundle with no node layout: exactly the line it
    printed before legs existed, and no box.

    Mutation performed and reverted: `res?.ok && res.reachable ? res.legs :
    null` -> `res?.legs ?? []` -> RED (an empty box is shown).
    """
    got = _answered(node, tmp_path, OK)
    assert got["line"] == ("From the exact point you chose: 7 h 12 min door to door, "
                           "computed on demand.")
    assert got["hidden"] is True and got["rows"] == []


def test_no_scheduled_route_has_no_legs(node, tmp_path):
    """Legs under "no scheduled route" would describe a journey that does not
    exist. Two guards, each tested alone: solvePoint gives an unreachable
    answer no legs, and paintExactLegs prints none for one.

    Mutations performed and reverted, each RED: `legs: reachable ?
    solverLegs(...) : null` -> `legs: body.legs`; `res?.ok && res.reachable ?`
    -> `res?.ok ?` in paintExactLegs.
    """
    body = dict(OK, reachable=False, minutes=None, legs=LEGS)
    got = _answered(node, tmp_path, body)
    assert "no scheduled route" in got["line"]
    assert got["hidden"] is True and got["rows"] == []
    alone = _run(node, tmp_path, _page(armed=True) + f"""
const res = await (async () => {{
  const p = solvePoint({{ lat: 1, lon: 2 }}, {{ lat: 3, lon: 4 }});
  requests[0].answer({json.dumps(body)});
  return p;
}})();
paintExactLegs({{ ok: true, reachable: false, minutes: null, legs: {json.dumps(LEGS)} }});
console.log(JSON.stringify({{ legs: res.legs, hidden: $("exactlegs").hidden }}));
""")
    assert alone == {"legs": None, "hidden": True}


@pytest.mark.parametrize("why,legs", [
    ("short by a minute", [dict(LEGS[0], min=139), *LEGS[1:]]),
    ("ends in the air", LEGS[:-1] + [dict(LEGS[-2], min=92)]),
    ("unknown kind", [dict(LEGS[0], kind="teleport"), *LEGS[1:]]),
    # Not summed, and "52" > 140 is false: only the integer test sees it.
    ("a string", [dict(LEGS[0], railMin="52"), *LEGS[1:]]),
    ("more rail than surface", [dict(LEGS[0], railMin=141), *LEGS[1:]]),
    # Has a length, so only Array.isArray stands between it and a for...of
    # that throws -- which solvePoint would report as an outage, figure lost.
    ("not a list", {"length": 5, "0": LEGS[0]}),
])
def test_legs_that_do_not_add_up_cost_the_breakdown_not_the_figure(node, tmp_path, why, legs):
    """The page checks the legs as the service does (wire._check_legs). A
    breakdown that does not sum to the figure above it is dropped; the figure,
    which was validated on its own, still prints.

    Mutations performed and reverted, each RED on its row: drop the
    `sum === minutes` test ("short by a minute"); drop the last-leg test
    ("ends in the air"); drop the `Object.hasOwn` kind test ("unknown
    kind"); drop the per-field `Number.isInteger` test ("a string"); drop the
    railMin bound ("more rail than surface"); drop `Array.isArray` ("not a
    list").
    """
    got = _answered(node, tmp_path, dict(WITH_LEGS, legs=legs))
    assert "20 h 18 min door to door" in got["line"]
    assert got["hidden"] is True, f"{why}: printed anyway"


def test_the_legs_go_with_the_line(node, tmp_path):
    """A new pair, a dropped point and an avoided mode each take the legs
    away with the answer they belonged to.

    Mutations performed and reverted, each RED: delete `paintExactLegs(null)`
    from paintExact's hidden branch (the legs outlive the point); delete the
    `box.replaceChildren()` in the empty branch (the rows survive, hidden).
    """
    got = _run(node, tmp_path, _page(armed=True) + f"""
exactFrom = {{ lat: 37.60, lon: 127.10 }};
pinB = {{ lat: 40.71, lon: -74.01, label: "New York" }};
active = meta.origins[0];
refreshExact();
requests[0].answer({json.dumps(WITH_LEGS)});
await tick(); await tick();
const shown = !$("exactlegs").hidden;
pinB = {{ lat: 35.68, lon: 139.65, label: "Tokyo" }};
refreshExact();
const whileComputing = [$("exactlegs").hidden, $("exactlegs").kids.length];
requests[1].answer({json.dumps(WITH_LEGS)});
await tick(); await tick();
exactFrom = null;
refreshExact();
const afterDrop = [$("exactlegs").hidden, $("exactlegs").kids.length];
console.log(JSON.stringify({{ shown, whileComputing, afterDrop }}));
""")
    assert got["shown"] is True
    assert got["whileComputing"] == [True, 0]
    assert got["afterDrop"] == [True, 0]


@pytest.mark.parametrize("legs,expected", [
    # Overland the whole way, all of it by train.
    ([{"kind": "surface", "min": 75, "railMin": 75}],
     ["1 h 15 min|No flight on this journey: surface travel|All of it by rail"]),
    # Overland, partly by train.
    ([{"kind": "surface", "min": 75, "railMin": 30}],
     ["1 h 15 min|No flight on this journey: surface travel|30 min of it by rail"]),
    # Land at one airport, cross town, fly out of another.
    ([{"kind": "surface", "min": 60, "railMin": 0},
      {"kind": "fly", "from": 0, "to": 2, "min": 600},
      {"kind": "surface", "min": 120, "railMin": 0},
      {"kind": "fly", "from": 1, "to": 0, "min": 300},
      {"kind": "surface", "min": 50, "railMin": 0}],
     ["1 h|To ICN, and through the airport",
      "10 h|Fly ICN → EWR",
      "2 h|From EWR to an airport, and through both airports",
      "5 h|Fly an airport → ICN",
      "50 min|Onward from ICN"]),
])
def test_each_surface_leg_is_named_by_the_flights_around_it(node, tmp_path, legs, expected):
    """exactLegRows alone, every surface branch, with the city's routes file
    resolving the codes. Rail under a surface leg, never road or ferry.

    Mutation performed and reverted: `leg.railMin >= leg.min` -> `>` -> RED on
    the first row.
    """
    got = _run(node, tmp_path, _page(armed=True) + f"""
const flat = (p) => typeof p === "string" ? p
  : p.ap ?? p.mode ?? (p.via ? "|" + p.via.map(flat).join("") : [].concat(p.b).map(flat).join(""));
console.log(JSON.stringify(exactLegRows({json.dumps(legs)}).map(
  (r) => r.t + "|" + r.d.map(flat).join(""))));
""")
    assert got == expected


def test_a_late_airports_json_names_the_exact_legs_too():
    """The itinerary is repainted when airports.json lands; the exact legs
    read the same table for their glosses, so they are repainted with it."""
    handler = _js.APP[_js.APP.index('fetch("./airports.json")'):]
    handler = handler[:handler.index(".catch(")]
    assert "if (pinB) { renderLegs(); paintExact(false); }" in handler


def test_the_exact_legs_box_has_the_tooltips_the_itinerary_has():
    """The .ap and .mode glosses are shown by listeners on their container;
    a second container needs them too, and a missing element must not throw
    at module load (a blank page, twice in this project)."""
    block = _js.APP[_js.APP.index("const legTip = $(\"legtip\");"):]
    block = block[:block.index("const lockBox")]
    assert 'for (const legs of [$("legs"), $("exactlegs")]) {' in block
    assert "if (!legs) continue;" in block
    html = (config.ROOT / "web" / "index.html").read_text(encoding="utf-8")
    assert html.index('id="exact"') < html.index('id="exactlegs"') < html.index('class="legend"')


# ------------------------------------------------------- the drag ---

def _drag(armed: bool, drop: tuple[float, float], active_slug: str, pin: bool) -> str:
    """originDragEnd, run for real, with paintOrigin stubbed to do what the
    real one does to the exact point: drop it."""
    meta = {"origins": CITIES, **({"solver": {"wire": 1}} if armed else {})}
    return f"""
const meta = {json.dumps(meta)};
const store = {{ get: () => true, set: () => {{}} }};
{CONSTS}
{CONST_SRC}
{FN["haversineKm"]}
{FN["nearestOrigin"]}
{FN["fmtKm"]}
let exactFrom = {{ lat: 0, lon: 0 }};   // left by an earlier drag
let pinB = {json.dumps({"lat": 35.0, "lon": 135.0}) if pin else "null"};
let active = meta.origins.find((o) => o.slug === {json.dumps(active_slug)});
const log = [];
const originLabel = {{ classList: {{ remove() {{}} }} }};
let markerAt = {{ lat: {drop[0]}, lng: {drop[1]} }};
const originMarker = {{ getLngLat: () => markerAt,
  setLngLat: ([lng, lat]) => {{ markerAt = {{ lat, lng }}; }} }};
let notice = "";
const snapNotice = (...p) => {{ notice = p.map((x) => typeof x === "string" ? x : x.b).join(""); }};
const announce = () => {{}};
const unfoldSheet = () => {{}};
const refreshExact = () => log.push("refresh");
const syncPermalink = () => log.push("sync");
const dropDestination = () => {{ pinB = null; }};
const paintOrigin = (o) => {{ log.push("paint"); exactFrom = null; notice = ""; active = o; }};
{FN["originDragEnd"]}
originDragEnd();
console.log(JSON.stringify({{ exactFrom, notice, active: active.slug, log }}));
"""


# About 34 km from Seoul, nearer Seoul than Tokyo.
NEAR_SEOUL = (37.80, 127.25)
# About 300 m from Seoul's own point.
ON_SEOUL = (37.5690, 126.9790)


def test_a_drop_away_from_the_city_keeps_the_exact_point(node, tmp_path):
    """The "Moved to" branch: the map snaps to Seoul, the point is kept, and
    the notice says the point's own time is computed on demand.

    Mutation performed and reverted: move `exactFrom = exact` above
    paintOrigin -> red (paintOrigin drops it). `km > EXACT_MIN_KM` ->
    `km > 100` -> red.
    """
    got = _run(node, tmp_path, _drag(True, NEAR_SEOUL, "tokyo", pin=False))
    assert got["active"] == "seoul"
    assert got["exactFrom"] == {"lat": NEAR_SEOUL[0], "lon": NEAR_SEOUL[1]}
    assert "Moved to Seoul" in got["notice"]
    assert "not from that point" in got["notice"]
    assert "computed on demand" in got["notice"]
    # Written after the switch, and then synced into the address.
    assert got["log"].index("paint") < got["log"].index("sync")


def test_a_kept_city_still_keeps_the_point_and_asks(node, tmp_path):
    """The "Kept" branch has no paintOrigin to call renderPins, and the
    destination survives it, so it must ask for the line itself.

    Mutation performed and reverted: delete `refreshExact()` from the Kept
    branch -> red.
    """
    got = _run(node, tmp_path, _drag(True, NEAR_SEOUL, "seoul", pin=True))
    assert got["exactFrom"] == {"lat": NEAR_SEOUL[0], "lon": NEAR_SEOUL[1]}
    assert "refresh" in got["log"] and "sync" in got["log"]
    assert "Kept Seoul" in got["notice"] and "computed on demand" in got["notice"]


def test_a_drop_on_the_city_itself_is_the_city(node, tmp_path):
    """Within a kilometre there is no separate point, and an earlier one goes.

    Mutation performed and reverted: in the Kept branch, `exactFrom = exact`
    -> `if (exact) exactFrom = exact` -> red (the earlier point survives).
    """
    got = _run(node, tmp_path, _drag(True, ON_SEOUL, "seoul", pin=True))
    assert got["exactFrom"] is None
    assert "computed on demand" not in got["notice"]


@pytest.mark.parametrize("active_slug", ["tokyo", "seoul"])
def test_unarmed_the_drag_is_exactly_what_it_was(node, tmp_path, active_slug):
    """No point kept, no `dep=` in the address, and the notice unchanged.

    Mutation performed and reverted: drop `solverEnabled &&` from `exact` ->
    red on both rows.
    """
    got = _run(node, tmp_path, _drag(False, NEAR_SEOUL, active_slug, pin=False))
    assert got["exactFrom"] is None
    assert "computed on demand" not in got["notice"]
    assert got["notice"].endswith("not from that point." if active_slug == "tokyo"
                                  else "from where you dropped the marker.")


def _paint_origin(o_slug: str, force: bool) -> str:
    """paintOrigin, run for real up to the first thing past its guard."""
    return f"""
const meta = {{ origins: {json.dumps(CITIES)} }};
let exactFrom = {{ lat: 37.80, lon: 127.25 }};
let active = meta.origins[0];               // departing from Seoul
const origin = {{ failed: null }};
let originGen = 0, originAbort = null;
const log = [];
const snapNotice = () => log.push("notice");
const refreshExact = () => log.push("refresh");
const syncPermalink = () => log.push("sync");
const captureComparison = () => {{}};
const clearTileTrouble = () => {{ throw "past the guard"; }};
{FN["forgetExactFrom"]}
{FN["paintOrigin"]}
let past = false;
try {{
  paintOrigin(meta.origins.find((o) => o.slug === {json.dumps(o_slug)}),
              {{ keepZoom: true, force: {json.dumps(force)} }});
}} catch (e) {{ if (e !== "past the guard") throw e; past = true; }}
console.log(JSON.stringify({{ exactFrom, past, log }}));
"""


@pytest.mark.parametrize("o_slug", ["tokyo", "seoul"])
def test_picking_a_city_drops_the_exact_point(node, tmp_path, o_slug):
    """The list, a permalink, "Depart from" and a city's label all reach
    paintOrigin. Picking the city you already depart from is the case that
    returns early at the guard, so the point must go BEFORE it.

    Mutation performed and reverted: move `if (!force) forgetExactFrom();`
    below the guard -> red on the "seoul" row. Delete it -> red on both.
    """
    got = _run(node, tmp_path, _paint_origin(o_slug, force=False))
    assert got["exactFrom"] is None
    assert got["past"] is (o_slug == "tokyo")
    assert "refresh" in got["log"] and "sync" in got["log"], (
        "the point was dropped but the line and the address still show it")


def test_avoiding_a_mode_keeps_the_exact_point(node, tmp_path):
    """`force` repaints the same city from another map; the point still
    applies, and the line says why it has no number meanwhile.

    Mutation performed and reverted: `if (!force) forgetExactFrom()` ->
    `forgetExactFrom()` -> red.
    """
    got = _run(node, tmp_path, _paint_origin("seoul", force=True))
    assert got["exactFrom"] == {"lat": 37.80, "lon": 127.25}
    assert got["past"] is True


def test_every_city_route_reaches_the_clearing_path():
    """Each of the routes the rule names calls paintOrigin with no `force`,
    and the label route no longer skips it for the current city."""
    list_pick = APP[APP.index('const b = e.target.closest("button[data-slug]");'):]
    assert "paintOrigin(bySlug.get(b.dataset.slug));" in list_pick[:600]
    assert "paintOrigin(requested ?? FALLBACK);" in APP
    assert "paintOrigin(near, { keepZoom: true });" in _js.function("renderPins")
    assert "if (cityHere.slug !== active?.slug) paintOrigin" not in APP, (
        "the label route skips paintOrigin for the current city, so an exact "
        "point dragged near it survives a click on the city's own name")


# ------------------------------------------------------- the address ---

def _dep(node, tmp_path, cases: dict) -> dict:
    block = APP[APP.index("  // ?dep= -- the exact point"):APP.index("} catch { /* no URL API */ }")]
    assert 'q.get("dep")' in block and "parseDep(" in block
    return _run(node, tmp_path, f"""
const meta = {{ origins: {json.dumps(CITIES)} }};
const bySlug = new Map(meta.origins.map((c) => [c.slug, c]));
{FN["haversineKm"]}
{FN["nearestOrigin"]}
{FN["parseDep"]}
function parse(search) {{
  const q = new URLSearchParams(search);
  const URL_REJECTED = [];
  let requestedDep = null;
  // As the reader before it does: a slug that names a city, or nothing.
  const requested = bySlug.get(q.get("from") ?? "") ?? null;
{block}
  return {{ requestedDep, URL_REJECTED }};
}}
console.log(JSON.stringify(Object.fromEntries(
  Object.entries({json.dumps(cases)}).map(([k, v]) => [k, parse(v)]))));
""")


def test_dep_is_restored_only_beside_the_from_it_belongs_to(node, tmp_path):
    """Mutation performed and reverted: drop `|| !from` from parseDep -> red on
    "alone". Drop the nearest-city check -> red on "wrong city". Drop the
    empty-half check -> red on "empty half".
    """
    got = _dep(node, tmp_path, {
        "good": "from=seoul&dep=37.80000,127.25000",
        "alone": "dep=37.80000,127.25000",
        "bad from": "from=atlantis&dep=37.80000,127.25000",
        "wrong city": "from=tokyo&dep=37.80000,127.25000",
        "out of range": "from=seoul&dep=91,127",
        "junk": "from=seoul&dep=north",
        "empty half": "from=seoul&dep=37.8,",
        "three": "from=seoul&dep=37.8,127.2,4",
        "none": "from=seoul",
    })
    assert got["good"] == {"requestedDep": {"lat": 37.8, "lon": 127.25}, "URL_REJECTED": []}
    for case in ("alone", "bad from", "wrong city", "out of range", "junk",
                 "empty half", "three"):
        assert got[case] == {"requestedDep": None, "URL_REJECTED": ["dep"]}, case
    assert got["none"] == {"requestedDep": None, "URL_REJECTED": []}


def test_dep_is_restored_after_the_departure_and_never_arms_anything():
    """paintOrigin drops any exact point, so restoring it first would restore
    nothing. And the restore must not touch the switch.

    Mutation performed and reverted: move the restore block above
    `paintOrigin(requested ?? FALLBACK);` -> red.
    """
    paint = APP.index("paintOrigin(requested ?? FALLBACK);")
    restore = APP.index("exactFrom = requestedDep;")
    assert paint < restore
    block = APP[restore:APP.index("\n}\n", restore)]
    assert "solverEnabled =" not in block
    assert re.search(r"if \(solverEnabled\) \{\s*snapNotice\(", block), (
        "an unarmed page says something about a point it will never compute")


def test_the_writer_puts_dep_only_beside_from():
    writer = _js.function("syncPermalink")
    dep = writer[writer.index('put("dep"'):]
    dep = dep[:dep.index(");") + 2]
    assert "exactFrom && active" in dep
    assert "toFixed(5)" in dep


# ------------------------------------------------------- carry-on ---

# solvePoint's result, not the wire body: what carryOnExact and exactReading take.
RES = {"ok": True, "reachable": True, "minutes": 432, "snappedKm": 0.0}
FLOWN = {**RES, "minutes": 1080, "legs": [
    {"kind": "surface", "min": 150, "railMin": 40},
    {"kind": "fly", "from": 0, "to": 2, "min": 873},
    {"kind": "surface", "min": 57, "railMin": 0}]}
SAVE = {"dep": 15, "arr": 10}


def _carry(node, tmp_path, res, save) -> dict:
    return _run(node, tmp_path, _page(armed=True) + f"""
console.log(JSON.stringify(carryOnExact({json.dumps(res)}, {json.dumps(save)})));
""")


def test_carry_on_comes_off_the_airport_legs_and_the_total_alike(node, tmp_path):
    """The map's panel takes the bag-drop minutes off the leg into the first
    airport and the belt minutes off the leg out of the last; the on-demand
    answer must do the same, and its legs must still add up to its figure.

    Mutations performed and reverted, each -> red: the total left unchanged;
    `arr` taken off the first leg instead of the last; railMin not clamped.
    """
    got = _carry(node, tmp_path, FLOWN, SAVE)
    assert got["minutes"] == 1080 - 25 and got["carryOn"] is True
    assert [leg["min"] for leg in got["legs"]] == [135, 873, 47]
    assert sum(leg["min"] for leg in got["legs"]) == got["minutes"]
    assert got["legs"][0]["railMin"] == 40
    tight = {**FLOWN, "legs": [{**FLOWN["legs"][0], "min": 20, "railMin": 18},
                               FLOWN["legs"][1], FLOWN["legs"][2]], "minutes": 950}
    t = _carry(node, tmp_path, tight, SAVE)
    assert t["legs"][0]["min"] == 5 and t["legs"][0]["railMin"] == 5


@pytest.mark.parametrize("res", [
    {**RES},                                                      # an older service: no legs
    {**RES, "legs": [{"kind": "surface", "min": 432, "railMin": 0}]},  # never flew
    {**RES, "reachable": False, "minutes": None},
    # Not surface-fly...fly-surface: there is no leg to take the bag-drop off.
    {**RES, "minutes": 900, "legs": [{"kind": "fly", "from": 0, "to": 2, "min": 873},
                                     {"kind": "surface", "min": 27, "railMin": 0}]},
])
def test_carry_on_leaves_what_it_cannot_honestly_change(node, tmp_path, res):
    """A surface-only journey must not lose bag minutes it never spent.

    Mutation performed and reverted: dropping the `!flights.length` return
    stays GREEN, and is equivalent -- with no flight there is no leg before the
    first one, and the shape check returns the answer unchanged. Making the
    shape check pass anything (`return res` removed) -> red.
    """
    assert _carry(node, tmp_path, res, SAVE) == res


def test_the_line_says_which_bag_its_figure_assumes(node, tmp_path):
    """Carry-on applied says so; no legs keeps the checked-bag caveat; a
    journey that never flew carries neither.

    Mutation performed and reverted: always append " It assumes a checked
    bag." when carry-on is on -> red.
    """
    applied = _carry(node, tmp_path, FLOWN, SAVE)
    assert _reading(node, tmp_path, applied, carryOnOn=True).endswith(" Carry-on only.")
    assert "assumes a checked bag" in _reading(node, tmp_path, RES, carryOnOn=True)
    overland = {**RES, "legs": [{"kind": "surface", "min": 432, "railMin": 0}]}
    said = _reading(node, tmp_path, overland, carryOnOn=True)
    assert "checked bag" not in said and "Carry-on" not in said
