"""A missing reading-tier file must degrade, not blank the page.

`loadReadingParents` is documented "Not fatal: the res-4 array still answers
every reading", and it was not. It fetched through `loadCells`, which fetches
through `fetchOk`, and `fetchOk` calls the page's global `fatal()` on any
non-2xx response -- which adds `body.fatal` (index.html turns that into
`display:none` over the whole side rail), empties `#time`, writes "HTTP 404"
into `#where`, and only THEN throws. The throw landed in the "not fatal" catch
and was logged as a warning, while the legend, the readout and the city list
had already gone. Reproduced in a browser against a dist with the file removed.

It was dormant only because the shipped `index.json` carries no `readingRes`,
so `READING_RES` is null and `loadReading()` returns before ever calling this.
The next full build advertises `readingRes` and arms it, which is why this is
fixed now rather than after. "A blank globe with nothing useful in the console"
is the failure CLAUDE.md records this project as having shipped twice.

Two tests, because neither alone is enough: the first RUNS the new fetch helper
against a 404 and proves it merely rejects, and the second pins the call graph,
because a helper that behaves correctly is no use if the caller stops using it.
"""

from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from transport_maps import config

APP = (config.ROOT / "web" / "app.js").read_text(encoding="utf-8")


def _function(name: str) -> str:
    """The verbatim source of a top-level function, by brace matching.

    The same slice-and-run approach `test_route_geometry.py` and
    `test_boot_behaviour.py` take, and for the same reason: a substring check
    stays green when the body is gutted.
    """
    start = APP.index(f"function {name}(")
    if start > 0:
        # `async function foo(` -- keep the keyword.
        prefix = APP.rfind("async ", max(0, start - 6), start)
        if prefix != -1:
            start = prefix
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
        pytest.skip("node is not on PATH; the reading-tier fetch cannot be run")
    return exe


