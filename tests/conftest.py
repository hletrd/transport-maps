"""Shared fixtures for the whole suite.

Two things every test gets without asking:

* A hermetic cache. `config.CACHE` is redirected to one scratch directory per
  session, seeded with the two Natural Earth archives the fast tests read, so
  a test run never writes into the real data/cache/. Before this, every run
  left `rail_routes-*` / `cell_country-*` / `urban_mask-*` parquet files
  behind (358 of the first kind by cycle 2). Tests marked `integration` keep
  the real cache: they build the full node index from the cached universe.
* `scripts/check_ramps.py` importable as a fixture, instead of every test
  file mutating `sys.path` for the session.

And one thing a test must ASK for, `hermetic_build`, because it cannot be
given to everyone: see its docstring. In short, `config.BUILD` is deliberately
NOT redirected -- most of the suite reads the real built artifacts and would
have to rebuild them -- but any test whose subject WRITES a derived table into
`config.BUILD` reads its own warm output instead of running the code, and
passes no matter what the code says. `tests/sources/test_airports.py` was
exactly that: a four-way mutation of the filter left it at 4 passed.
"""

import importlib.util
import shutil

import pytest

from transport_maps import config

# What the fast tests read from the cache: country polygons (borders, zones)
# and populated places (the urban mask). Everything else they need lives in
# data/build (the stamped land cells, airports and road grid), which is not
# redirected.
SEED_ARCHIVES = ("ne_10m_admin_0_countries.zip", "ne_10m_populated_places_simple.zip")


@pytest.fixture(scope="session")
def scratch_cache(tmp_path_factory):
    real = config.CACHE
    scratch = tmp_path_factory.mktemp("cache")
    for name in SEED_ARCHIVES:
        src = real / name
        if src.exists():
            dst = scratch / name
            shutil.copyfile(src, dst)
            # Two of the real archives are 0600 from before _atomic_write
            # honoured the umask; the copy must be readable.
            dst.chmod(0o644)
    return scratch


@pytest.fixture(autouse=True)
def _hermetic_cache(request, monkeypatch, scratch_cache):
    if request.node.get_closest_marker("integration"):
        return
    monkeypatch.setattr(config, "CACHE", scratch_cache)


@pytest.fixture(scope="session", autouse=True)
def _offline_session():
    """Offline from the first fixture of the session to the last.

    Per test was not enough: pytest builds a module-scoped fixture BEFORE the
    function-scoped ones of the test that first needs it, so
    tests/sources/test_airports.py's module `df` ran between one test's
    teardown and the next test's setup -- online -- and fetched OurAirports
    live. Integration tests read the REAL data/cache, so in the main checkout
    that was a test run refreshing the build's inputs.
    """
    from transport_maps.sources import _fetch

    _fetch.set_offline(True)
    yield
    _fetch.set_offline(None)


@pytest.fixture(autouse=True)
def _offline_inputs(_offline_session):
    """No test asks an upstream whether a raw input changed (G2).

    `sources._fetch` checks every input once per process; under pytest that
    would be a live request from any test that reaches a download, and the
    per-process memo would carry one test's answer into the next. Every test
    starts offline with an empty memo, and ends offline whatever it set;
    tests/sources/test_fetch.py turns the network back on against a stub.
    """
    from transport_maps.sources import _fetch

    _fetch.reset()
    _fetch.set_offline(True)
    yield
    _fetch.set_offline(True)
    _fetch.reset()


#: Reason prefix for a test skipped because a raw input it reads is not in the
#: cache. Before G2 such a test downloaded the input live -- in a fresh
#: worktree the country and urban tests fetched Natural Earth on every run --
#: which a test suite must not do.
NEEDS_INPUT = "needs a cached raw input"


@pytest.hookimpl(wrapper=True)
def pytest_runtest_call(item):
    """A test MARKED `needs_inputs` whose input is absent from the cache is
    SKIPPED, and says which input. Only the mark makes it a skip: unmarked,
    the same `MissingInput` is a failure. A blanket rule turned sixteen
    `_build_all` tests into silent skips the moment the build learned to check
    its inputs -- which is the change they exist to catch."""
    from transport_maps.sources import _fetch

    try:
        return (yield)
    except _fetch.MissingInput as exc:
        if not (str(exc).startswith("offline") and item.get_closest_marker("needs_inputs")):
            raise
        pytest.skip(f"{NEEDS_INPUT}: {exc}")


@pytest.fixture
def hermetic_build(monkeypatch, tmp_path):
    """Redirect `config.BUILD` at a scratch directory for one test.

    Opt-in, and NOT autouse, which is the whole point. `config.CACHE` can be
    redirected for everyone because the fast tests need only two seed archives
    from it. `config.BUILD` cannot: it holds the stamped land cells, the
    airports table and the road grid, and most of the suite reads them rather
    than building them. Redirecting it globally would turn a twenty-minute
    suite into a rebuild.

    So the hazard is real and has to be opted out of, one test at a time.
    Every `sources/` builder follows the same shape --

        out = _table_cache_path()
        if out.exists():
            return pl.read_parquet(out)
        ...actually build it...

    -- so a test that calls the builder without this fixture reads whatever
    the last real build left behind and never executes a line of the filter it
    claims to test. Cycle 15 proved it: mutating four separate things in
    `sources/airports.py` at once (`== "yes"` -> `!= "no"`, deleting the
    3-character IATA filter, `keep="first"` -> `"last"`, deleting `.sort`)
    left `tests/sources/test_airports.py` at **4 passed, GREEN**.

    Use this in any test whose subject writes into `config.BUILD`, and pair it
    with a stubbed download so the test neither fetches nor depends on a warm
    cache.
    """
    scratch = tmp_path / "build"
    scratch.mkdir()
    monkeypatch.setattr(config, "BUILD", scratch)
    return scratch


@pytest.fixture(scope="session")
def check_ramps():
    path = config.ROOT / "scripts" / "check_ramps.py"
    spec = importlib.util.spec_from_file_location("check_ramps", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


#: The sentinel that lets `scripts/deploy_verify.sh` tell one kind of skip
#: from another.
#:
#: Cycle 15's C15-2 found that `page_gate()` exited 0 when tests skipped, and
#: closed it with "any skip is a failure". That was right, and it immediately
#: broke `--page-only` -- the one deploy mode `deploy_verify.sh:17-19`
#: documents as not needing `dist/` -- because the same cycle added four
#: `dist/`-conditional skips to the gate's own file set. Measured with `dist/`
#: absent: 21 passed / 0 skipped became 14 passed / 7 skipped, and `dist/` is
#: gitignored, so that is every clone. It also contradicted
#: `tests/test_licence_firewall.py`, which asserts that a skip is the CORRECT
#: answer for an unbuilt tree.
#:
#: Both rules are right; they just need to be told apart. A test that skips
#: because nothing is built has not stopped checking anything -- there is
#: nothing to check. A test that skips for any other reason (no `node`, a
#: missing dependency, a condition someone added later) is a check that
#: silently stopped running, which is the hole C15-2 closed.
#:
#: So the reason string carries a sentinel, and the gate counts the two kinds
#: separately. Changing this string means changing `page_gate()` too; the
#: guard in `tests/test_deploy_script.py` fails if they drift apart.
NEEDS_DIST = "needs a built dist/"


def skip_without_dist(detail: str):
    """Skip because the tree has no built `dist/`, in the form the gate reads.

    Call it, do not raise it: `pytest.skip` raises, so this never returns.
    """
    pytest.skip(f"{NEEDS_DIST}: {detail}")
