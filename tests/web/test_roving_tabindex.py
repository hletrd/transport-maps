"""The departure list must always keep exactly one tab stop.

`#results` is a roving-tabindex listbox: the arrow keys move focus, and exactly
one row carries `tabIndex = 0` so that Tab from elsewhere on the page lands
back on the list where the visitor left it.

The handler cleared every row's tab stop before deciding which one to restore,
and on ArrowUp from the FIRST row it restored none: focus went to `#q` and the
list was left with zero stops. One keystroke, and Tab from the search box
skipped all 60 rows and landed on "Search address" -- the 1,464 departure
cities became unreachable by Tab until something re-rendered the list.

Run against a DOM built here rather than asserted as a substring: the defect
is the end state after a sequence of keystrokes, which no amount of reading the
source shows.

Mutation performed and reverted: restore the old
`if (next !== $("q")) next.tabIndex = 0;` -> red on the ArrowUp case, green on
every other.
"""

from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from tests.web import _js
from transport_maps import config

APP = (config.ROOT / "web" / "app.js").read_text(encoding="utf-8")


def _handler() -> str:
    """The keydown listener, cut at its own boundaries."""
    start = APP.index('$("results").addEventListener("keydown"')
    end = APP.index("\n});", start) + len("\n});")
    return APP[start:end]


@pytest.fixture(scope="module")
def press(tmp_path_factory):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not on PATH; the handler cannot be run")

    # A DOM small enough to reason about and real enough to run the handler:
    # a listener registry, a focus pointer, and buttons with a tabIndex.
    src = """
const rows = [];
const q = { id: "q", tabIndex: 0, focus() { active = q; } };
let active = null;
const listeners = {};
const results = {
  addEventListener: (kind, fn) => (listeners[kind] = fn),
  querySelectorAll: () => rows,
};
const $ = (id) => (id === "results" ? results : q);
const document = { get activeElement() { return active; } };
function makeRows(n) {
  rows.length = 0;
  for (let i = 0; i < n; i++) {
    rows.push({ i, tabIndex: -1, focus() { active = this; } });
  }
  rows[0].tabIndex = 0;
}
HANDLER
const plan = JSON.parse(process.argv[2]);
makeRows(plan.rows);
active = rows[plan.start];
for (const key of plan.keys) {
  listeners.keydown({ key, preventDefault() {} });
}
process.stdout.write(JSON.stringify({
  stops: rows.filter((r) => r.tabIndex === 0).map((r) => r.i),
  qStop: q.tabIndex,
  focused: active === q ? "q" : active.i,
}));
""".replace("HANDLER", _handler())
    path = tmp_path_factory.mktemp("rt") / "rt.cjs"
    path.write_text(src, encoding="utf-8")

    def call(keys, rows=60, start=0):
        done = subprocess.run(
            [node, str(path), json.dumps({"keys": keys, "rows": rows, "start": start})],
            capture_output=True, text=True)
        assert done.returncode == 0, done.stderr
        return json.loads(done.stdout)
    return call


def test_arrowup_from_the_first_row_leaves_the_list_reachable_by_tab(press):
    """The defect. Focus correctly returns to the search box; the tab stop
    must not vanish with it."""
    got = press(["ArrowUp"])
    assert got["focused"] == "q", got
    assert got["stops"] == [0], (
        f"ArrowUp out of the list left {len(got['stops'])} tab stops in it, so "
        "Tab from the search box skips every departure city")


def test_moving_through_the_list_never_leaves_two_stops(press):
    """The other half of the contract, and the one C17-6's fix could have
    broken: restoring a stop on the way out must not leave the old one."""
    for keys in (
        ["ArrowDown"],
        ["ArrowDown", "ArrowDown", "ArrowDown"],
        ["ArrowDown", "ArrowDown", "ArrowUp"],
        ["ArrowDown", "ArrowUp", "ArrowUp"],
        ["ArrowUp", "ArrowDown"],
        ["ArrowDown"] * 8 + ["ArrowUp"] * 8,
    ):
        got = press(keys)
        assert len(got["stops"]) == 1, f"{keys} left stops {got['stops']}"


def test_the_stop_is_on_the_row_that_has_focus(press):
    """A stop on a different row than the focused one sends Tab somewhere the
    visitor was not."""
    for keys in (["ArrowDown"], ["ArrowDown", "ArrowDown"], ["ArrowDown", "ArrowUp"]):
        got = press(keys)
        assert got["stops"] == [got["focused"]], (
            f"{keys}: focus is on {got['focused']} and the tab stop on {got['stops']}")


def test_arrowdown_stops_at_the_last_row(press):
    """Not part of the defect; asserted because the fix indexes `items[i]` and
    an off-by-one at the end of the list would be silent."""
    got = press(["ArrowDown"] * 20, rows=5)
    assert got["focused"] == 4, got
    assert got["stops"] == [4], got


# --- DEF17-21 / DEF17-22: the stop render() leaves behind ---------------------
#
# render() rebuilds #results once per origin, up to a second after a city is
# clicked, and gives keyboard focus back to the row that had it. The inline
# version set tabIndex 0 on the current departure AND on the refocused row --
# two stops in a one-stop list (DEF17-21) -- and refocused only city rows, so
# a rebuild under an airport or address row dropped focus to <body> (DEF17-22).
# rovingStop() is that step, run here against a DOM built for it.