def _run(node: str, tmp_path, body: str) -> dict:
    script = tmp_path / "probe.mjs"
    script.write_text(body, encoding="utf-8")
    out = subprocess.run([node, str(script)], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_a_404_on_the_parent_file_rejects_and_touches_nothing_else(node, tmp_path):
    """The helper is run for real, with a `fatal` in scope that RECORDS being
    called rather than a comment promising it will not be.

    Mutation performed: point `loadReadingParents` back at `loadCells` -- the
    call-graph test below goes red. Mutation performed: make
    `fetchReadingCells` call `fatal(...)` on a bad response -- this test goes
    red on `fatalCalls`.
    """
    src = _function("fetchReadingCells")
    probe = f"""
let fatalCalls = 0;
function fatal(msg) {{ fatalCalls++; throw new Error(msg); }}
globalThis.fetch = async () => ({{ ok: false, status: 404,
  arrayBuffer: async () => new ArrayBuffer(0) }});
{src}
let rejected = null;
try {{ await fetchReadingCells("./reading_parents.bin"); }}
catch (e) {{ rejected = e.message; }}
console.log(JSON.stringify({{ fatalCalls, rejected }}));
"""
    got = _run(node, tmp_path, probe)
    assert got["rejected"] is not None, "a 404 must reject so the caller can fall back"
    assert got["fatalCalls"] == 0, (
        "the reading-tier fetch called fatal(), which blanks the whole side rail "
        "for a file the page is documented as working without")


def test_a_truncated_parent_file_also_rejects_rather_than_blanking(node, tmp_path):
    """The other refusal the tier needs. A body that is not a whole number of
    8-byte cells is from another build, and reading it would print plausible
    times for the wrong places."""
    src = _function("fetchReadingCells")
    probe = f"""
let fatalCalls = 0;
function fatal(msg) {{ fatalCalls++; throw new Error(msg); }}
globalThis.fetch = async () => ({{ ok: true, status: 200,
  arrayBuffer: async () => new ArrayBuffer(12) }});
{src}
let rejected = null;
try {{ await fetchReadingCells("./reading_parents.bin"); }}
catch (e) {{ rejected = e.message; }}
console.log(JSON.stringify({{ fatalCalls, rejected }}));
"""
    got = _run(node, tmp_path, probe)
    assert got["rejected"] is not None and "12 bytes" in got["rejected"]
    assert got["fatalCalls"] == 0


def test_the_parent_fetch_does_not_go_through_the_fatal_path():
    """The call graph, pinned. `loadCells` and `loadJSON` are for the two files
    the page genuinely cannot start without -- index.json and hover_cells.bin --
    and calling fatal() for those is correct. The reading tier is an optional
    extra and must not borrow that path.

    Mutation performed: restore `loadCells(url)` inside `loadReadingParents`
    -> red.
    """
    loader = _function("loadReadingParents")
    assert "fetchReadingCells(" in loader, (
        "loadReadingParents no longer uses its own fetch; if it went back to "
        "loadCells, a missing reading_parents.bin blanks the page again")
    assert "loadCells(" not in loader
    # ...and the helper itself must not reach fatal() by any route.
    helper = _function("fetchReadingCells")
    for sink in ("fatal(", "fetchOk(", "loadCells("):
        assert sink not in helper, f"fetchReadingCells reaches {sink}"


def test_the_per_origin_reading_array_was_always_fetched_this_way():
    """The correct shape already existed twenty lines away, which is what made
    the defect a slip rather than a design: the per-origin `.r6.bin` is fetched
    with `get(...)`, its response is tested, and a failure DEGRADES TO null
    instead of reaching fatal(). Pinned so the two halves of the tier cannot
    drift apart again.

    Stated as the property rather than as the literal source line. This
    assertion used to be `".then((r) => (r.ok ? r.arrayBuffer() : null))" in
    APP`, and cycle 15 turned that exact text into `okOr(r, ...)` -- a helper
    that logs the status and returns null, which is the same degrade with the
    silence removed. The old assertion went red for a change that satisfied
    everything the test exists to protect, which is the "assert on a string in
    app.js rather than on behaviour" habit this suite has been warned about.
    """
    # The directory comes from originBase(): the full set, or an exclusion
    # variant (which never fetches a reading tier at all).
    fetch_at = APP.index('get(`${originBase()}${o.slug}${meta.readingUrlSuffix}`)')
    # The response handler immediately following that fetch.
    handler = APP[fetch_at:fetch_at + 400]
    assert "? r.arrayBuffer() : null" in handler, (
        "the per-origin reading fetch no longer degrades a bad response to "
        f"null; a missing .r6.bin would blank the page again:\n{handler[:300]}")
    for sink in ("fatal(", "fetchOk("):
        assert sink not in handler, (
            f"the per-origin reading fetch reaches {sink}, so a missing "
            ".r6.bin is fatal to the page instead of falling back")


@pytest.mark.parametrize("name,body", [
    ("an HTML error page with a 200",
     'globalThis.fetch = async () => ({ ok: true, status: 200, '
     'arrayBuffer: async () => new TextEncoder().encode('
     '"<!doctype html><title>502</title>").buffer });'),
    ("an aborted request",
     'globalThis.fetch = async () => { const e = new Error("aborted"); '
     'e.name = "AbortError"; throw e; };'),
    ("a 500 with an empty body",
     'globalThis.fetch = async () => ({ ok: false, status: 500, '
     'arrayBuffer: async () => new ArrayBuffer(0) });'),
    ("a body whose length is not a whole number of ids",
     'globalThis.fetch = async () => ({ ok: true, status: 200, '
     'arrayBuffer: async () => new ArrayBuffer(13) });'),
])
def test_every_way_the_parent_file_can_fail_degrades_rather_than_blanks(
        node, tmp_path, name, body):
    """Only two of the five failure modes were pinned by a test that RAN
    anything; the rest rested on guards no test called.

    A 404 and a truncated file were covered. An HTML error body with a 200 (a
    proxy or an origin serving an error page), an aborted request, and a
    non-multiple length are the three that were not, and all three reach
    different branches. None of them may call `fatal()`, and each must reject
    so `loadReadingParents` can null `readingParentsWanted` and retry.

    Mutation performed and reverted: make `fetchReadingCells` call `fatal()`
    instead of throwing -> red on every case.
    """
    src = _function("fetchReadingCells")
    probe = f"""
let fatalCalls = 0;
function fatal(msg) {{ fatalCalls++; throw new Error("FATAL: " + msg); }}
{body}
{src}
let rejected = null, value = "none";
try {{ value = String(await fetchReadingCells("./reading_parents.bin")); }}
catch (e) {{ rejected = e.message; }}
console.log(JSON.stringify({{ fatalCalls, rejected, value }}));
"""
    got = _run(node, tmp_path, probe)
    assert got["fatalCalls"] == 0, (
        f"{name} made the reading-tier fetch call fatal(), which blanks the "
        "whole side rail for a file the page works without")
    assert not str(got["rejected"] or "").startswith("FATAL:"), got["rejected"]


def test_a_response_for_an_abandoned_origin_is_dropped_not_applied(node, tmp_path):
    """The generation check is what stops a slow reading array landing on top of
    a newer departure's. Deleting `current()` from the reading path left the
    whole suite green, so the guard was unpinned.

    Run here rather than grepped: the `.then` chain is given a `current()` that
    reports the origin has changed, and the probe records whether the array was
    written anyway.
    """
    # `loadReading` is an arrow inside paintOrigin, not a top-level function, so
    # it is sliced by brace matching from its own `const`. A skip here would be
    # a vacuous pass -- this repository has already had to fix one of those.
    import re as _re
    start = APP.index("const loadReading = () => {")
    i = APP.index("{", APP.index("=>", start))
    depth = 0
    for j in range(i, len(APP)):
        if APP[j] == "{":
            depth += 1
        elif APP[j] == "}":
            depth -= 1
            if depth == 0:
                break
    else:
        raise AssertionError("loadReading is not brace-balanced")
    body = _re.sub(r"//[^\n]*", "", APP[start:j + 1])
    assert "current()" in body, (
        "the reading path no longer checks the origin generation, so a slow "
        "response can land on top of a newer departure's array")

    # The check must be in the SAME callback as the write, not merely somewhere
    # earlier in the chain. A first draft of this assertion looked backwards for
    # any current() and was satisfied by the one in the outer .then, so deleting
    # the inner check left it green -- the very mutation it was written for. It
    # also carried `body.count("{", guard, i) >= 0`, which is true of every
    # input. Both were found by running the mutation.
    writes = [m.start() for m in _re.finditer(r"origin\.reading\s*=", body)]
    assert writes, "nothing in loadReading writes origin.reading; re-read this guard"
    for at in writes:
        stack = []
        for k, ch in enumerate(body[:at]):
            if ch == "{":
                stack.append(k)
            elif ch == "}" and stack:
                stack.pop()
        assert stack, "the write is not inside a block; re-read this guard"
        open_at = stack[-1]
        depth, close = 0, len(body)
        for k in range(open_at, len(body)):
            if body[k] == "{":
                depth += 1
            elif body[k] == "}":
                depth -= 1
                if depth == 0:
                    close = k
                    break
        block = body[open_at:close]
        assert "current()" in block, (
            "origin.reading is written in a callback that does not check the "
            "origin generation, so a slow response for an abandoned departure "
            f"lands on the new one's array:\n{block.strip()[:240]}")


def _arrow(name: str) -> str:
    """The body of a `const NAME = (...) => { ... }` binding, by brace matching.

    `loadReading` and `settle` are arrow consts, not declarations, so
    `_function` above cannot find them.
    """
    start = APP.index(f"const {name} = ")
    i = APP.index("{", APP.index("=>", start))
    depth = 0
    for j in range(i, len(APP)):
        if APP[j] == "{":
            depth += 1
        elif APP[j] == "}":
            depth -= 1
            if depth == 0:
                return APP[start:j + 1]
    raise AssertionError(f"const {name} is not brace-balanced")


# --- and when the tier ARRIVES, everything read through lookup() is redone ---

def test_the_arrival_of_the_finer_tier_redoes_every_reading_it_changes():
    """`loadReading`'s success branch is the second place the page re-reads
    everything, and it drifted from `settle()`.

    `renderLegs()` was missing from it. The headline moved to the finer array
    there while the itinerary kept the total it had already rendered, so
    `?from=seoul&to=-20.162,57.499` printed "19 h 48 min" over a "Door to door"
    line reading "19 h 57 min" -- measured against the shipped arrays, exactly
    the res-6 and res-4 values for that cell. The itinerary panel takes both
    of its numbers from `lookup()`, so it is self-consistent whenever it runs;
    this path simply never ran it again.

    Pinned as a set rather than one call, so the next render added to
    `settle()` cannot be forgotten here. Comments are stripped first: the
    standing rule is that an assertion over source text a comment can satisfy
    is vacuous, and this one is explained by a comment naming every call.

    Mutations performed and reverted, each confirmed RED:
      * delete `renderLegs();` from loadReading            -> 1 failed
      * delete `refreshScale();` from loadReading          -> 1 failed
      * `if (pinB || lastPointer)` -> `if (lastPointer)`   -> 1 failed
    """
    import re

    body = re.sub(r"//[^\n]*", "", _arrow("loadReading"))
    # Everything in settle() whose output is a function of lookup().
    for call in ("rereadPointer()", "renderLegs()", "renderDeparture()",
                 "refreshScale()", "render($(\"q\").value)"):
        assert call in body, (
            f"loadReading does not redo {call} when the finer array lands, so "
            "what it produced off the coarse grid stands beside a headline "
            "that has moved")
    # rereadPointer prefers the PIN over the pointer, so the guard in front of
    # it must not be narrower than that -- a pinned destination with no pointer
    # would keep a coarse headline for the rest of the session.
    assert re.search(r"if\s*\(\s*pinB\s*\|\|\s*lastPointer\s*\)\s*rereadPointer\(\)", body), (
        "the re-read is guarded on the pointer alone; rereadPointer answers "
        "for the pin first")


def test_the_two_re_read_paths_have_not_drifted_apart():
    """`settle()` and `loadReading` both re-read after new data lands. The
    only render `settle()` may have that `loadReading` does not is the city
    list rebuild's announcement, which is deliberately once-per-arrival.

    Mutation performed and reverted: delete `renderLegs()` from `settle()`
    -> red here and in test_state_writers.
    """
    import re

    settle = re.sub(r"//[^\n]*", "", _arrow("settle"))
    read = re.sub(r"//[^\n]*", "", _arrow("loadReading"))
    for call in ("renderLegs()", "renderDeparture()", "refreshScale()"):
        assert (call in settle) == (call in read), (
            f"{call} runs in one re-read path and not the other: "
            f"settle={call in settle}, loadReading={call in read}")


def test_a_variant_loads_its_own_reading_tier():
    """A variant ships the tier now (transport_maps.variants). Skipping it made
    the page read the ~20 km area's time, faster than the full map's at Tinian
    with ferries avoided. The fetch goes through originBase(), so it reads the
    variant's own file."""
    start = APP.index("const loadReading = () => {")
    body = APP[start:APP.index("\n  };", start)]
    assert "variantMeta()" not in body and "avoid" not in body, body[:400]
    assert "originBase()" in body
