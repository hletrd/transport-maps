"""The itinerary's total is the number printed above it, and its rows sum to it.

Two defects meet in `renderLegsInto`, and this file pins both.

**The grids.** Every leg row is read at the res-4 cell index -- `legsTo()`
through `origin.air`/`origin.routes`, `surface()` through `origin.modes` --
while `lookup()` returns the res-6 reading whenever that tier is present. Those
are two different cells, up to 17 km apart. Cycle 9 made the panel total res-4
so the rows would sum; the page then printed "16 h 23 min" above a "Door to
door" line reading "16 h 20 min", and `scripts/browser_verify.sh` failed on it.
The total now comes from the reading and the ONWARD leg carries the difference,
which is the only row that depends on the grid at all. Where the reading is at
or below the minute the journey landed it cannot head a decomposition -- the
rows would exceed it -- and the panel falls back to res-4 and says so.

**The chain.** A `dep` node's predecessor is a solver CELL, and
`emit/routes_json.py` emits airport nodes only, so the walk stops there. For a
journey that FLEW to that airport the whole prefix was missing, and the page
rendered the truncated head as a ground leg: from Seoul, `?to=-20.162,57.499`
read "10 h 48 min -- To KUL, and through the airport". `legsTo` now continues
the walk by asking `origin.air` about the departure airport's own cell, and
where it cannot show the recovered chain lands at that same airport it returns
the chain `partial` and the panel stops asserting how it was reached.

`renderLegsInto` and `legsTo` are RUN here, not ported. `cellIndex` and
`lookup` are stubbed because they are the two INPUTS whose disagreement is the
subject -- stubbing them is how the disagreement is staged -- and everything
else is the real code. `fmtDur` is stubbed to print the raw minute count so the
rows can be summed exactly rather than parsed back out of "3 h 20".

Mutations performed and reverted, each confirmed RED:
  * `const total = usable ? reading : coarse;` -> `= coarse`
      -> 4 failed
  * `usable`: drop `&& reading > landedMin`
      -> 1 failed (the rows then exceed the total they decompose)
  * `for (let hop = 0; hop < 6; ...)` -> `hop < 0`, so the walk never continues
      -> 2 failed
  * `landed.code !== head.code` dropped from the splice guard
      -> 1 failed. This one needed a NEW fixture to catch: with only the
         arr:CCC case the `landed.min > head.min` guard fired first and the
         mutation stayed green on all 11 tests. arr:DDD at 350 exists solely
         to reach the code guard on its own.
  * `rows.push(chain.partial ? ... : ...)` -> `rows.push(false ? ... : ...)`
      -> 2 failed
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess

import pytest

from transport_maps import config

APP = (config.ROOT / "web" / "app.js").read_text(encoding="utf-8")

# The REAL escape, not a stub. This harness is the only place `esc`'s call
# sites actually run, and it used to declare `const esc = (t) => String(t)` --
# so the escape was switched off in the one test that exercised it, and
# deleting the `"` replacement left every gate green while opening live XSS
# through `data-tip="..."`. Sliced from app.js by the same helper
# tests/web/test_esc.py uses, so the two cannot drift apart.
from tests.web.test_esc import ESC_SRC  # noqa: E402


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
        pytest.skip("node is not on PATH; the page functions cannot be run")
    return exe


#: res-4 indices: the pin, then the two airports the walk has to ask about.
CI, CI_BBB, CI_AAA = 5, 7, 9
#: The journey: 40 min to AAA, fly to BBB landing at 340, connect and board at
#: 400, fly to CCC landing at 700, then onward to the pin. DDD is a fourth
#: airport reachable at 350 -- BEFORE the journey boards at BBB -- and exists
#: only so the "lands at the SAME airport" guard can be tested on its own,
#: without the "lands after we board" guard firing first and masking it.
TO_AAA, ARR_BBB, DEP_BBB, ARR_CCC, ARR_DDD = 40, 340, 400, 700, 350
#: What the res-4 array says the whole door-to-door journey takes.
GROUND_TOTAL = 900
#: The id of the cell dep:BBB was reached from. Deliberately absent from byId:
#: that absence is the defect's mechanism.
CELL_PREV = 999


def _probe(reading: int, air_at_bbb: str = "1") -> str:
    """A two-flight journey whose res-6 reading is `reading`.

    `air_at_bbb` is the arrival-airport ordinal recorded for BBB's OWN res-4
    cell, which is what `legsTo` consults to continue the walk:
      "1"  -> arr:BBB, so the prefix AAA->BBB is recoverable
      "3"  -> arr:DDD, a DIFFERENT airport reached BEFORE we board: the code
              guard is the only thing that can refuse it
      "2"  -> arr:CCC, a different airport reached AFTER we board
      "NO_AIRPORT" -> BBB really was reached over the ground; chain is complete
    """
    return f"""
