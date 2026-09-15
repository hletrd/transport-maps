"""The white dot on a departure-city label sits on the city it departs from.

Measured on the live site at zoom 8 over Tokyo, before this was fixed: two
labels for one city. One read "Tokyo", carried the accent dot and sat 0.3 px
from the charted coordinate; the other read "Ota", carried a WHITE dot, sat
56.6 px away, and its title was "Depart from Tokyo".

Two causes, one per function pinned here.

`dottedCityRows` -- every gazetteer row within 15 km of a charted city became a
button for it, so one city could claim several. Over the shipped
`dist/places.json` and `dist/index.json`, 595 rows claimed 511 cities: "Ota"
departed from Tokyo, "Queens" from New York, "Johor Bahru" from Singapore,
which is a different country. Only the nearest row to a city may carry its
button.

`labelPlacement` -- the button was drawn at the ROW's coordinate under the
ROW's name, so its dot missed the city it departs from by up to 14.72 km and
its visible text named a different place from its accessible name (WCAG 2.5.3,
Label in Name).

Both are pure functions of plain arrays and are RUN here under Node, together
with the real `originNear` and `haversineKm` they are built on. The fixture is
synthetic so the distances are arithmetic this file can state; the figures in
the docstring above come from the shipped artefacts and are checked separately
by test_the_shipped_gazetteer_gives_each_city_one_button.

Mutations performed and reverted, each confirmed RED:
  * `labelPlacement`'s city arm -> `{ lat: row[3], lon: row[4], name: city.name }`
      -> 2 failed
  * `labelPlacement`'s city arm -> `{ lat: city.lat, lon: city.lon, name: row[0] }`
      -> 2 failed
  * `dottedCityRows`: `if (!cur || km < cur.km)` -> `if (true)`, last row wins
      -> 1 failed
  * `dottedCityRows`: `if (!cur || km < cur.km)` -> `if (!cur)`, first row wins
      -> 1 failed. BOTH of these were green against a single row order, and
         neither of them is "keep the nearest" -- which is why ROW_ORDERS tests
         the two Tokyo rows each way round.
  * `dottedCityRows`: drop the dedupe, emit every matching row
      -> 2 failed
  * `haversineKm`: 6371.0088 -> 6371.0
      -> 1 failed
"""

from __future__ import annotations

import json
import math
import shutil
import subprocess

import pytest

from transport_maps import config

APP = (config.ROOT / "web" / "app.js").read_text(encoding="utf-8")


def _const(name: str) -> str:
    """The verbatim source of a top-level `const NAME = ...;`.

    `originNear` gained three module-level dependencies in cycle 15 when its
    linear scan over all 553 origins became a latitude-band prune, and this
    harness went red with `ReferenceError: KM_PER_DEG_LAT is not defined` --
    the slicer had no way to know. Ends at the first semicolon outside any
    bracket, which is enough for the two declarations it is used for and is
    checked by test_the_harness_defines_everything_origin_near_needs rather
    than assumed.
    """
    start = APP.index(f"const {name} = ")
    depth = 0
    for j in range(start, len(APP)):
        c = APP[j]
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
        elif c == ";" and depth == 0:
            return APP[start:j + 1]
    raise AssertionError(f"const {name} has no terminating semicolon")


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


#: Three charted cities. TOWN is far enough from all of them to stay a place.
CITIES = [
    {"slug": "tokyo", "name": "Tokyo", "lat": 35.6762, "lon": 139.6503},
    {"slug": "osaka", "name": "Osaka", "lat": 34.6937, "lon": 135.5023},
]
#: Gazetteer rows: [name, ?, ?, lat, lon]. "Tokyo" is 0 km from the charted
#: Tokyo; "Ota" is about 12 km away and must lose; "Kyoto" is 40 km from Osaka
#: and matches nothing.
TOKYO_ROW = ["Tokyo", None, None, 35.6762, 139.6503]
OTA_ROW = ["Ota", None, None, 35.5613, 139.7161]
OSAKA_ROW = ["Osaka", None, None, 34.6937, 135.5023]
KYOTO_ROW = ["Kyoto", None, None, 35.0116, 135.7681]
ROWS = [OTA_ROW, TOKYO_ROW, OSAKA_ROW, KYOTO_ROW]
#: Both orderings of the two Tokyo rows. Tested BOTH ways round on purpose: with
#: only one, "keep the last match" and "keep the first match" are both green,
#: and neither is "keep the nearest". That mutation survived the first draft.
ROW_ORDERS = {
    "near-first": [TOKYO_ROW, OTA_ROW, OSAKA_ROW, KYOTO_ROW],
    "far-first": [OTA_ROW, TOKYO_ROW, OSAKA_ROW, KYOTO_ROW],
}


