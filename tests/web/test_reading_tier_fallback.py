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
    with `get(...)` and an explicit `r.ok` test. Pinned so the two halves of
    the tier cannot drift apart again."""
    assert 'get(`./origins/${o.slug}${meta.readingUrlSuffix}`)' in APP
    assert ".then((r) => (r.ok ? r.arrayBuffer() : null))" in APP
