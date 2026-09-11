"""The page's own JavaScript must at least parse.

Nothing in this repository parsed `web/app.js`. A syntax error in it passed the
deploy's entire page gate (102 tests green), passed `check_dist --copy-only`
(exit 0), and `deploy_verify.sh` rsynced it to the live site BEFORE
`browser_verify.sh` ever opened a browser. CLAUDE.md's deploy rule records that
this site has gone out blank twice; a broken `app.js` is the shortest path to a
third.

The obvious guard is itself vacuous, which is why this file explains itself.
Measured on Node v24 with the real app.js and a deliberate `{ {` inserted:

    node --check bad.mjs   -> exit 1, "SyntaxError: Unexpected end of input"
    node --check bad.js    -> exit 0

A bare `.js` with no `package.json` type is ambiguous, and Node resolves the
ambiguity by accepting it. So the file is copied to an explicit extension --
`.mjs` for the module, `.cjs` for the classic script -- which is what forces
Node to commit to a parse goal and actually fail.

This is a syntax check and nothing more. It cannot see a temporal-dead-zone
error, which is valid syntax and is the failure CLAUDE.md records as having
blanked this site twice; `browser_verify.sh` is what catches those. It is the
cheap half, placed before the expensive half.
"""

import shutil
import subprocess

import pytest

from transport_maps import config

WEB = config.ROOT / "web"

#: The page's own scripts and the extension that forces Node's parse goal.
#: app.js is an ES module (it has top-level `import`); boot.js is a classic
#: script loaded with a plain <script src>, deliberately, so the CSP needs no
#: hash. The vendored bundles are not here: they are pinned by sha256 in
#: `test_vendor.py` and are not ours to parse-check.
SCRIPTS = {"app.js": ".mjs", "boot.js": ".cjs"}


@pytest.fixture(scope="module")
def node() -> str:
    exe = shutil.which("node")
    if exe is None:
        pytest.skip("node is not on PATH; the page's scripts cannot be parsed")
    return exe


@pytest.mark.parametrize("name", sorted(SCRIPTS))
def test_the_page_script_parses(node: str, name: str, tmp_path_factory) -> None:
    """Mutation performed and reverted: insert `{ {` into app.js -> red here,
    and green under `node --check app.js`, which is the whole point."""
    src = WEB / name
    assert src.is_file(), f"web/{name} is missing; the page cannot start"
    copy = tmp_path_factory.mktemp("parse") / (src.stem + SCRIPTS[name])
    copy.write_bytes(src.read_bytes())
    done = subprocess.run([node, "--check", str(copy)], capture_output=True, text=True)
    assert done.returncode == 0, f"web/{name} does not parse:\n{done.stderr}"


def test_the_ambiguous_check_would_not_have_caught_it(node: str, tmp_path_factory) -> None:
    """The evidence for the extension, not a restatement of it.

    If a future edit "simplifies" the test above to `node --check app.js`, this
    is the measurement that says why it must not: Node accepts a broken module
    under a bare `.js`. Should Node ever start rejecting it, this test fails and
    the simplification becomes safe -- which is the right way round.
    """
    broken = (WEB / "app.js").read_text(encoding="utf-8") + "\nfunction ( { {\n"
    d = tmp_path_factory.mktemp("ambiguous")
    (d / "app.js").write_text(broken, encoding="utf-8")
    (d / "app.mjs").write_text(broken, encoding="utf-8")
    bare = subprocess.run([node, "--check", str(d / "app.js")], capture_output=True)
    explicit = subprocess.run([node, "--check", str(d / "app.mjs")], capture_output=True)
    assert explicit.returncode != 0, "the .mjs check no longer catches a broken module"
    assert bare.returncode == 0, (
        "node now rejects a broken module under a bare .js; the extension "
        "copy in test_the_page_script_parses can be simplified away")
