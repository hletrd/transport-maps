"""`solvePoint()` runs under node, against a stubbed network.

The service it talks to does not exist yet and cannot be started here: it would
hold 3.4 GiB of graph on a box that is already swapping under a 39-hour build.
What CAN be tested, and is what actually matters, is the half that decides what
the page does with every answer the service can give -- including the answers
where there is no service at all.

The requirement these tests exist to hold is CLAUDE.md's, not a nicety: this
page has shipped a blank live site twice, and `fatal()` blanks it by design. A
network dependency that can reach `fatal()` is a way for a server outage to
delete a static map. So every path below ends in a result object, and one test
reads the source to prove no path can end in `fatal()` at all.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess

import pytest

from transport_maps import config

APP = (config.ROOT / "web" / "app.js").read_text(encoding="utf-8")


def _slice_function(name: str) -> str:
    """The verbatim source of `async function NAME(...) { ... }`.

    Brace matching that skips line comments, block comments and string or
    template literals -- all three appear inside this function, and a slicer
    that ignores them stops at the first brace in a comment.
    """
    start = APP.index(f"async function {name}(")
    i, depth, seen = start, 0, False
    while i < len(APP):
        c = APP[i]
        nxt = APP[i + 1] if i + 1 < len(APP) else ""
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
    raise AssertionError(f"async function {name} has no closing brace")


def _const_block() -> str:
    """The SOLVER_* constants, sliced from SOLVER_PATH to the flag."""
    start = APP.index("const SOLVER_PATH = ")
    end = APP.index("let solverEnabled = ")
    return APP[start:APP.index("\n", end) + 1]


SOLVE_SRC = _slice_function("solvePoint")
CONST_SRC = _const_block()


def test_the_slices_really_contain_what_they_claim():
    """A slicer that silently truncates gives a green test of nothing."""
    assert SOLVE_SRC.count("return") >= 6, SOLVE_SRC
    assert SOLVE_SRC.rstrip().endswith("}")
    assert "finally" in SOLVE_SRC and "clearTimeout" in SOLVE_SRC
    for code in ("bad_request", "out_of_range", "not_on_land", "busy",
                 "timeout", "unavailable"):
        assert code in CONST_SRC, f"{code} is missing from the sliced constants"


def test_no_failure_path_can_blank_the_page():
    """The one rule that is not negotiable. `fatal()` sets `body.fatal`, which
    `index.html` uses to hide the rail -- so a solver outage reaching it would
    delete the city list, the legend and the static map that is still correct.

    Mutation performed and reverted: replace one `return fail("unavailable")`
    with `fatal("...")` -> red.
    """
    code = re.sub(r"//[^\n]*", "", SOLVE_SRC)     # the prose may name it
    assert "fatal(" not in code, (
        "solvePoint can reach fatal(); a server outage would blank a working map")
    assert "fetchOk(" not in code and "loadJSON(" not in code, (
        "solvePoint uses a loader whose failure path calls fatal()")


def test_the_flag_is_off_by_default_and_the_address_cannot_arm_it():
    """A third URL parameter would let a pasted link turn on an experimental
    network dependency in someone else's browser, and spend their share of a
    rate limit doing it.

    Mutation performed and reverted: change the default to `true` -> red.
    Add `params.get("solver")` to the initialiser -> red.
    """
    assert 'store.get("solver", false)' in CONST_SRC, (
        "the solver flag is not read as a stored preference defaulting to off")
    assert "params.get" not in CONST_SRC and "searchParams" not in CONST_SRC, (
        "the solver flag can be set from the address")
    # ...and no other part of the file reads it from the URL either.
    assert 'params.get("solver")' not in APP and "params.has(\"solver\")" not in APP


@pytest.fixture(scope="module")
def node() -> str:
    exe = shutil.which("node")
    if exe is None:
        pytest.skip("node is not on PATH; solvePoint() cannot be run")
    return exe


def _run(node: str, tmp_path, scenario: dict) -> dict:
    """Run solvePoint once with a stubbed fetch, and return its result."""
    harness = f"""
