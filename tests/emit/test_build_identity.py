"""inputsHash must move when any input that shapes the artifacts moves.

`build_identity()` exists so two builds can be told apart. Its docstring lists
what it covers, and nothing checked the list: dropping `SOLVE_RES`, `FINE_RES`
and `BAND_EDGES_MIN` from the `params_hash` call left the whole suite green,
and a res-5 build and a res-6 build then shared a `buildId` -- exactly the
mixture `scripts/check_dist.py` says "passes every length check".

Each term is tested by MOVING it and asserting the hash moves, which is the
only form of this test that cannot pass with the term removed.

What the table guard could not see until cycle 16: it built

    called = {n for n in STAMPED if f"config.{n}" in body}

which is a SUBSET OF `STAMPED` BY CONSTRUCTION, so `called == set(STAMPED)`
asserted precisely what the `for name in STAMPED` loop beside it already
asserted. The direction the guard exists for -- a `config.X` added to
`params_hash` with no row here, and therefore never mutation-tested -- could
not fail it, and its failure message printed the symmetric difference under the
label of the half it could never contain. The names are now read out of the
`params_hash` call's own AST and compared BOTH ways.

Mutations performed and reverted, with measured results:

- delete the `UNREACHABLE` row from STAMPED (a hashed constant with no row,
  the exact shape the guard exists for). Old guard: 11 passed, 0 failed --
  green, because `called` shrank with the table. New guard: 1 failed,
  10 passed, "params_hash hashes config constants with no row in STAMPED:
  ['UNREACHABLE']".
- add a bare `config.DIST` argument to the `params_hash` call. The real
  emit/index.py could NOT be edited (a 38-hour `build-all` had it imported),
  so the mutation was applied to a copy on disk and both extractions were run
  against it. Old extraction: `called` == the full table, symmetric difference
  `[]` -- green, it cannot see a name the table does not already hold. New
  extraction: `hashed` gains `'DIST'`, unrowed == `['DIST']`, assertion fails.
- delete `config.HOVER_RES` from that copy's `params_hash` call. New guard:
  unhashed == `['HOVER_RES']`, fails as "STAMPED rows that params_hash does not
  hash" -- the other direction, labelled the right way round this time.
- control: the unmutated copy gives unrowed == `[]` and unhashed == `[]`.
"""

import ast
import inspect
import textwrap

import pytest

from transport_maps import config
from transport_maps.emit import index, modes

#: Every constant `build_identity`'s docstring claims to cover, with a value
#: that differs from the real one. A term missing from the hash fails here.
STAMPED = {
    "SOLVE_RES": (config, 5),
    "FINE_RES": (config, 8),
    "HOVER_RES": (config, 3),
    "BAND_EDGES_MIN": (config, (30, 60, 120)),
    "UNREACHABLE": (config, 65534),
    "READING_RES": (config, 5),
    "READING_PARENT_RES": (config, 2),
    "READING_SLOTS": (config, 49),
}


def test_the_stamp_exists_at_all():
    ident = index.build_identity()
    assert ident["inputsHash"] and ident["buildId"].startswith(ident["inputsHash"])
    assert ident["builtAt"]


@pytest.mark.parametrize("name", sorted(STAMPED))
def test_moving_a_governing_constant_moves_the_stamp(name, monkeypatch):
    before = index.build_identity()["inputsHash"]
    module, other = STAMPED[name]
    assert getattr(module, name) != other, f"{name}'s test value equals its real one"
    monkeypatch.setattr(module, name, other)
    after = index.build_identity()["inputsHash"]
    assert after != before, (
        f"inputsHash does not cover {name}: two builds differing only in it would "
        "share a buildId, and the field that exists to tell artifacts apart could "
        "not tell those two apart")


def test_the_mode_channel_order_is_stamped(monkeypatch):
    """.modes.bin's channel order is a wire format. Two builds with different
    channel orders produce arrays of identical length."""
    before = index.build_identity()["inputsHash"]
    monkeypatch.setattr(modes, "CHANNELS", tuple(reversed(modes.CHANNELS)))
    assert index.build_identity()["inputsHash"] != before


def test_two_runs_of_one_input_set_stay_distinguishable():
    """buildId adds the start time, so an aborted run and its retry differ."""
    from datetime import UTC, datetime
    a = index.build_identity(datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC))
    b = index.build_identity(datetime(2026, 1, 1, 0, 0, 1, tzinfo=UTC))
    assert a["inputsHash"] == b["inputsHash"]
    assert a["buildId"] != b["buildId"]


