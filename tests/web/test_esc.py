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

from tests.web import _js
from transport_maps import config

APP = (config.ROOT / "web" / "app.js").read_text(encoding="utf-8")


def _const_arrow(name: str) -> str:
    """The verbatim source of a top-level `const NAME = ...;` arrow.

    Ends at the first semicolon that is not inside a string or a regex
    literal, which is what `.replace(/"/g, "&quot;")` is full of.
    """
    return _js.statement(f"const {name} = ")


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


def _sink_statements() -> list[tuple[int, str]]:
    r"""Every `.innerHTML = <expr>;` with the WHOLE expression, not its first line.

    The previous inventory used `re.finditer(r"\.innerHTML\s*=\s*(.+)")`, and
    `.` does not match a newline. Two of the six sinks span more than one
    line, so the loop below them never ran: the first line of each is a
    condition with no `${` in it, the `continue` fired, and the interpolations
    -- including two that carry a city name and a place name straight from
    fetched JSON -- were never looked at. Deleting `esc()` from `app.js:2704`
    or `:2785` was live XSS with all 362 tests in this directory green, proved
    by mutation.

    The give-away that it had never worked is still in the allow-list this
    test ships: `piece.startswith("t >= ")` names the CONDITION at `:2785`, so
    whoever wrote it believed the scanner was capturing that statement. It was
    capturing the condition and calling it an interpolation.

    Statement ends are found by scanning with a stack, so a `;` inside a
    string, a template, a nested call or an object literal does not end it.
    """
    out: list[tuple[int, str]] = []
    for m in re.finditer(r"\.innerHTML\s*=\s*", APP):
        i, stack = m.end(), []
        while i < len(APP):
            c = APP[i]
            nxt = APP[i + 1] if i + 1 < len(APP) else ""
            top = stack[-1] if stack else None
            if top in ('"', "'"):
                if c == "\\":
                    i += 2
                    continue
                if c == top:
                    stack.pop()
            elif top == "`":
                if c == "\\":
                    i += 2
                    continue
                if c == "`":
                    stack.pop()
                elif c == "$" and nxt == "{":
                    stack.append("{")
                    i += 2
                    continue
            else:
                if c == "/" and nxt == "/":
                    i = APP.index("\n", i)
                    continue
                if c in "\"'`([{":
                    stack.append(c)
                elif c in ")]}":
                    if not stack:
                        break
                    stack.pop()
                elif c == ";" and not stack:
                    break
            i += 1
        out.append((APP[:m.start()].count("\n") + 1, APP[m.end():i]))
    return out


def _interpolations(expr: str) -> list[str]:
    """The `${...}` parts of a template, brace-balanced.

    `[^}]*` -- what the old inventory used -- stops at the first `}` , so an
    interpolation containing an object literal or a nested template was read as
    a truncated fragment and matched against the allow-list as one.
    """
    out, i = [], 0
    while True:
        j = expr.find("${", i)
        if j < 0:
            return out
        k, depth = j + 2, 1
        while k < len(expr) and depth:
            if expr[k] == "{":
                depth += 1
            elif expr[k] == "}":
                depth -= 1
            k += 1
        out.append(expr[j + 2:k - 1])
        i = k


# Interpolations that reach innerHTML without `esc(`, each with the reason it
# is safe. A new sink must either escape or be argued for HERE -- which is the
# point of an allow-list: it makes the argument visible in review.
SAFE_PIECES = {
    # Formatters that produce digits and a unit from a number.
    "big": "fmtTime()'s figure: a number formatted by the page",
    "unit": "fmtTime()'s unit: one of a fixed set of literals",
    "band": "bandRangeOf()'s label, built from index.json's numeric band edges",
    'unit ? " " + unit : ""': "the same fixed unit set, or the empty string",
    'band ? " · " + band : ""': "the same band label, or the empty string",
    'active ? " · from " + esc(active.name) : ""': "escapes the only fetched value",
}

# Sinks assigned a bare variable rather than a template. Static analysis cannot
# clear these, so each names the guard that does.
SAFE_VARIABLE_SINKS = {
    "text": "itinerary leg text, built at app.js:2294-2376 only from ap(), "
            "mode(), railVia() and fmtDur(); asserted by "
            "tests/web/test_itinerary_grid.py",
}