def _run(node: str, tmp_path, tail: str, rows=None, cities=None) -> object:
    body = f"""
const meta = {{ origins: {json.dumps(cities if cities is not None else CITIES)} }};
const ROWS = {json.dumps(rows if rows is not None else ROWS)};
{_function("haversineKm")}
{_const("KM_PER_DEG_LAT")}
{_const("originsByLat")}
{_function("lowerBoundLat")}
{_function("originNear")}
{_function("dottedCityRows")}
{_function("labelPlacement")}
{tail}
"""
    script = tmp_path / "labels.mjs"
    script.write_text(body, encoding="utf-8")
    out = subprocess.run([node, str(script)], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


#: Module-level names `originNear` reads. Assembling the harness without one
#: of these fails in node with a bare `ReferenceError`, several frames deep in
#: a generated file, which is a poor way to learn that a slicer needs updating.
ORIGIN_NEAR_DEPS = ("KM_PER_DEG_LAT", "originsByLat", "lowerBoundLat", "haversineKm")


def test_the_harness_defines_everything_origin_near_needs(node, tmp_path) -> None:
    """The guard on the harness.

    `originNear` was a self-contained loop over `meta.origins` until cycle 15
    gave it a latitude-band prune and three module-level dependencies. Every
    test in this file went red with `ReferenceError: KM_PER_DEG_LAT is not
    defined`. Read the identifiers out of the real function and check the
    assembled body declares each one, so the NEXT dependency says so here
    instead.
    """
    src = _function("originNear")
    body = _run(node, tmp_path, "console.log(JSON.stringify(Object.keys({})));")
    assert body == [], "the probe tail should print an empty key list"
    assembled = "\n".join((
        _function("haversineKm"), _const("KM_PER_DEG_LAT"),
        _const("originsByLat"), _function("lowerBoundLat"), _function("originNear")))
    for dep in ORIGIN_NEAR_DEPS:
        if dep == "originNear":
            continue
        assert dep in src or dep == "haversineKm", (
            f"{dep} is listed as a dependency of originNear but is not read by "
            "it; the list has gone stale")
        assert f"const {dep}" in assembled or f"function {dep}(" in assembled, (
            f"the harness does not define {dep}, which originNear reads -- node "
            "would fail with a bare ReferenceError instead of this message")


def test_a_dotted_label_is_placed_on_the_city_not_on_the_gazetteer_row(
        node, tmp_path) -> None:
    """The dot claims to mark the city, so it must be on the city. The row it
    was matched from is a different point, and using it is what put a white dot
    56.6 px from Tokyo."""
    got = _run(node, tmp_path, """
const city = meta.origins[0];
const row = ROWS[0];                       // "Ota", about 12 km from Tokyo
console.log(JSON.stringify({
  dotted: labelPlacement(row, city),
  plain:  labelPlacement(row, null),
  apart:  haversineKm(row[3], row[4], city.lat, city.lon),
}));
""")
    assert got["apart"] > 5, (
        "the fixture row is too close to the city to tell the two apart; "
        f"it is {got['apart']:.2f} km away")
    assert got["dotted"]["lat"] == pytest.approx(CITIES[0]["lat"]), (
        f"the dotted label sits at {got['dotted']} and not on Tokyo")
    assert got["dotted"]["lon"] == pytest.approx(CITIES[0]["lon"])
    assert got["dotted"]["name"] == "Tokyo", (
        f"the label reads {got['dotted']['name']!r} while its accessible name "
        "says 'Depart from Tokyo' (WCAG 2.5.3, Label in Name)")
    # The control: a plain place label still belongs to its own row.
    assert got["plain"]["lat"] == pytest.approx(ROWS[0][3])
    assert got["plain"]["lon"] == pytest.approx(ROWS[0][4])
    assert got["plain"]["name"] == "Ota"


@pytest.mark.parametrize("order", sorted(ROW_ORDERS))
def test_one_button_per_city_and_the_nearest_row_wins(node, tmp_path, order) -> None:
    """Two rows are inside Tokyo's radius. Only the NEARER may be its button;
    the other goes back to being a place name -- whichever order they arrive
    in, which is what makes this about distance and not about position."""
    got = _run(node, tmp_path, """
const m = dottedCityRows(ROWS);
console.log(JSON.stringify(ROWS.map((r, i) => [r[0], m.get(i)?.slug ?? null])));
""", rows=ROW_ORDERS[order])
    by_row = dict(got)
    assert by_row["Tokyo"] == "tokyo", "the row that IS Tokyo lost its own button"
    assert by_row["Ota"] is None, (
        "'Ota' is still a button that departs from Tokyo, 12 km from Tokyo")
    assert by_row["Osaka"] == "osaka"
    assert by_row["Kyoto"] is None, "Kyoto is 40 km from Osaka and charts neither"
    assert sorted(v for v in by_row.values() if v) == ["osaka", "tokyo"], (
        f"a city claimed more than one button: {got}")


def test_the_radius_is_still_what_stops_the_next_town_over(node, tmp_path) -> None:
    """The 15 km radius is the guard that stopped 'Incheon' departing from
    Seoul. Widening it must still not be free: a row outside it is never a
    button, however close it is to being one."""
    rows = [["Just outside", None, None, 35.6762 + 16 / 111.0, 139.6503]]
    got = _run(node, tmp_path, """
console.log(JSON.stringify({
  tight: [...dottedCityRows(ROWS, 15).values()].map((c) => c.slug),
  wide:  [...dottedCityRows(ROWS, 30).values()].map((c) => c.slug),
}));
""", rows=rows)
    assert got["tight"] == [], "a row 16 km away became a departure button at 15 km"
    assert got["wide"] == ["tokyo"], (
        "the radius is not doing anything: the same row is excluded at 30 km too")


def test_the_shipped_gazetteer_gives_each_city_one_button(node, tmp_path) -> None:
    """Against the real dist/ artefacts, not a fixture. Before the fix 595 rows
    claimed 511 cities; every one of the extra 84 was a button that departed
    from somewhere it was not."""
    dist = config.ROOT / "dist"
    places, index = dist / "places.json", dist / "index.json"
    if not (places.exists() and index.exists()):
        pytest.skip("dist/ is not built here; nothing to measure against")
    rows = json.loads(places.read_text(encoding="utf-8"))["places"][:900]
    cities = json.loads(index.read_text(encoding="utf-8"))["origins"]
    got = _run(node, tmp_path, """
const m = dottedCityRows(ROWS);
const slugs = [...m.values()].map((c) => c.slug);
let worst = 0, worstName = null;
for (const [i, c] of m) {
  const km = haversineKm(ROWS[i][3], ROWS[i][4], c.lat, c.lon);
  if (km > worst) { worst = km; worstName = c.name; }
}
console.log(JSON.stringify({
  buttons: slugs.length, unique: new Set(slugs).size, worst, worstName,
  // what a dotted label is now placed at, for the worst offender
  onCity: [...m].every(([i, c]) => {
    const p = labelPlacement(ROWS[i], c);
    return p.lat === c.lat && p.lon === c.lon && p.name === c.name;
  }),
}));
""", rows=rows, cities=cities)
    assert got["buttons"] == got["unique"], (
        f"{got['buttons']} buttons for {got['unique']} cities: a city has more "
        "than one")
    assert got["buttons"] > 400, (
        f"only {got['buttons']} cities got a label; the matcher has stopped "
        "matching")
    assert got["onCity"] is True, (
        "a dotted label is placed somewhere other than the city it departs from")
    # The row a city is matched FROM can still be far away; what matters is
    # that the label is not drawn there. This records the real worst case.
    assert got["worst"] < 15, "a match escaped the radius"
    assert got["worst"] > 5, (
        f"the worst match is only {got['worst']:.2f} km out, so this test is no "
        "longer exercising the case it was written for")


def test_the_haversine_the_matcher_uses_is_the_real_one(node, tmp_path) -> None:
    """`dottedCityRows` ranks by distance, so a broken distance silently picks
    the wrong row. Checked against a value derived here, not from app.js."""
    a, b = CITIES[0], CITIES[1]
    got = _run(node, tmp_path, "console.log(JSON.stringify(haversineKm("
               f'{a["lat"]}, {a["lon"]}, {b["lat"]}, {b["lon"]})));')
    r = 6371.0088
    p = math.pi / 180
    expected = 2 * r * math.asin(math.sqrt(
        math.sin((b["lat"] - a["lat"]) * p / 2) ** 2
        + math.cos(a["lat"] * p) * math.cos(b["lat"] * p)
        * math.sin((b["lon"] - a["lon"]) * p / 2) ** 2))
    assert expected == pytest.approx(395, abs=10), "re-derive the reference"
    assert got == pytest.approx(expected, abs=1e-6)
