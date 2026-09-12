"""The itinerary is decomposed on one grid, and its rows sum to its total.

`renderLegsInto` reads every leg row at the res-4 cell index -- `legsTo()`
through `origin.air`/`origin.routes`, `surface()` through `origin.modes` -- and
used to take its total from `lookup()`, which returns the res-6 reading whenever
that tier is present. Those are two different cells, up to 17 km apart.

Two silent consequences, both armed the moment a build advertises `readingRes`:
`if (total > landed.min)` goes false when the finer reading is the lower of the
two, and the onward leg from the arrival airport vanishes from the itinerary;
and the rows stop summing to the "Door to door" line they are presented as
decomposing.

`renderLegsInto` is RUN here, not ported. `cellIndex` and `lookup` are stubbed
because they are the two INPUTS whose disagreement is the subject -- stubbing
them is how the disagreement is staged -- and everything else is the real code.
`fmtDur` is stubbed to print the raw minute count so the rows can be summed
exactly rather than parsed back out of "3 h 20".

Mutation performed and reverted: take `total` from `lookup(...)` again -> red on
both the missing onward row and the sum.
"""

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
        pytest.skip("node is not on PATH; the page functions cannot be run")
    return exe


#: res-4 index of the pin in the fixture below.
CI = 5
#: The journey: 40 min to the airport, a 300 min flight, then 120 min onward.
TO_AIRPORT, LANDED, GROUND_TOTAL = 40, 340, 460


def _probe(reading: int) -> str:
    """A journey whose res-6 reading is `reading` and whose res-4 total is 460."""
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
const esc = (t) => String(t);
const fmtDur = (m) => String(m);          // raw minutes, so the rows can be summed
const countryName = () => "Somewhere";
const airports = [["AAA", "A Airport", "XX"], ["BBB", "B Airport", "YY"]];
const pinB = {{ lat: 1, lon: 2, label: "Destination" }};
function renderRoute() {{}}
function fitReading() {{}}

// The two grid lookups, stubbed: their disagreement IS the subject.
function cellIndex() {{ return {CI}; }}
function lookup() {{ return {reading}; }}

const origin = {{
  // res-4 array: the index the legs are read at carries the journey's real total
  times: (() => {{ const a = new Uint16Array(16).fill(MAX_MINUTES); a[{CI}] = {GROUND_TOTAL}; return a; }})(),
  air: (() => {{ const a = new Uint16Array(16).fill(NO_AIRPORT); a[{CI}] = 0; return a; }})(),
  modes: (() => {{ const a = new Uint16Array(16 * 3); a[{CI} * 3 + 2] = 90; return a; }})(),
  rail: null,
  routes: {{
    offsets: {{ airports: 0, stations: 4 }},   // count = (4 - 0) / 2 = 2
    byId: new Map([
      [2, {{ code: "AAA", kind: "dep", min: {TO_AIRPORT}, prev: null }}],
      [3, {{ code: "BBB", kind: "arr", min: {LANDED}, prev: 2 }}],
    ]),
  }},
}};
{_function("railVia")}
{_function("legsTo")}
{_function("renderLegsInto")}
renderLegsInto();
const box = $("legs");
const frag = box.children[0];
console.log(JSON.stringify({{
  hidden: box.hidden,
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


@pytest.mark.parametrize("reading", [GROUND_TOTAL, 300, 620])
def test_the_rows_sum_to_the_door_to_door_line_whatever_the_finer_grid_says(
        node, tmp_path, reading: int) -> None:
    """300 is the case that used to delete the onward leg: it is BELOW the
    minute the journey landed at (340), so `total > landed.min` went false."""
    got = _run(node, tmp_path, _probe(reading))
    assert got["hidden"] is False, "the itinerary refused to render at all"
    rows = got["rows"]

    onward = [r for r in rows if "Onward from" in r[1] or "onward by surface" in r[1]]
    assert onward, (
        f"the onward leg is missing when the finer grid reads {reading} against "
        f"a res-4 total of {GROUND_TOTAL}; the journey landed at {LANDED}")

    totals = [r for r in rows if r[2]]
    assert len(totals) == 1, "there must be exactly one Door to door row"
    assert totals[0][1] == "Door to door"
    door = int(totals[0][0])
    assert door == GROUND_TOTAL, (
        f"the panel totals {door}, which is the finer grid's reading, not the "
        f"{GROUND_TOTAL} its own rows are read at")

    # Rows before the "Surface travel over the whole journey:" heading are the
    # decomposition; the ones after it are a separate listing over the whole
    # journey and are explicitly NOT a breakdown of the onward figure.
    parts, seen_heading = [], False
    for minutes, text, is_total in rows:
        if "Surface travel over the whole journey" in text:
            seen_heading = True
        if is_total or seen_heading or not minutes:
            continue
        parts.append(int(minutes))
    assert sum(parts) == door, (
        f"the rows {parts} sum to {sum(parts)}, not to the {door} the "
        "'Door to door' line states")


def test_a_disagreement_between_the_two_grids_is_stated_not_hidden(node, tmp_path) -> None:
    """CLAUDE.md requires the composition to be said wherever a figure is shown.
    Two door-to-door figures that differ, with nothing saying why, is worse than
    one."""
    quiet = _run(node, tmp_path, _probe(GROUND_TOTAL))["notes"]
    assert not any("finer grid" in n for n in quiet), (
        "the grids agree, but the page explained a difference anyway")

    loud = _run(node, tmp_path, _probe(300))["notes"]
    assert any("finer grid" in n and "300" in n for n in loud), (
        "the headline reading and the breakdown disagree and the panel says "
        f"nothing about it: {loud}")