def test_every_html_sink_routes_through_esc():
    """A seventh sink that forgets `esc` must fail here, not on the live site.

    The dangerous shape is a template literal containing `${` assigned to
    innerHTML. Each one below must interpolate only through `esc(`, a nested
    helper that escapes its own inputs, or a named entry in SAFE_PIECES.

    Mutation performed and reverted: drop `esc()` from `${esc(active.name)}`
    at app.js:2704 -> red. Same at `${esc(where)}` at :2785 -> red. Both were
    GREEN before this inventory captured whole statements.
    """
    for banned in ("outerHTML", "insertAdjacentHTML", "document.write",
                   "srcdoc", "createContextualFragment", "setHTML"):
        assert banned not in APP, f"{banned} is a new HTML sink with no escape"

    sinks = _sink_statements()
    assert len(sinks) >= 5, "the sink inventory found nothing; the scanner is stale"
    # The scanner's own guard: at least three sinks MUST span more than one
    # line, because three do. If that stops being true the scanner has probably
    # started truncating again, and a one-line capture would look identical.
    multiline = [line for line, expr in sinks if "\n" in expr]
    assert len(multiline) >= 2, (
        f"only {len(multiline)} multi-line sink(s) captured; the statement "
        "scanner is truncating, which is exactly the old defect")

    checked = 0
    for line, expr in sinks:
        pieces = _interpolations(expr)
        if not pieces:
            # A bare variable, or a literal string. A literal is not a sink.
            name = expr.strip().rstrip(";").strip()
            if name.isidentifier():
                assert name in SAFE_VARIABLE_SINKS, (
                    f"app.js:{line} assigns the variable `{name}` to innerHTML. "
                    "Static analysis cannot clear that: escape at the point of "
                    "use, or name it in SAFE_VARIABLE_SINKS with the guard that "
                    "does.")
            continue
        for piece in pieces:
            checked += 1
            body = piece.strip()
            # A helper is trusted by name only because
            # test_every_html_helper_escapes_what_it_returns checks its body.
            # By name, not by substring: `"ap(" in body` also admitted `.map(`.
            safe = "esc(" in body or bool(_helper_calls(body)) or body in SAFE_PIECES
            assert safe, (
                f"app.js:{line} interpolates `{body}` into innerHTML without "
                "esc(); if it is provably safe, name it in SAFE_PIECES with "
                "the reason")
    # And the count, so a scanner that silently stops finding interpolations
    # cannot pass by checking nothing. Eleven today across the five templates.
    assert checked >= 10, (
        f"only {checked} interpolation(s) were checked; the extractor is stale")


# --- C15-5.5 / DEF16-23: one hop further, into the helpers --------------------
#
# The sink check above trusts `ap(`, `mode(` and `railVia(` by name, and never
# saw `describe()` at all: the `#where` sink reaches it as
# `placeLine(lat, lng) + ...`, a call OUTSIDE any template, which the
# interpolation scan does not read. So `esc()` could be deleted from inside
# any of them with every gate green -- and `describe()` escapes GeoNames'
# community-edited name, region and country, which `emit/places.py` writes
# verbatim. Each helper whose RETURN VALUE is HTML is now checked by the same
# rules as a sink, and a sink may call, outside a template, only `esc` or one
# of these.

#: The helpers whose output is HTML, sliced from app.js. `ap` and `mode` are
#: arrows local to renderLegsInto().
HTML_HELPERS = {
    "describe": _js.function("describe"),
    "placeLine": _js.function("placeLine"),
    "railVia": _js.function("railVia"),
    "ap": _js.block("  const ap = (code) => {", after="=>"),
    "mode": _js.block("  const mode = (name) => {", after="=>"),
}
#: Functions whose output is not HTML-bearing: digits, units, hemisphere letters.
SAFE_FORMATTERS = {
    "fmtCoord": "degrees to one decimal and N/S/E/W, from two numbers",
}

_CALL = re.compile(r"(?<![\w.$])([A-Za-z_$][\w$]*)\s*\(")