@pytest.fixture(scope="module")
def rebuild(tmp_path_factory):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not on PATH; rovingStop cannot be run")
    src = """
let active = null;
const document = { get activeElement() { return active; } };
function button(id, attrs, data) {
  return { id, attrs, dataset: data, tabIndex: -1, focus() { active = this; } };
}
// The selectors rovingStop uses, and nothing else: an attribute list, each
// either present or equal to a quoted value.
function matches(b, sel) {
  for (const [, name, val] of sel.matchAll(/\\[([\\w-]+)(?:="([^"]*)")?\\]/g)) {
    const have = name.startsWith("data-") ? b.dataset[name.slice(5)] : b.attrs[name];
    if (have === undefined || (val !== undefined && have !== val)) return false;
  }
  return true;
}
SRC
const plan = JSON.parse(process.argv[2]);
const rows = plan.rows.map(([id, attrs, data, tab]) => {
  const b = button(id, attrs, data);
  if (tab !== undefined) b.tabIndex = tab;
  return b;
});
const box = {
  querySelector: (sel) => rows.find((b) => matches(b, sel)) ?? null,
  querySelectorAll: () => rows,
  contains: (el) => rows.includes(el),
};
// The row focus was on BEFORE the rebuild: the same node for an address row
// (carried across), a different node with the same data for a city or airport.
const before = plan.focused === null ? null
  : plan.carried ? rows.find((b) => b.id === plan.focused)
  : { dataset: plan.focusedData };
active = before;
rovingStop(box, { slug: before?.dataset?.slug, airport: before?.dataset?.airport, el: before });
process.stdout.write(JSON.stringify({
  stops: rows.filter((b) => b.tabIndex === 0).map((b) => b.id),
  focused: rows.includes(active) ? active.id : null,
}));
""".replace("SRC", _js.function("cssEscape") + "\n" + _js.function("rovingStop"))
    path = tmp_path_factory.mktemp("rs") / "rs.cjs"
    path.write_text(src, encoding="utf-8")

    def call(*, focused=None, focused_data=None, carried=False, address_tab=-1):
        rows = [
            ["addr", {}, {"geo": "1,2"}, address_tab],
            ["aba", {"aria-current": "false"}, {"slug": "aba"}],
            ["seoul", {"aria-current": "true"}, {"slug": "seoul"}],
            ["tokyo", {"aria-current": "false"}, {"slug": "tokyo"}],
            ["hnd", {}, {"airport": "HND"}],
        ]
        plan = {"rows": rows, "focused": focused, "focusedData": focused_data,
                "carried": carried}
        done = subprocess.run([node, str(path), json.dumps(plan)],
                              capture_output=True, text=True)
        assert done.returncode == 0, done.stderr
        return json.loads(done.stdout)
    return call


def test_a_rebuild_under_a_city_row_leaves_one_stop_on_that_row(rebuild):
    """DEF17-21. Focus on Tokyo while departing from Seoul: Tokyo keeps focus
    and the stop, and Seoul -- the default stop -- does not keep one as well.

    Mutation performed and reverted: restore the inline version's shape
    (`stop` = the current departure, then `again.tabIndex = 0` on top, no
    reset) -> red, stops ["seoul", "tokyo"].
    """
    got = rebuild(focused="tokyo", focused_data={"slug": "tokyo"})
    assert got == {"stops": ["tokyo"], "focused": "tokyo"}, got


def test_a_rebuild_under_an_airport_row_keeps_focus(rebuild):
    """DEF17-22. Was: focus dropped to <body>, only data-slug rows restored.

    Mutation performed and reverted: drop the `had.airport` branch -> red,
    focused null and the stop back on Seoul.
    """
    got = rebuild(focused="hnd", focused_data={"airport": "HND"})
    assert got == {"stops": ["hnd"], "focused": "hnd"}, got


def test_a_carried_address_row_keeps_focus_and_sheds_its_old_stop(rebuild):
    """An address row is the same node before and after; focus returns to it.
    Unfocused, the tabIndex 0 that arrow-key roving left on it must not
    survive beside the departure's.

    Mutation performed and reverted: delete the reset loop in rovingStop ->
    red on the second case, stops ["addr", "seoul"].
    """
    got = rebuild(focused="addr", carried=True)
    assert got == {"stops": ["addr"], "focused": "addr"}, got
    got = rebuild(address_tab=0)
    assert got == {"stops": ["seoul"], "focused": None}, got


def test_with_nothing_focused_the_stop_is_the_departure(rebuild):
    """Not row 1: see test_page_affordances' note on "Aba" and scrollTop."""
    assert rebuild() == {"stops": ["seoul"], "focused": None}


def test_render_uses_rovingstop_and_sets_no_stop_of_its_own() -> None:
    """The tests above run rovingStop; this pins that render() is what calls
    it, and that no second `tabIndex = 0` has crept back in beside it."""
    body = _js.function("render")
    assert "rovingStop(box, had)" in body
    assert "tabIndex = 0" not in body, "render() sets a tab stop outside rovingStop"
