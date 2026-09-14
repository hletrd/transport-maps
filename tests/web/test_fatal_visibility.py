"""`fatal()` must leave its message somewhere a visitor can read it.

`index.html` carries `body.fatal .rail{display:none}`, and its own comment says
why: on a phone the bottom sheet would otherwise cover the message. Cycle 12
moved `layoutForSize()` ABOVE the globe-load race -- correctly, for a different
reason its own comment records -- and layoutForSize puts `.reading` INSIDE
`.rail` below 860 px.

From that line onwards the rule hid the sentence it exists to reveal. At
820x1180, 390x844 and 844x390 -- three of the four viewports CLAUDE.md's deploy
rule names -- the 20-second globe timeout produced a masthead, a black canvas
and no explanation. That is the blank-page failure this repository has shipped
twice, reintroduced by a reorder, and nothing in 869 tests could see it.

`fatal()` is run here under a stub DOM rather than asserted about in source:
the defect was an interaction between a CSS rule and a DOM move, and only
running it proves where the message lands.
"""

from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from transport_maps import config

APP = (config.ROOT / "web" / "app.js").read_text(encoding="utf-8")


def _slice_function(name: str) -> str:
    """The verbatim source of `function NAME(...) { ... }`, brace matched past
    comments and string literals -- `fatal()` is now mostly comment."""
    start = APP.index(f"function {name}(")
    i, depth, seen = start, 0, False
    while i < len(APP):
        c, nxt = APP[i], APP[i + 1] if i + 1 < len(APP) else ""
        if c == "/" and nxt == "/":
            i = APP.index("\n", i)
            continue
        if c == "/" and nxt == "*":
            i = APP.index("*/", i) + 2
            continue
        if c in "\"'`":
            j = i + 1
            while j < len(APP) and APP[j] != c:
                j += 2 if APP[j] == "\\" else 1
            i = j + 1
            continue
        if c == "{":
            depth += 1
            seen = True
        elif c == "}":
            depth -= 1
            if seen and depth == 0:
                return APP[start:i + 1]
        i += 1
    raise AssertionError(f"function {name} has no closing brace")


FATAL_SRC = _slice_function("fatal")


def test_the_slice_really_contains_the_whole_function():
    assert 'classList.add("fatal")' in FATAL_SRC
    assert "throw new Error" in FATAL_SRC
    assert FATAL_SRC.rstrip().endswith("}")


@pytest.fixture(scope="module")
def node() -> str:
    exe = shutil.which("node")
    if exe is None:
        pytest.skip("node is not on PATH; fatal() cannot be run")
    return exe


def _run(node: str, tmp_path, small_layout: bool) -> dict:
    harness = f"""
const classes = new Set();
const elements = {{}};
const el = (id) => (elements[id] ||= {{ id, textContent: "" }});
const rail = {{ className: "rail" }};
const readout = {{ className: "reading", parentElement: null }};
const document = {{
  body: {{
    classList: {{ add: (c) => classes.add(c), contains: (c) => classes.has(c) }},
    insertBefore: (node) => {{ node.parentElement = document.body; return node; }},
  }},
  querySelector: (sel) => (sel === ".reading" ? readout : null),
  getElementById: el,
}};
readout.parentElement = {str(small_layout).lower()} ? rail : document.body;
const $ = el;
{FATAL_SRC}
let threw = null;
try {{ fatal("the globe did not finish loading within 20 seconds."); }}
catch (e) {{ threw = String(e.message); }}
console.log(JSON.stringify({{
  fatalClass: classes.has("fatal"),
  where: elements.where ? elements.where.textContent : "",
  time: elements.time ? elements.time.textContent : null,
  readoutInBody: readout.parentElement === document.body,
  threw,
}}));
"""
    path = tmp_path / "fatal.mjs"
    path.write_text(harness, encoding="utf-8")
    done = subprocess.run([node, str(path)], capture_output=True, text=True, timeout=20)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_on_a_small_layout_the_message_is_moved_out_of_the_hidden_rail(node, tmp_path):
    """The defect, directly. Below 860 px the readout is inside `.rail`, which
    `body.fatal` hides -- so the message has to be moved before it is written.

    Mutation performed and reverted: delete the re-parenting block from
    `fatal()` -> red (readoutInBody false; a visitor at 390x844 sees a black
    canvas and no explanation).
    """
    seen = _run(node, tmp_path, small_layout=True)
    assert seen["fatalClass"] and seen["where"], seen
    assert seen["readoutInBody"], (
        "fatal() wrote its message inside .rail, which body.fatal hides")


def test_on_a_desktop_layout_nothing_is_moved(node, tmp_path):
    """Above 860 px the readout is already a child of <body>. Moving it anyway
    is a pointless DOM write in a failure path, and it would reorder the
    document for no reason.

    Mutation performed and reverted: drop the `parentElement !== document.body`
    guard -> green here, which is why the guard is also asserted in source.
    """
    seen = _run(node, tmp_path, small_layout=False)
    assert seen["readoutInBody"] and seen["where"]
    assert "parentElement !== document.body" in FATAL_SRC, (
        "fatal() re-parents the readout unconditionally")


def test_it_still_clears_a_stale_figure_and_still_throws(node, tmp_path):
    """The two things fatal() did before must survive the fix: a stale
    duration must not sit above a failure message, and the throw is what stops
    the module.
    """
    seen = _run(node, tmp_path, small_layout=True)
    assert seen["time"] == "", "a stale reading was left above the failure message"
    assert seen["threw"], "fatal() no longer stops the module"


def test_the_rule_it_works_around_is_still_in_the_stylesheet():
    """If `body.fatal .rail{display:none}` is ever deleted, the re-parenting
    above is dead code that quietly reorders the DOM in a failure path, and
    this test says so rather than leaving it to rot.
    """
    html = (config.ROOT / "web" / "index.html").read_text(encoding="utf-8")
    assert "body.fatal .rail{display:none}" in html, (
        "the rule fatal() re-parents around is gone; the re-parenting can go too")