class El {{
  constructor(tag){{ this.tagName=tag; this.style={{}}; this.dataset={{}};
    this.textContent=""; this.innerHTML=""; this.className="";
    this.hidden=false; this.children=[]; }}
  append(...k){{ this.children.push(...k); }}
  replaceChildren(...k){{ this.children = k; }}
}}
globalThis.document = {{
  createElement: (t) => new El(t),
  createDocumentFragment: () => new El("#fragment"),
}};
const _els = {{}};
const $ = (id) => (_els[id] ||= new El("div"));

const MAX_MINUTES = 65534, NO_AIRPORT = 0xFFFF, NO_RAIL = 0xFFFF;
const MODE_NAMES = ["rail", "ferry", "highway"];
const MODE_FALLBACK = {{ rail: "by train", ferry: "by boat", highway: "by road" }};
const meta = {{ modeDetail: null }};
{ESC_SRC}
const fmtDur = (m) => String(m);          // raw minutes, so the rows can be summed
const countryName = () => "Somewhere";
// [iata, name, country, lat, lon, size] -- legsTo reads 3 and 4.
const airports = [["AAA", "A Airport", "XX", 10, 10],
                  ["BBB", "B Airport", "YY", 20, 20],
                  ["CCC", "C Airport", "ZZ", 30, 30],
                  ["DDD", "D Airport", "WW", 40, 40]];
const pinB = {{ lat: 1, lon: 2, label: "Destination" }};
function renderRoute() {{}}
function fitReading() {{}}

// The two grid lookups, stubbed: their disagreement IS the subject. cellIndex
// must answer for the airports too, because that is how the walk continues.
function cellIndex(lat, lon) {{
  if (lat === 1  && lon === 2)  return {CI};
  if (lat === 20 && lon === 20) return {CI_BBB};
  if (lat === 10 && lon === 10) return {CI_AAA};
  if (lat === 40 && lon === 40) return 11;
  return -1;
}}
function lookup() {{ return {reading}; }}

