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
