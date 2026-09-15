"""`railVia()` RUN, not read: what the leg row says when a field is missing.

The owner asked for operator and service number on the rail leg. Coverage is
uneven by region -- `operator` is 92% worldwide but 80% in Africa, `ref` 88%
worldwide but 16% in Africa -- so the absent case is not an edge case, it is
the common case somewhere, and the requirement was that the page degrade
honestly rather than print an empty parenthesis or a bare dash.

Every assertion here is on the STRING the function returns, produced by node
running the real body out of `web/app.js`. A test that read the source for the
presence of `operator` would pass on a version that printed " · " with nothing
either side of it.

Mutations performed and reverted. Recorded with their real outcome, including
the two that came back GREEN, because a mutation log that only lists the
successes is the same kind of claim this file exists to refuse:

  RED
  * `[operator, ref].filter(Boolean)` -> `[operator, ref]`
      -> 5 failed (a lone ref renders " · 101", a lone operator "Korail · ")
  * `return sub ? ... : head` -> always wrap
      -> 2 failed (an empty <span class="via"></span> on every rail leg)
  * `esc(station || "a station")` -> `esc(station)`
      -> 1 failed (an unnamed stop renders " via  (Line)")
  * drop `.map(esc)` from the label line
      -> 1 failed (operator and ref reach innerHTML raw)

  GREEN, and worth knowing why
  * drop `Number.isInteger(operatorIdx) && operatorIdx >= 0`
  * drop the `?? ""` on `rail.operators?.[operatorIdx]`
      -> both still pass. A JavaScript array does NOT index from the end on a
         negative subscript, so `operators[-1]` and `operators[7]` are both
         `undefined`, and `filter(Boolean)` is what actually drops them. The
         two guards are defensive, not load-bearing, and this file does not
         claim otherwise. `filter(Boolean)` is the one to keep.
"""

import json
import pathlib
import shutil
import subprocess

import pytest

APP = (pathlib.Path(__file__).resolve().parents[2] / "web" / "app.js").read_text()


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


def _esc_source() -> str:
    """The page's own `esc`, so the escaping asserted below is the real one."""
    start = APP.index("const esc = (t) =>")
    return APP[start:APP.index(";\n", start) + 1]


@pytest.fixture(scope="module")
def node() -> str:
    exe = shutil.which("node")
    if exe is None:
        pytest.skip("node is not on PATH; the page functions cannot be run")
    return exe


def _render(node, tmp_path, table, operators):
    script = tmp_path / "railvia.mjs"
    script.write_text(f"""
{_esc_source()}
const NO_RAIL = 0xFFFF;
let origin = {{ rail: null }};
{_function("railVia")}
const table = {json.dumps(table)};
const operators = {json.dumps(operators)};
origin.rail = {{ idx: new Uint16Array([0]), table,
                 operators: operators === null ? undefined : operators }};
console.log(JSON.stringify(railVia(0)));
""")
    out = subprocess.run([node, str(script)], capture_output=True, text=True, check=True)
    return json.loads(out.stdout.strip())


ROW = ["Gupo", "Gyeongbu Line", 0, "101"]


def test_both_fields_present_reads_like_a_timetable(node, tmp_path):
    got = _render(node, tmp_path, [ROW], ["Korail"])
    assert got == ' via Gupo (Gyeongbu Line)<span class="via">Korail · 101</span>'


@pytest.mark.parametrize("row,operators,tail", [
    # A missing operator leaves the ref alone -- no leading separator.
    (["Gupo", "Gyeongbu Line", -1, "101"], [], '<span class="via">101</span>'),
    # A missing ref leaves the operator alone -- no trailing separator.
    (["Gupo", "Gyeongbu Line", 0, ""], ["Korail"], '<span class="via">Korail</span>'),
    # Neither: the whole second line is absent, not an empty element.
    (["Gupo", "Gyeongbu Line", -1, ""], [], ""),
])
def test_an_absent_field_prints_nothing_at_all(node, tmp_path, row, operators, tail):
    got = _render(node, tmp_path, [row], operators)
    assert got == f" via Gupo (Gyeongbu Line){tail}"
    assert " · <" not in got and ">· " not in got, "a separator with nothing beside it"
    assert "()" not in got and " - " not in got, "an empty bracket or a bare dash"
    assert 'class="via"></span>' not in got, "an empty second line"


def test_an_unnamed_stop_says_a_station_rather_than_nothing(node, tmp_path):
    """`sources/osm.py` now leaves an unnamed stop node empty instead of
    giving it the route's name. The page must fill that slot with a word."""
    got = _render(node, tmp_path, [["", "Gyeongbu Line", 0, "101"]], ["Korail"])
    assert got.startswith(" via a station (Gyeongbu Line)")


def test_a_row_with_neither_station_nor_line_renders_no_leg_detail(node, tmp_path):
    assert _render(node, tmp_path, [["", "", -1, ""]], []) == ""


def test_a_rail_json_written_before_operator_and_ref_shipped_still_renders(node, tmp_path):
    """Two-element rows and no `operators` array: the shape `dist/` holds
    until the next full rebuild. It must render exactly as it used to."""
    assert _render(node, tmp_path, [["Gupo", "Gyeongbu Line"]], None) == \
        " via Gupo (Gyeongbu Line)"


def test_an_operator_ordinal_the_table_cannot_resolve_is_dropped_silently(node, tmp_path):
    """A stale or truncated `operators` array must not print `undefined`.

    Both an out-of-range ordinal and the NO_OPERATOR sentinel resolve to
    `undefined` in JavaScript, and `filter(Boolean)` is what removes them --
    verified by mutation, and by the two mutations that did NOT redden. The
    failure this prevents is a leg row reading "undefined · 101".
    """
    assert _render(node, tmp_path, [["Gupo", "Gyeongbu Line", 7, "101"]], ["Korail"]) == \
        ' via Gupo (Gyeongbu Line)<span class="via">101</span>'
    assert _render(node, tmp_path, [["Gupo", "Gyeongbu Line", -1, "101"]], ["Korail"]) == \
        ' via Gupo (Gyeongbu Line)<span class="via">101</span>'


def test_every_osm_string_reaching_the_row_is_escaped(node, tmp_path):
    """Station, line, operator and ref are all community-edited OpenStreetMap
    values and all four land in an `innerHTML`."""
    got = _render(node, tmp_path,
                  [['<img src=x onerror=alert(1)>', "L&", 0, '" onmouseover="x']],
                  ['<script>'])
    for bad in ("<img", "<script>", 'onmouseover="x'):
        assert bad not in got, f"{bad!r} reached the DOM unescaped"
    assert "&lt;img" in got and "&lt;script&gt;" in got and "&quot;" in got
