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