const origin = {{
  // res-4 array: the grid the legs are read at, and the fallback total.
  times: (() => {{ const a = new Uint16Array(16).fill(MAX_MINUTES); a[{CI}] = {GROUND_TOTAL}; return a; }})(),
  air: (() => {{ const a = new Uint16Array(16).fill(NO_AIRPORT);
                 a[{CI}] = 2;                       // the pin was reached via arr:CCC
                 a[{CI_BBB}] = {air_at_bbb};        // what BBB's own cell records
                 a[{CI_AAA}] = NO_AIRPORT;          // AAA is reached over the ground
                 a[11] = NO_AIRPORT;                // DDD's own cell
                 return a; }})(),
  modes: (() => {{ const a = new Uint16Array(16 * 3); a[{CI} * 3 + 2] = 90; return a; }})(),
  rail: null,
  routes: {{
    offsets: {{ airports: 0, stations: 8 }},   // count = (8 - 0) / 2 = 4 airports
    byId: new Map([
      [0, {{ code: "AAA", kind: "dep", min: {TO_AAA},  prev: null }}],
      [1, {{ code: "BBB", kind: "dep", min: {DEP_BBB}, prev: {CELL_PREV} }}],
      [5, {{ code: "BBB", kind: "arr", min: {ARR_BBB}, prev: 0 }}],
      [6, {{ code: "CCC", kind: "arr", min: {ARR_CCC}, prev: 1 }}],
      [7, {{ code: "DDD", kind: "arr", min: {ARR_DDD}, prev: 0 }}],
    ]),
  }},
}};
{_function("walkPrev")}
{_function("chainAtCell")}
{_function("legsTo")}
{_function("partial")}
{_function("railVia")}
{_function("renderLegsInto")}
const MAX_CHAIN = 24;
renderLegsInto();
const box = $("legs");
const frag = box.children[0];
console.log(JSON.stringify({{
  hidden: box.hidden,
  chain: (legsTo(pinB.lat, pinB.lon) || []).map((n) => n.kind + ":" + n.code + "@" + n.min),
  partialFlag: !!(legsTo(pinB.lat, pinB.lon) || {{}}).partial,
  rows: frag.children.filter((c) => c.className.startsWith("leg"))
    .map((d) => [d.children[0].textContent, d.children[1].innerHTML,
                 d.className.includes("total")]),
  notes: frag.children.filter((c) => c.className === "linekey")
    .map((c) => c.textContent),
}}));
"""


def _run(node: str, tmp_path, body: str) -> dict:
    script = tmp_path / "itinerary.mjs"
    script.write_text(body, encoding="utf-8")
    out = subprocess.run([node, str(script)], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


def _plain(html: str) -> str:
    """Row text with the tooltip spans stripped, so an assertion reads like the
    sentence a visitor sees rather than like the markup."""
    return re.sub(r"<[^>]+>", "", html)


def _decomposition(rows: list) -> list[int]:
    """The rows the "Door to door" line is presented as decomposing.

    Rows after the "Surface travel over the whole journey:" heading are a
    separate listing over the whole journey and explicitly NOT part of it.
    """
    parts, seen_heading = [], False
    for minutes, text, is_total in rows:
        if "Surface travel over the whole journey" in text:
            seen_heading = True
        if is_total or seen_heading or not minutes:
            continue
        parts.append(int(minutes))
    return parts


# --------------------------------------------------------------- the grids ---

@pytest.mark.parametrize("reading", [GROUND_TOTAL, 860, 1200])
def test_the_door_to_door_line_is_the_number_printed_above_it(
        node, tmp_path, reading: int) -> None:
    """browser_verify.sh compares #time against `.leg.total .t` and they must
    match. All three readings are above the minute the journey landed (700), so
    the decomposition holds and the total is the reading -- NOT the res-4 900."""
    got = _run(node, tmp_path, _probe(reading))
    assert got["hidden"] is False, "the itinerary refused to render at all"
    totals = [r for r in got["rows"] if r[2]]
    assert len(totals) == 1, "there must be exactly one Door to door row"
    assert totals[0][1] == "Door to door"
    assert int(totals[0][0]) == reading, (
        f"the panel totals {totals[0][0]} where the headline reads {reading}; "
        "the two numbers a visitor sees together must be the same number")


@pytest.mark.parametrize("reading", [GROUND_TOTAL, 860, 1200])
def test_the_rows_sum_to_the_door_to_door_line(node, tmp_path, reading: int) -> None:
    got = _run(node, tmp_path, _probe(reading))
    rows = got["rows"]
    onward = [r for r in rows if "Onward from" in r[1] or "onward by surface" in r[1]]
    assert onward, f"the onward leg is missing at a reading of {reading}"
    parts = _decomposition(rows)
    assert sum(parts) == reading, (
        f"the rows {parts} sum to {sum(parts)}, not to the {reading} the "
        "'Door to door' line states")


def test_a_reading_below_the_landing_falls_back_and_says_so(node, tmp_path) -> None:
    """650 is below ARR_CCC (700): the rows would exceed a total of 650, so the
    panel must use the res-4 figure and state the disagreement instead."""
    got = _run(node, tmp_path, _probe(650))
    totals = [r for r in got["rows"] if r[2]]
    assert int(totals[0][0]) == GROUND_TOTAL, (
        "a reading at or below the minute the journey landed cannot head a "
        f"decomposition; the panel should have fallen back to {GROUND_TOTAL}")
    parts = _decomposition(got["rows"])
    assert sum(parts) == GROUND_TOTAL, (
        f"the rows {parts} sum to {sum(parts)}, not to {GROUND_TOTAL}")
    assert any("finer grid" in n and "650" in n for n in got["notes"]), (
        "the headline reading and the total disagree and the panel says "
        f"nothing about it: {got['notes']}")


def test_agreeing_grids_are_not_explained(node, tmp_path) -> None:
    """CLAUDE.md requires the composition to be said wherever a figure is
    shown -- not that a difference be invented where there is none."""
    notes = _run(node, tmp_path, _probe(GROUND_TOTAL))["notes"]
    assert not any("finer grid" in n or "do not sum" in n for n in notes), (
        f"the grids agree, but the page explained a difference anyway: {notes}")


# --------------------------------------------------------------- the chain ---

def test_the_walk_continues_through_a_cell_predecessor(node, tmp_path) -> None:
    """dep:BBB's predecessor is a CELL, absent from the file. The prefix is
    recovered from origin.air at BBB's own cell, so the panel names AAA -- the
    airport the journey actually left from -- not BBB."""
    got = _run(node, tmp_path, _probe(GROUND_TOTAL))
    assert got["chain"] == ["dep:AAA@40", "arr:BBB@340", "dep:BBB@400", "arr:CCC@700"], (
        f"the walk stopped short: {got['chain']}")
    assert got["partialFlag"] is False
    first = got["rows"][0]
    assert "AAA" in first[1] and "through the airport" in first[1], (
        f"the first row should reach AAA over the ground, got {first}")
    assert int(first[0]) == TO_AAA, (
        f"the first row charges {first[0]} min to reach the first airport, but "
        f"the journey reached AAA at {TO_AAA}; {DEP_BBB} would be the truncated "
        "head being priced as a ground leg")
    texts = _plain(" ".join(r[1] for r in got["rows"]))
    assert "Fly AAA → BBB" in texts and "Fly BBB → CCC" in texts, (
        f"both flights should be itemised: {texts}")
    assert "Connect at BBB" in texts


def test_an_airport_genuinely_reached_overland_is_still_named_that_way(
        node, tmp_path) -> None:
    """NO_AIRPORT at BBB's own cell means the journey really did reach it over
    the ground. That is the common case and it must not be made partial."""
    got = _run(node, tmp_path, _probe(GROUND_TOTAL, air_at_bbb="NO_AIRPORT"))
    assert got["chain"] == ["dep:BBB@400", "arr:CCC@700"]
    assert got["partialFlag"] is False
    assert "BBB" in got["rows"][0][1] and "through the airport" in got["rows"][0][1]


@pytest.mark.parametrize("air_at_bbb, why", [
    ("3", "arr:DDD lands at 350, before the journey boards BBB at 400, so only "
          "the 'lands at the SAME airport' guard can refuse this splice"),
    ("2", "arr:CCC lands at 700, after the journey boards BBB at 400"),
])
def test_a_chain_that_cannot_be_continued_is_not_asserted(
        node, tmp_path, air_at_bbb: str, why: str) -> None:
    """BBB's cell records a DIFFERENT airport from the one boarded. The page
    cannot show how BBB was reached, so it must not say."""
    got = _run(node, tmp_path, _probe(GROUND_TOTAL, air_at_bbb=air_at_bbb))
    assert got["partialFlag"] is True, f"the chain should be marked partial: {why}"
    first = got["rows"][0]
    assert "through the airport" not in first[1], (
        f"the page asserts a ground journey it cannot substantiate: {first}")
    assert "not recorded" in first[1], (
        f"the unknown prefix should be named as unknown, got {first}")
    assert any("not recorded" in n and "not drawn" in n for n in got["notes"]), (
        f"the globe draws no leading leg, and the key must not promise one: "
        f"{got['notes']}")


def test_a_hostile_airport_name_cannot_escape_its_tooltip(node, tmp_path) -> None:
    """`ap()` interpolates an OurAirports name into `data-tip="..."`, and this
    harness is the only place that code actually runs.

    It ran with `esc` stubbed to the identity function, so the escape was off
    in the one test that exercised it. With the real helper in place, a name
    carrying a double quote must not be able to close the attribute and add an
    event handler.

    Mutation performed and reverted: put the stub back (`const esc = (t) =>
    String(t)`) -> red, `onmouseover=` appears outside the attribute.
    """
    body = _probe(GROUND_TOTAL).replace(
        '["BBB", "B Airport", "YY", 20, 20]',
        '["BBB", "B\\" onmouseover=\\"alert(1)", "YY", 20, 20]')
    got = _run(node, tmp_path, body)
    html = "".join(text for _, text, _ in got["rows"])
    assert "onmouseover" in html, (
        "the hostile name never reached the row; the fixture no longer bites")
    assert 'onmouseover="' not in html, (
        "the airport name closed data-tip and added a live event handler")
    assert "&quot; onmouseover=&quot;alert(1)" in html
