"""The shared app.js slicer (`tests/web/_js.py`) is itself under test.

Every node-run test in this directory runs whatever the slicer hands it, so a
slicer that stops early or runs long makes them all test the wrong thing --
and the old per-file matchers did both: a destructured parameter's braces were
taken for the body (C12-10), and a `}` inside a string or a comment was
counted as code.

Mutations performed and reverted, each against `_js.py`:
- `function()` takes `src.index("{", start)` as the body brace (the old naive
  matcher) -> red on the destructured-parameter case and on paintOrigin.
- `skip()` returns `i` for strings (no literal skipping) -> red on the string,
  template and whole-file cases.
- `_regex_may_start()` always returns False -> red on the regex case and on
  the whole-file scan (app.js's `.replace(/[&<>"]/g, ...)` opens a "string").
"""

from __future__ import annotations

import re

import pytest

from tests.web import _js


def test_a_destructured_parameter_is_not_taken_for_the_body() -> None:
    src = "function f(o, { a = 1, b = {} } = {}) {\n  return o + a;\n}\nconst after = 1;\n"
    assert _js.function("f", src) == src[:src.index("\nconst")]


@pytest.mark.parametrize("inner", [
    'const s = "}";',
    "const s = '}{';",
    "const s = `${ {a: 1}.a } }`;",
    "const s = `outer ${`inner ${ '}' }`}`;",
    "// a comment that closes a block }",
    "/* and } one { that */",
    r"const r = /[}]\}/g;",
    "const q = (a) / 2 / (b);",
    "const q = x.replace(/[&<>\"]/g, (c) => c);",
    "if (x) return /}/.test(y);",
])
def test_a_brace_inside_a_literal_or_a_comment_is_not_code(inner: str) -> None:
    src = f"function f(x, y, a, b) {{\n  {inner}\n  return 1;\n}}\nfunction g() {{\n  return 2;\n}}\n"
    got = _js.function("f", src)
    assert got.endswith("return 1;\n}"), got
    assert "function g" not in got


def test_statement_and_block_follow_the_same_rules() -> None:
    src = 'const esc = (t) => String(t).replace(/;/g, ";");\nconst next = 1;\n'
    assert _js.statement("const esc = ", src) == src[:src.index("\n")]
    src = 'const f = (o) => {\n  const s = "}";\n  return s;\n};\nconst g = 1;\n'
    assert _js.block("const f = ", src, after="=>") == src[:src.index(";\nconst g")]


def test_the_whole_of_app_js_scans_balanced() -> None:
    """Every bracket in app.js closes, and nothing closes that was not opened.

    This is the check on the regex heuristic: one `/` misread as a regex, or a
    regex misread as division, swallows code up to the next `/` and leaves a
    bracket unbalanced somewhere in 4,800 lines.
    """
    src, j, groups = _js.APP, 0, 0
    while j < len(src):
        k = _js.skip(src, j)
        if k != j:
            j = k
            continue
        assert src[j] not in ")]}", f"stray {src[j]!r} at app.js line {_js._line(src, j)}"
        if src[j] in "([{":
            j = _js.close(src, j) + 1
            groups += 1
            continue
        j += 1
    assert groups > 300, f"only {groups} top-level groups; the scanner skipped most of app.js"


def test_every_top_level_function_slices_to_its_own_closing_brace() -> None:
    """app.js closes every multi-line top-level function with `}` at column 0,
    so a correct slice of one ends exactly there and contains no other."""
    names = re.findall(r"^(?:async )?function (\w+)\(", _js.APP, re.M)
    assert len(names) > 100
    for name in names:
        got = _js.function(name)
        if "\n" in got:
            assert got.endswith("\n}"), f"{name} does not end at a column-0 brace"
            assert "\n}\n" not in got, f"{name} ran past its own end"


def test_paint_origin_is_sliced_whole() -> None:
    """The real destructured-parameter function (`paintOrigin(o, { keepZoom =
    false, force = false } = {})`), sliced to its body and not its signature."""
    body = _js.function("paintOrigin")
    assert "keepZoom" in body and "originGen" in body and len(body) > 500