def _helper_calls(code: str) -> set[str]:
    return {m for m in _CALL.findall(code) if m in HTML_HELPERS}


def _piece_is_safe(piece: str, body: str, depth: int = 0) -> bool:
    """Whether an interpolated expression inside a helper's `body` is escaped.

    Escaped means: it calls `esc(`; or it calls another checked helper; or it
    calls a SAFE_FORMATTER; or it is a local `const` whose own initialiser is
    one of those, a template whose every piece is, or a list escaped with
    `.map(esc)` -- railVia's operator line.
    """
    piece = piece.strip()
    if "esc(" in piece or _helper_calls(piece):
        return True
    if any(f in SAFE_FORMATTERS for f in _CALL.findall(piece)) and piece.endswith(")"):
        return True
    if depth < 4 and piece.isidentifier() and f"const {piece} = " in body:
        init = _js.statement(f"const {piece} = ", body)[len(f"const {piece} = "):-1]
        if ".map(esc)" in init:
            return True
        pieces = _interpolations(init)
        if pieces:
            return all(_piece_is_safe(p, body, depth + 1) for p in pieces)
        return _piece_is_safe(init, body, depth + 1)
    return False


def test_every_html_helper_escapes_what_it_returns():
    """DEF16-23. Every `${...}` in a helper's templates is escaped.

    Mutations performed and reverted, each -> red here. The first three were
    GREEN across the whole of tests/web without this test (measured, with the
    two new tests deselected); the last two were already caught by node runs
    in test_itinerary_grid.py and test_rail_via.py, and are red here as well:
    - describe(): `${esc(lead)}` -> `${lead}` (a GeoNames name).
    - describe(): `${esc(where)}` -> `${where}` (GeoNames region, country).
    - mode(): `data-tip="${esc(tip)}"` -> `${tip}`.
    - ap(): `data-tip="${esc(a[1])}, ...` -> `${a[1]}` (an OurAirports name).
    - railVia(): drop `.map(esc)` from the operator line (OSM operator, ref).
    """
    checked = 0
    for name, body in HTML_HELPERS.items():
        assert body.rstrip().endswith("}"), f"{name} sliced short:\n{body}"
        for piece in _interpolations(body):
            checked += 1
            assert _piece_is_safe(piece, body), (
                f"{name}() interpolates `{piece.strip()}` into the HTML it returns "
                "without esc(); its callers trust it by name, so this reaches a sink")
    # Thirteen today. A slicer that lost a helper's body would check nothing.
    assert checked >= 12, f"only {checked} helper interpolation(s) checked"


def test_a_sink_calls_only_esc_and_checked_helpers_outside_its_templates():
    """The hop the interpolation scan could not see: `#where` is assigned
    `placeLine(lat, lng) + ...`, and placeLine() returns describe()'s HTML.
    A call in a sink's plain code must be `esc` or a checked HTML helper.

    Mutation performed and reverted: route the `#where` sink through an
    unchecked wrapper, `placeLine2(lat, lng)` -> red here, GREEN across the
    rest of tests/web.
    """
    seen = set()
    for line, expr in _sink_statements():
        code, j = [], 0
        while j < len(expr):
            k = _js.skip(expr, j)
            code.append(" " * (k - j) if k != j else expr[j])
            j = k if k != j else j + 1
        for call in _CALL.findall("".join(code)):
            seen.add(call)
            assert call == "esc" or call in HTML_HELPERS, (
                f"app.js:{line} puts `{call}(...)` into innerHTML outside any "
                "template; check it as an HTML helper or escape its result")
    assert "placeLine" in seen, (
        "the #where sink no longer calls placeLine(); re-derive this test, it "
        "is what carries describe()'s GeoNames strings to the page")


def test_the_allow_list_has_no_dead_entries():
    """An entry for an interpolation that no longer exists is an argument
    nobody has to make again. Worse, it can silently cover a NEW piece that
    happens to be spelled the same.
    """
    live = {p.strip() for _, expr in _sink_statements() for p in _interpolations(expr)}
    stale = {k for k in SAFE_PIECES if k not in live and k not in ("big", "unit", "band")}
    assert not stale, f"SAFE_PIECES entries no longer present in app.js: {stale}"


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