const scenario = JSON.parse(process.argv[2]);
const store = {{ get: (k, d) => scenario.enabled, set: () => {{}} }};
{CONST_SRC}
solverEnabled = scenario.enabled;
let calls = 0;
let lastUrl = null;
globalThis.fetch = (url, opts) => {{
  calls += 1; lastUrl = url;
  // Honours the signal, the way a real fetch does: without this the harness
  // exits with an empty event loop and the test reads an empty stdout.
  if (scenario.kind === "hang" || scenario.kind === "cancel") {{
    return new Promise((_, rej) => opts.signal.addEventListener(
      "abort", () => rej(opts.signal.reason), {{ once: true }}));
  }}
  if (scenario.kind === "reject") return Promise.reject(new TypeError("Failed to fetch"));
  if (scenario.kind === "notjson") {{
    return Promise.resolve({{ ok: true, status: 200,
      json: () => Promise.reject(new SyntaxError("Unexpected token <")) }});
  }}
  return Promise.resolve({{
    ok: scenario.status < 400, status: scenario.status,
    json: () => Promise.resolve(scenario.body),
  }});
}};
{SOLVE_SRC}
(async () => {{
  const ctl = new AbortController();
  if (scenario.kind === "cancel") setTimeout(() => ctl.abort("cancelled"), 5);
  let threw = null, out = null;
  try {{
    out = await solvePoint({{lat: 5.9749, lon: 116.0724}}, {{lat: 35.6762, lon: 139.6503}},
                           scenario.kind === "cancel" ? ctl.signal : undefined);
  }} catch (e) {{ threw = String(e); }}
  console.log(JSON.stringify({{ out, threw, calls, lastUrl }}));
}})();
"""
    # A hanging or cancelled fetch must not wait the real 30 s deadline.
    if scenario.get("kind") in ("hang", "cancel"):
        harness = harness.replace("const SOLVER_TIMEOUT_MS = 30000;",
                                  "const SOLVER_TIMEOUT_MS = 40;")
    path = tmp_path / "harness.mjs"
    path.write_text(harness, encoding="utf-8")
    done = subprocess.run([node, str(path), json.dumps(scenario)],
                          capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


OK_BODY = {"v": 1, "status": "ok", "reachable": True, "minutes": 618,
           "snappedKm": 4.2, "snappedLat": 5.98, "snappedLon": 116.11}


def test_with_the_flag_off_nothing_reaches_the_network(node, tmp_path):
    """The default state of every visitor's browser. Not one request.

    Mutation performed and reverted: delete the `if (!solverEnabled)` guard ->
    red (calls becomes 1).
    """
    got = _run(node, tmp_path, {"enabled": False, "status": 200, "body": OK_BODY})
    assert got["calls"] == 0, "the flag is off and a request was made anyway"
    assert got["out"] == {"ok": False, "code": "unavailable",
                          "message": got["out"]["message"]}


def test_a_good_answer_is_returned_in_minutes(node, tmp_path):
    got = _run(node, tmp_path, {"enabled": True, "status": 200, "body": OK_BODY})
    assert got["out"]["ok"] is True
    assert got["out"]["minutes"] == 618 and got["out"]["reachable"] is True
    assert got["out"]["snappedKm"] == 4.2
    assert "from=5.97490,116.07240" in got["lastUrl"]
    assert "to=35.67620,139.65030" in got["lastUrl"]


def test_no_scheduled_route_is_an_answer_and_not_a_failure(node, tmp_path):
    """`reachable: false` means the graph was searched and nothing connects.
    That is a fact to print, not an error to retry.

    Mutation performed and reverted: treat `minutes === null` as a failure ->
    red.
    """
    body = dict(OK_BODY, reachable=False, minutes=None)
    got = _run(node, tmp_path, {"enabled": True, "status": 200, "body": body})
    assert got["out"]["ok"] is True and got["out"]["minutes"] is None
    assert got["out"]["reachable"] is False


@pytest.mark.parametrize("code,status", [
    ("not_on_land", 422), ("busy", 503), ("timeout", 504),
    ("unavailable", 503), ("bad_request", 400), ("out_of_range", 400),
])
def test_every_service_error_code_is_carried_through(node, tmp_path, code, status):
    """A code the page cannot name is a visitor staring at a silent failure.

    Mutation performed and reverted: delete `not_on_land` from SOLVER_CODES ->
    red for that row, and the result degrades to `unavailable`.
    """
    body = {"v": 1, "status": "error", "code": code, "message": "..."}
    got = _run(node, tmp_path, {"enabled": True, "status": status, "body": body})
    assert got["out"] == {"ok": False, "code": code, "message": got["out"]["message"]}
    assert got["out"]["message"], "the code has no sentence for a visitor"


def test_a_code_the_page_does_not_know_degrades_rather_than_crashing(node, tmp_path):
    """A newer service must not be able to make an older page throw on
    `SOLVER_CODES[body.code].toUpperCase()` or print `undefined`.

    Mutation performed and reverted: index SOLVER_CODES without Object.hasOwn
    -> red (message is null).
    """
    body = {"v": 1, "status": "error", "code": "teapot", "message": "..."}
    got = _run(node, tmp_path, {"enabled": True, "status": 418, "body": body})
    assert got["out"]["code"] == "unavailable" and got["out"]["message"]


def test_a_response_from_a_different_wire_version_is_refused(node, tmp_path):
    """A field that changed meaning prints a figure measuring something else,
    which is worse than printing nothing.

    Mutation performed and reverted: drop the version check -> red.
    """
    got = _run(node, tmp_path, {"enabled": True, "status": 200,
                                "body": dict(OK_BODY, v=2)})
    assert got["out"]["ok"] is False and got["out"]["code"] == "unavailable"


def test_a_reachable_answer_with_no_number_is_refused(node, tmp_path):
    """Otherwise the page formats `undefined` into the headline as NaN.

    Mutation performed and reverted: drop the `typeof body.minutes` check ->
    red.
    """
    got = _run(node, tmp_path, {"enabled": True, "status": 200,
                                "body": dict(OK_BODY, minutes="soon")})
    assert got["out"]["ok"] is False and got["out"]["code"] == "unavailable"


def test_a_captive_portal_answering_html_is_an_outage_not_a_crash(node, tmp_path):
    """The hotel wifi case: HTTP 200, and the body is a login page.

    Mutation performed and reverted: remove the try/catch -> red (threw).
    """
    got = _run(node, tmp_path, {"enabled": True, "kind": "notjson", "status": 200,
                                "body": None})
    assert got["threw"] is None and got["out"]["code"] == "unavailable"


def test_a_refused_connection_is_an_outage_not_an_unhandled_rejection(node, tmp_path):
    """A CSP refusal and a DNS failure both arrive as a rejected fetch. An
    unhandled one reaches boot.js's capturing listener, which paints "The page
    could not start" over a globe that is drawing perfectly -- the exact
    failure boot.js's own header records as shipped and seen live.
    """
    got = _run(node, tmp_path, {"enabled": True, "kind": "reject", "status": 0,
                                "body": None})
    assert got["threw"] is None and got["out"]["code"] == "unavailable"


def test_a_request_that_never_answers_ends_as_a_timeout(node, tmp_path):
    """`fetch` has no timeout of its own. Without this the page waits for the
    browser's own limit, which runs into minutes.

    Mutation performed and reverted: delete the setTimeout that aborts -> the
    harness times out and the test goes red.
    """
    got = _run(node, tmp_path, {"enabled": True, "kind": "hang", "status": 0,
                                "body": None})
    assert got["threw"] is None and got["out"]["code"] == "timeout"


def test_the_caller_can_cancel_and_gets_no_error_dialog(node, tmp_path):
    """A "Stop waiting" button, or a second drag starting before the first
    answered. Cancelling is not a failure to report to the visitor as one.

    Mutation performed and reverted: drop the `reason === "cancelled"` branch
    -> red (the result reads `timeout`, so a visitor who pressed Stop is told
    the service was slow).
    """
    got = _run(node, tmp_path, {"enabled": True, "kind": "cancel", "status": 0,
                                "body": None})
    assert got["threw"] is None and got["out"]["code"] == "unavailable"


def test_the_fallback_sentence_names_the_city_still_being_measured_from(node, tmp_path):
    """Every failure leaves a correct map on screen. Saying so is the
    difference between a failure and a dead end -- and the page must not
    invite a retry without saying what the numbers currently mean.
    """
    assert "SOLVER_FALLBACK" in CONST_SRC
    harness = tmp_path / "fallback.mjs"
    harness.write_text(CONST_SRC.replace("let solverEnabled = store.get(\"solver\", false);", "")
                       + '\nconsole.log(JSON.stringify([SOLVER_FALLBACK("Tokyo"), SOLVER_FALLBACK(null)]));\n',
                       encoding="utf-8")
    done = subprocess.run([node, str(harness)], capture_output=True, text=True, timeout=20)
    assert done.returncode == 0, done.stderr
    named, unnamed = json.loads(done.stdout)
    assert "Tokyo" in named and "still measured" in named
    assert "charted departure cities" in unnamed
