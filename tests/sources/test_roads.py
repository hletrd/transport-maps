import numpy as np
import pytest

from transport_maps.sources import roads


@pytest.fixture(scope="module")
def grid():
    return roads.road_class_grid()


def test_grid_shape_is_five_arcmin_global(grid):
    assert grid.shape == (2160, 4320)
    assert grid.dtype == np.uint8


def test_open_ocean_has_no_roads(grid):
    assert roads.sample_class(np.array([0.0]), np.array([-160.0]))[0] == 0


def test_motorway_corridors_are_class_one(grid):
    """Points on real expressways. Measured tp1 density: 243, 666, 494 m/km2."""
    # Yangjae IC on the Gyeongbu Expressway; Los Angeles; Essen in the Ruhr.
    lats = np.array([37.4837, 34.0522, 51.5136])
    lons = np.array([127.0325, -118.2437, 7.4653])
    assert (roads.sample_class(lats, lons) == 1).all()


def test_dense_urban_core_without_a_motorway_is_still_well_roaded(grid):
    """Seoul's historic core has no motorway in its 5-arcmin cell but is dense.

    Measured: tp1 = 0, tp2 = 1573 m/km2. Seoul's expressways ring the old city
    rather than cross it, so this cell is class 2, not class 1. Asserting class 1
    here would be a false premise about how road networks are laid out, not a
    threshold problem -- do not "fix" it by lowering DENSITY_THRESHOLD.
    """
    assert roads.sample_class(np.array([37.5665]), np.array([126.9780]))[0] == 2


def test_remote_interior_is_lower_grade_than_a_capital(grid):
    remote = roads.sample_class(np.array([-24.0]), np.array([126.0]))[0]  # W. Australia
    seoul = roads.sample_class(np.array([37.5665]), np.array([126.9780]))[0]
    assert remote > seoul or remote == 0  # higher number = lower grade