def _config_names_hashed_by(fn) -> set[str]:
    """Every `config.X` whose VALUE is an argument of `fn`'s params_hash call.

    Read off the AST, not out of the text: a name in a comment or a docstring
    cannot satisfy it, and -- the point of cycle 16 -- the set is derived from
    the CODE, so it can contain a name STAMPED does not, which is the only way
    round the guard can catch a term added to the hash without a row.

    Recursion stops at a nested `Call`, because what a call contributes to the
    digest is its RESULT. `_sha256(config.ROOT / "calibration.toml")` hashes the
    file's contents; `config.ROOT` is the locator that found the file, not a
    value in the digest, and moving it does not mean "the grid resolution
    changed" -- so ROOT and DATA are deliberately not rows in STAMPED and
    deliberately not collected here.
    """
    tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call)
             and getattr(n.func, "attr", getattr(n.func, "id", "")) == "params_hash"]
    assert len(calls) == 1, (
        f"{fn.__name__} makes {len(calls)} params_hash calls; this guard reads one. "
        "A second call would hide every term in it from the table check")

    names: set[str] = set()

    def visit(node) -> None:
        if isinstance(node, ast.Call):
            return
        if (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
                and node.value.id == "config"):
            names.add(node.attr)
            return
        for child in ast.iter_child_nodes(node):
            visit(child)

    for arg in calls[0].args:
        visit(arg)
    return names


def test_the_table_and_the_hash_cover_exactly_the_same_config_constants():
    """Both directions. The half that matters is the first one.

    A row with no term in the hash was already caught (its parametrised case
    goes red). A term in the hash with no row was NOT: it is simply never
    mutation-tested, and this file exists because three such terms shipped.
    """
    hashed = _config_names_hashed_by(index.build_identity)
    unrowed = sorted(hashed - set(STAMPED))
    unhashed = sorted(set(STAMPED) - hashed)
    assert not unrowed, (
        f"params_hash hashes config constants with no row in STAMPED: {unrowed}. "
        "Nothing mutation-tests them, so dropping one from the hash again would "
        "leave the suite green -- add a row with a value that differs from the "
        "real one")
    assert not unhashed, (
        f"STAMPED rows that params_hash does not hash: {unhashed}. Either the "
        "term was dropped from build_identity (two builds differing only in it "
        "now share a buildId) or the row is stale")


def test_the_code_is_stamped_by_content_not_by_commit(monkeypatch):
    """A resumed build (`build-all --skip-existing`) trusts an origin only under
    the inputsHash it was built with. Keyed on the git head, any commit -- a
    plan tick -- broke that, so a build that died on day two of three could
    never resume in a checkout that takes commits daily. The head is still
    recorded, as `gitHead`, and the code still moves the hash.

    Mutations performed and reverted, each red: `_git_head()` back in the
    params_hash call (the first assertion); `_code_hash()` dropped from it (the
    last).
    """
    monkeypatch.setattr(index, "_git_head", lambda: "aaaaaaa")
    a = index.build_identity()
    monkeypatch.setattr(index, "_git_head", lambda: "bbbbbbb-dirty")
    b = index.build_identity()
    assert a["inputsHash"] == b["inputsHash"], "a commit that changes no code moved inputsHash"
    assert (a["gitHead"], b["gitHead"]) == ("aaaaaaa", "bbbbbbb-dirty")
    monkeypatch.setattr(index, "_code_hash", lambda: "edited")
    assert index.build_identity()["inputsHash"] != a["inputsHash"], "a code edit did not move it"


def test_the_code_hash_reads_every_package_file_and_nothing_else(monkeypatch, tmp_path):
    """Every file of the package (nested ones too), pyproject.toml and uv.lock;
    not bytecode, editor dotfiles or anything outside them.

    Mutations performed and reverted, each red: `glob` for `rglob` (the nested
    edit is missed); uv.lock dropped from CODE_PATHS; the `__pycache__` filter
    removed (the bytecode moves it).
    """
    pkg = tmp_path / "src" / "transport_maps"
    (pkg / "graph").mkdir(parents=True)
    (pkg / "cli.py").write_text("x = 1\n")
    (pkg / "graph" / "build.py").write_text("y = 2\n")
    (tmp_path / "pyproject.toml").write_text("[project]\n")
    (tmp_path / "uv.lock").write_text("v1\n")
    monkeypatch.setattr(index.config, "ROOT", tmp_path)
    base = index._code_hash()

    (pkg / "__pycache__").mkdir()
    (pkg / "__pycache__" / "cli.cpython-314.pyc").write_bytes(b"\0")
    (pkg / ".cli.py.swp").write_bytes(b"\0")
    (tmp_path / "plan.md").write_text("tick\n")
    assert index._code_hash() == base, "bytecode, a swap file or a plan note moved the code hash"

    for f, edit in ((pkg / "graph" / "build.py", "y = 3\n"), (tmp_path / "uv.lock", "v2\n"),
                    (tmp_path / "pyproject.toml", "[project]\nname = 'x'\n")):
        old = f.read_text()
        f.write_text(edit)
        assert index._code_hash() != base, f"an edit to {f.name} did not move the code hash"
        f.write_text(old)
    assert index._code_hash() == base
    (pkg / "new.py").write_text("")
    assert index._code_hash() != base, "a new module, tracked or not, is code"
