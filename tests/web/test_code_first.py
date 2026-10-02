"""A three-letter city name is not an invitation to pick an airport.

`codeFirst` decides whether the airport rows go above the departure cities. It
keyed on the query's LENGTH alone: three characters that match some IATA code
put that airport first, and Enter takes the first row -- which sets a
DESTINATION rather than departing from the city you just spelled in full.

Six departure cities in the 1,464-origin roster are spelled exactly like a live
IATA code. Typing `Aba` and pressing Enter set Abakan, Russia as the
destination instead of departing from Aba, Nigeria.

The rule the flag exists for is untouched: no departure city is called JFK, so
`jfk` is still one keystroke from Kennedy.

Mutation performed and reverted: drop `hits[0]?.key !== f` from the condition
-> red, all six cities put an airport first again.

R8 (2026-10-02): the airport code is lower-cased once at load (`code:`) rather
than per row per keystroke, and the key line is now lifted from app.js rather
than retyped here. Mutation performed and reverted: drop `code:` from that
line -> red, 2 failed (no code matches any more).
"""

from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from tests.conftest import skip_without_dist
from transport_maps import config

APP = (config.ROOT / "web" / "app.js").read_text(encoding="utf-8")


def _fold_line() -> str:
    start = APP.index("const FOLD_DROP =")
    return APP[start:APP.index("const cities =", start)]


def _airports_line() -> str:
    """The page's own search keys for the airport table, lifted rather than
    retyped: the ranking reads `a.code`, which this file's copy of the line
    did not build, so a retyped copy would rank every code as a miss."""
    start = APP.index("    airports = a.airports.map(")
    return APP[start:APP.index("\n", start)]


@pytest.fixture(scope="module")
def first_row(tmp_path_factory):
    """Whether a query puts an AIRPORT or a CITY at the top of the list.

    Replays `rankCity`, `rankAirport` and `codeFirst` verbatim from the page
    over the shipped index and airport table, rather than reimplementing the
    ranking -- a reimplementation would test this file's idea of the order.
    """
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not on PATH; the ranking cannot be run")
    index = config.DIST / "index.json"
    airports = config.DIST / "airports.json"
    for path in (index, airports):
        if not path.exists():
            skip_without_dist(f"{path.name} is not built")

    render = APP[APP.index("function render(filter"):]
    render = render[:render.index("\n}\n") + 2]
    # The ranking and the flag, cut out of render() at their own boundaries.
    ranking = render[render.index("  const rankCity ="):render.index("  if (codeFirst)")]

    src = f"""
const fs = require("node:fs");
const meta = JSON.parse(fs.readFileSync({json.dumps(str(index))}, "utf8"));
const ap = JSON.parse(fs.readFileSync({json.dumps(str(airports))}, "utf8"));
{_fold_line()}
const cities = meta.origins.slice().sort((a, b) => a.name.localeCompare(b.name));
for (const c of cities) c.key = fold(c.name);
let airports;
const a = ap;
{_airports_line()}
const UNFILTERED_CAP = 60;
const dn = new Intl.DisplayNames(["en"], {{ type: "region" }});
const countryName = (code) => (code ? (dn.of(code) || code) : "");
// The slice below builds the airport ROWS as DOM nodes on its way to the flag.
// Stubbed rather than trimmed out: trimming would mean deciding where the
// ranking ends, which is the thing under test.
const document = {{
  createDocumentFragment: () => ({{ append() {{}} }}),
  createElement: () => ({{
    dataset: {{}}, style: {{}}, classList: {{ add() {{}} }},
    setAttribute() {{}}, append() {{}},
  }}),
}};
function verdict(query) {{
  const f = fold(query);
  const matched = cities.filter((c) => (c.skey ?? c.key).includes(f));
{ranking}
  return {{
    codeFirst,
    top: codeFirst ? ["airport", apHits[0] && apHits[0][0]] : ["city", hits[0] && hits[0].name],
  }};
}}
process.stdout.write(JSON.stringify(verdict(process.argv[2])));
"""
    path = tmp_path_factory.mktemp("cf") / "cf.cjs"
    path.write_text(src, encoding="utf-8")

    def call(query: str):
        done = subprocess.run([node, str(path), query],
                              capture_output=True, text=True)
        assert done.returncode == 0, done.stderr
        return json.loads(done.stdout)
    return call


#: Departure cities whose complete name folds to a live IATA code. Not a
#: literal list of six taken on trust -- test_the_collisions_are_real below
#: recomputes it from the shipped data and fails if it has moved.
COLLIDING = ("Aba", "Huế", "Ibb", "Jos", "Ufa", "Van")


def test_the_collisions_are_real(first_row):
    """Guards the parametrised tests against becoming a loop over nothing.

    If the roster or the airport table changes so that none of these names is
    a code any more, the tests below would pass by having nothing to check.
    """
    still = [name for name in COLLIDING if first_row(name)["top"][1]]
    assert len(still) == len(COLLIDING), (
        f"only {still} remain in the shipped data; the list needs recomputing")


@pytest.mark.parametrize("name", COLLIDING)
def test_a_city_spelled_like_a_code_departs_from_the_city(first_row, name):
    got = first_row(name)
    assert got["codeFirst"] is False, (
        f"{name!r} is a departure city's whole name and still puts an airport "
        f"first: {got['top']}")
    kind, top = got["top"]
    assert kind == "city", got
    assert top is not None, got


def test_a_code_that_is_nobodys_city_still_comes_first(first_row):
    """The behaviour the flag exists for. If this goes red the fix has taken
    the airport shortcut away with it."""
    for code in ("jfk", "lhr", "icn", "cdg"):
        got = first_row(code)
        assert got["codeFirst"] is True, f"{code!r} no longer ranks its airport first: {got}"
        assert got["top"] == ["airport", code.upper()], got


def test_the_suppression_is_an_exact_match_not_a_prefix(first_row):
    """`ord` must still find O'Hare even though Orlando and Ordos start with
    it: only a WHOLE city name outranks a code."""
    got = first_row("ord")
    assert got["codeFirst"] is True, got
