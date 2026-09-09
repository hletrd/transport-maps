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


@pytest.fixture(scope="session")
def check_ramps():
    path = config.ROOT / "scripts" / "check_ramps.py"
    spec = importlib.util.spec_from_file_location("check_ramps", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
