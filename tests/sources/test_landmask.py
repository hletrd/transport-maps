import h3
import pytest
import shapely

from transport_maps import config
from transport_maps.sources import landmask

# Builds the full node index from the cached universe: minutes, real caches.
pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def cells() -> set[str]:
    return set(landmask.land_cells(config.SOLVE_RES))


# Measured land-cell counts per solver resolution at contain="overlap":
# 599,741 at res 5 and 4,091,715 at res 6 with the current stamp (548,557 at
# res 5 before the lake and ice-shelf sources landed). These include the
# Antarctic wedges -- 363,488 of the res-6 cells (2026-10-02) -- which an
# earlier version of this comment said they excluded. Keyed
# on the configured resolution so the bound moves with the grid instead of
# silently asserting the res-5 range against a res-6 universe.
MEASURED_CELL_COUNT_BOUNDS = {5: (500_000, 620_000), 6: (3_800_000, 4_400_000)}


def test_cell_count_matches_measured_baseline(cells):
    res = config.SOLVE_RES
    if res not in MEASURED_CELL_COUNT_BOUNDS:
        pytest.fail(f"no measured cell-count baseline for SOLVE_RES={res}; "
                    "measure the universe and add its bound here")
    lo, hi = MEASURED_CELL_COUNT_BOUNDS[res]
    assert lo < len(cells) < hi, f"{len(cells):,} cells at res {res}, expected {lo:,}-{hi:,}"


@pytest.mark.parametrize("name,lat,lon", [
    ("Seoul", 37.5665, 126.9780),
    ("Sahara", 23.0, 10.0),
])
def test_continental_land_is_covered(cells, name, lat, lon):
    assert h3.latlng_to_cell(lat, lon, config.SOLVE_RES) in cells


@pytest.mark.parametrize("name,lat,lon", [
    ("Reykjavik", 64.1460, -21.9400),
    ("Male", 4.1755, 73.5093),
    ("Honolulu", 21.3150, -157.8580),
    ("Nauru", -0.5477, 166.9209),
])
def test_islands_and_coastlines_are_covered(cells, name, lat, lon):
    """Regression guard: contain="center" deletes every one of these."""
    assert h3.latlng_to_cell(lat, lon, config.SOLVE_RES) in cells


@pytest.mark.parametrize("name,lat,lon", [
    ("mid-Pacific", 0.0, -160.0),
    ("N.Atlantic", 45.0, -40.0),
])
def test_open_ocean_is_excluded(cells, name, lat, lon):
    assert h3.latlng_to_cell(lat, lon, config.SOLVE_RES) not in cells


def test_islands_survive_a_cache_free_run(tmp_path, monkeypatch):
    """Cache-independent regression guard.

    `test_islands_and_coastlines_are_covered` above reads the module-scoped
    `cells` fixture, which is backed by the real `data/build/land_cells_r5.parquet`
    cache once it exists. That means it can no longer catch a regression from
    `contain="overlap"` back to the default `contain="center"` -- it would just
    read the stale, still-correct cache. This test forces the real code path:
    `config.BUILD` is redirected to an empty `tmp_path` (no cache to short-circuit
    to) and `_land_parts` is monkeypatched to return two islands far smaller than
    a single res-5 cell (~253 km^2), so only `contain="overlap"` keeps them.
    """
    monkeypatch.setattr(config, "BUILD", tmp_path)

    male = shapely.box(73.5093 - 0.01, 4.1755 - 0.01, 73.5093 + 0.01, 4.1755 + 0.01)
    nauru = shapely.box(166.9209 - 0.01, -0.5477 - 0.01, 166.9209 + 0.01, -0.5477 + 0.01)
    monkeypatch.setattr(landmask, "_land_parts", lambda: [male, nauru])

    result = set(landmask.land_cells(config.SOLVE_RES))

    assert h3.latlng_to_cell(4.1755, 73.5093, config.SOLVE_RES) in result
    assert h3.latlng_to_cell(-0.5477, 166.9209, config.SOLVE_RES) in result
