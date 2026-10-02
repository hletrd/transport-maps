"""The page warns about an index.json written under a newer contract, and does
nothing else about it (J1b, the page half; docs/contract.md, "Versioning").

A newer `contractVersion` is not a reason to stop: every field the page reads
has a fallback, and the deploy gates are what refuse a dist/ that is really
inconsistent. A check that reached `fatal()` would turn a harmless version
bump into the blank page this site has shipped twice. So the guard is run
under node, and its source is read for the one call it must never make.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess

import pytest

from tests.web import _js
from transport_maps import config
from transport_maps.emit import index

APP = _js.APP
GUARD_START = "try {\n  const warning = contractWarning(meta.contractVersion);"
GUARD = APP[APP.index(GUARD_START):]
GUARD = GUARD[:GUARD.index("\n", GUARD.index("} catch")) + 1]
CONST = _js.statement("const PAGE_CONTRACT_VERSION = ")
FN = _js.function("contractWarning")


@pytest.fixture(scope="module")
def node() -> str:
    exe = shutil.which("node")
    if exe is None:
        pytest.skip("node is not on PATH; the guard cannot be run")
    return exe


def _run(node: str, tmp_path, body: str):
    script = tmp_path / "probe.mjs"
    script.write_text(body, encoding="utf-8")
    out = subprocess.run([node, str(script)], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_the_page_knows_the_version_the_pipeline_writes():
    """The writer moves first and the reader follows in the same commit
    (docs/contract.md, "Owners"). A bump in emit/index.py that leaves the page
    behind fails here, which is where the page's fallbacks get re-read.

    Mutation performed and reverted: `PAGE_CONTRACT_VERSION = 3` -> red.
    """
    m = re.fullmatch(r"const PAGE_CONTRACT_VERSION = (\d+);", CONST)
    assert m and int(m.group(1)) == index.CONTRACT_VERSION


@pytest.mark.parametrize("version,warns", [
    (None, False),          # absent: written before the field, version 1
    (1, False),
    (2, False),
    (3, True),
    (99, True),
    ("3", True),            # present but not a version this page can read
    ("2", True),            # ... even where `<=` would coerce it into one
    (1.5, True),
])
def test_only_a_newer_or_unreadable_version_is_warned_about(node, tmp_path, version, warns):
    """Mutations performed and reverted, each RED: `v <= PAGE_CONTRACT_VERSION`
    -> `v < ...` (the version-2 row warns); drop `?? 1` (the absent row
    warns); drop `Number.isInteger(v) &&` (the "2" and 1.5 rows stay silent).
    """
    meta = {} if version is None else {"contractVersion": version}
    got = _run(node, tmp_path, f"""
const meta = {json.dumps(meta)};
{CONST}
{FN}
console.log(JSON.stringify(contractWarning(meta.contractVersion)));
""")
    if not warns:
        assert got is None
    else:
        assert json.dumps(version) in got and str(index.CONTRACT_VERSION) in got


@pytest.mark.parametrize("console_throws", [False, True])
def test_the_guard_warns_and_carries_on(node, tmp_path, console_throws):
    """The guard as the page runs it: one console.warn for a newer version,
    and the next statement still runs -- even if the console itself throws.

    Mutations performed and reverted, each RED: `console.warn(warning)` ->
    `fatal(warning)`; the `try`/`catch` removed (the throwing-console row).
    """
    warn = ("() => { throw new Error('console gone'); }" if console_throws
            else "(m) => warned.push(m)")
    got = _run(node, tmp_path, f"""
const meta = {{ contractVersion: 3 }};
const warned = [];
let fatalled = null;
const fatal = (m) => {{ fatalled = m; throw new Error(m); }};
globalThis.console.warn = {warn};
{CONST}
{FN}
{GUARD}
const after = "the page went on";
process.stdout.write(JSON.stringify({{ warned, fatalled, after }}) + "\\n");
""")
    assert got["fatalled"] is None and got["after"] == "the page went on"
    assert len(got["warned"]) == (0 if console_throws else 1)


def test_the_guard_sits_after_the_index_check_and_never_calls_fatal():
    """Read the source with the comments stripped, so prose that names
    fatal() cannot satisfy or trip it.

    Mutation performed and reverted: move the guard above `const meta =
    await loadJSON` -> red (it would read `meta` in its dead zone, and the
    ReferenceError is the blank page again).
    """
    code = re.sub(r"/\*.*?\*/|//[^\n]*", "", GUARD + FN, flags=re.S)
    assert "fatal(" not in code and "throw" not in code
    assert "console.warn(" in code
    load = APP.index("const meta = await loadJSON(")
    check = APP.index('fatal("index.json lists no departure cities or band edges.");')
    assert load < check < APP.index(GUARD_START) < APP.index("const UNREACHABLE = ")
    doc = (config.ROOT / "docs" / "contract.md").read_text(encoding="utf-8")
    assert "The page does not read `contractVersion` yet." not in doc
