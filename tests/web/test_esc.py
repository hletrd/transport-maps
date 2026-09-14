"""Run `esc()` and check what it actually escapes.

Every untrusted string that reaches the DOM as HTML -- GeoNames and OurAirports
names, OSM station and route names, Nominatim addresses -- goes through this
one two-line arrow at `app.js:28-29`. Cycle 11's security lane traced all six
HTML sinks and found the surface closed *because of it*, and then found that
nothing in 772 tests asserts anything about it.

Worse than nothing: `tests/web/test_itinerary_grid.py` -- the one harness that
executes its call sites -- declared `const esc = (t) => String(t)`, so the
escape was switched off in the only place it ran. Deleting the `"` replacement
opened live XSS through `data-tip="..."` and left the whole suite green.

Three traps this file is built around, each of which produces a test that
passes while proving nothing:

1. `esc` is a `const` arrow, not `function esc(`, so the `_function()` slicer
   every other test in this directory uses cannot see it. The slicer here
   self-checks that all four `.replace(` calls landed inside the slice.
2. A single occurrence of a character cannot detect a missing `/g`. Every
   character appears at least twice in at least one case.
3. `assert "&lt;" in esc("<")` passes when the `&` replacement is moved last
   and the real output is `&amp;lt;`. Every assertion here is exact equality.

The expected strings are written out by hand from the HTML specification, not
copied from a run of the code under test.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess

import pytest

from transport_maps import config

APP = (config.ROOT / "web" / "app.js").read_text(encoding="utf-8")


def _const_arrow(name: str) -> str:
    """The verbatim source of a top-level `const NAME = ...;` arrow.

    Ends at the first semicolon that is not inside a string or a regex
    literal, which is what `.replace(/"/g, "&quot;")` is full of.
    """
    start = APP.index(f"const {name} = ")
    i, depth, quote = start, 0, None
    while i < len(APP):
        c = APP[i]
        if quote:
            if c == "\\":
                i += 2
                continue
            if c == quote:
                quote = None
        elif c in "\"'`":
            quote = c
        elif c == "/" and APP[i + 1] not in "/*":
            # a regex literal: /.../flags -- skip to its unescaped closing /
            j = i + 1
            while j < len(APP) and APP[j] != "/":
                j += 2 if APP[j] == "\\" else 1
            i = j
        elif c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
        elif c == ";" and depth == 0:
            return APP[start:i + 1]
        i += 1
    raise AssertionError(f"const {name} has no terminating semicolon")


ESC_SRC = _const_arrow("esc")


def test_the_slice_really_contains_the_whole_helper():
    """A slicer that silently truncates gives a green test of nothing. This is
    the guard on the guard.
    """
    assert ESC_SRC.count(".replace(") == 4, (
        f"esc() was sliced with {ESC_SRC.count('.replace(')} replacements, not "
        f"4 -- the slicer is wrong, or esc() changed:\n{ESC_SRC}")
    for ch in ("&amp;", "&lt;", "&gt;", "&quot;"):
        assert ch in ESC_SRC, f"{ch} is not in the sliced source"


@pytest.fixture(scope="module")
def node() -> str:
    exe = shutil.which("node")
    if exe is None:
        pytest.skip("node is not on PATH; esc() cannot be run")
    return exe


@pytest.fixture(scope="module")
def esc(node: str, tmp_path_factory):
    path = tmp_path_factory.mktemp("esc") / "esc.cjs"
    path.write_text(
        ESC_SRC + "\nprocess.stdout.write(JSON.stringify("
        "esc(JSON.parse(process.argv[2])[0])));\n", encoding="utf-8")

    def call(value):
        done = subprocess.run([node, str(path), json.dumps([value])],
                              capture_output=True, text=True, check=True)
        return json.loads(done.stdout)
    return call


# (input, exact expected output). Every character appears twice somewhere, so a
# missing /g cannot hide.
CASES = [
    ("&", "&amp;"),
    ("<", "&lt;"),
    (">", "&gt;"),
    ('"', "&quot;"),
    ("&&", "&amp;&amp;"),
    ("<<", "&lt;&lt;"),
    (">>", "&gt;&gt;"),
    ('""', "&quot;&quot;"),
    ("a<b>c&d\"e", "a&lt;b&gt;c&amp;d&quot;e"),
    # Already-escaped input must be escaped AGAIN, not left alone: proof that
    # & is replaced first. If & went last this would come back "&amp;".
    ("&amp;", "&amp;amp;"),
    ("&lt;script&gt;", "&amp;lt;script&amp;gt;"),
    # Unaffected characters, including the apostrophe (see below).
    ("Côte d'Ivoire", "Côte d'Ivoire"),
    ("Ho Chi Minh City", "Ho Chi Minh City"),
    ("서울", "서울"),
    ("", ""),
]


@pytest.mark.parametrize("raw,expected", CASES)
def test_esc_escapes_exactly_these(esc, raw, expected):
    assert esc(raw) == expected


@pytest.mark.parametrize("value,expected", [
    (None, "null"), (42, "42"), (0, "0"), (False, "false"),
])
def test_esc_coerces_rather_than_throwing(esc, value, expected):
    """Sinks pass whatever the data held. `String(t)` is load-bearing: without
    it `null.replace` throws inside a template literal and the readout goes
    blank with no message -- the blank-globe failure CLAUDE.md is written
    around.
    """
    assert esc(value) == expected


def test_a_text_context_payload_cannot_open_a_tag(esc):
    """The sinks at app.js:350, :2540 and :2546 interpolate into element text."""
    out = esc('<img src=x onerror=alert(1)>')
    assert "<" not in out and ">" not in out
    assert out == "&lt;img src=x onerror=alert(1)&gt;"


def test_an_attribute_context_payload_cannot_close_the_attribute(esc):
    """This is the case a text-only test misses, and the one that matters.

    `ap()` (app.js:2144) and `mode()` (:2148) interpolate an OurAirports or OSM
    name into `data-tip="..."`. Only the `"` replacement stands between a
    hostile name and an event handler on that element.

    Mutation performed and reverted: delete `.replace(/"/g, "&quot;")` -> red
    here, and green across the rest of tests/web/.
    """
    payload = '" onmouseover="alert(1)'
    out = esc(payload)
    assert '"' not in out, "the attribute can be closed; this is live XSS"
    assert out == "&quot; onmouseover=&quot;alert(1)"
    # ...and the element that results really does keep it inside the attribute.
    assert f'data-tip="{out}"'.count('"') == 2


def test_the_apostrophe_is_deliberately_not_escaped_and_no_sink_needs_it():
    """`esc` leaves `'` alone, which is safe ONLY while no sink interpolates
    into a single-quoted attribute. That was true when cycle 12 checked it and
    nothing was holding it true. This is what holds it.

    Mutation performed and reverted: change any `data-tip="` in app.js to
    `data-tip='` -> red.
    """
    assert "&#39;" not in ESC_SRC and "&apos;" not in ESC_SRC, (
        "esc() now escapes the apostrophe; this test is stale, delete it")
    singles = re.findall(r"=\'\$\{", APP)
    assert not singles, (
        f"{len(singles)} sink(s) interpolate into a single-quoted attribute, "
        "which esc() does not protect: either escape ' or quote with \"")


def test_every_html_sink_routes_through_esc():
    """A seventh sink that forgets `esc` must fail here, not on the live site.

    The dangerous shape is a template literal containing `${` assigned to
    innerHTML. Each one below is checked to interpolate only through `esc(`,
    a nested helper that escapes its own inputs, or a number formatter.
    """
    for banned in ("outerHTML", "insertAdjacentHTML", "document.write",
                   "srcdoc", "createContextualFragment", "setHTML"):
        assert banned not in APP, f"{banned} is a new HTML sink with no escape"

    sinks = [m for m in re.finditer(r"\.innerHTML\s*=\s*(.+)", APP)]
    assert len(sinks) >= 5, "the sink inventory found nothing; the regex is stale"
    for m in sinks:
        expr = m.group(1)
        if "${" not in expr:
            continue                      # a literal string is not a sink
        line = APP[:m.start()].count("\n") + 1
        interpolations = re.findall(r"\$\{([^}]*)\}", expr)
        for piece in interpolations:
            safe = ("esc(" in piece or "railVia(" in piece or "mode(" in piece
                    or "ap(" in piece or piece.strip() in ("big", "unit", "band")
                    or piece.startswith("t >= "))
            assert safe, (
                f"app.js:{line} interpolates `{piece}` into innerHTML without "
                "esc(); if it is provably safe, name it in this allow-list "
                "with the reason")


def test_railvia_escapes_its_own_osm_strings():
    """It used to return raw text and depend on its single call site wrapping
    it. A second call site would have been stored XSS with every gate green.

    Mutation performed and reverted: revert railVia to the unescaped body and
    drop the caller's wrapper -> red.
    """
    start = APP.index("function railVia(")
    body = APP[start:APP.index("\n}", start)]
    assert "${esc(station" in body and "${esc(line)" in body, (
        "railVia interpolates an OSM name without escaping it")
    # And the caller must not double-escape what railVia has already escaped.
    assert "esc(railVia(" not in APP, (
        "railVia's output is escaped twice; station names will show &amp;")
