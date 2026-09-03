import h3
import pytest

from transport_maps import config
from transport_maps.sources import landmask


@pytest.fixture(scope="module")
def cells() -> set[str]:
    return set(landmask.land_cells(config.SOLVE_RES))


def test_cell_count_matches_measured_baseline(cells):
    # Measured: 548,557 cells from 6,657 non-Antarctic parts at contain="overlap".
    assert 500_000 < len(cells) < 620_000


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
