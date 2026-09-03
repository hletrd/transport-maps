import h3
import numpy as np
import pytest

from transport_maps.graph import nodes
from transport_maps.sources import roads


@pytest.fixture(scope="module")
def grid():
    return roads.road_class_grid()


@pytest.fixture(scope="module")
def idx():
    return nodes.build_index()


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


def test_cell_class_finds_roads_the_centroid_misses(grid):
    """An H3 res-5 cell (~253 km2) spans 3-6 GRIP4 cells (~86 km2 at the equator,
    ~43 km2 at 60 degrees), so a centroid-only sample can land in a gap between
    roads that the cell's footprint otherwise covers.

    Measured for this cell, near Alta, Norway: the centroid falls on a GRIP4 cell
    with class 0 (roadless), but the cell's footprint window is

        [[0 0 0 0 0 0 0]
         [2 0 0 0 0 0 0]
         [2 2 2 2 2 1 1]]

    which contains a class-1 (highway) cell at its edge.
    """
    cell = "85012013fffffff"
    lat, lon = h3.cell_to_latlng(cell)
    centroid_grade = roads.sample_class(np.array([lat]), np.array([lon]))[0]
    footprint_grade = roads.cell_class([cell])[0]

    assert centroid_grade == 0
    assert footprint_grade == 1


def test_cell_class_is_never_worse_than_centroid_sampling(idx):
    """Footprint aggregation can only add roads a centroid sample missed, never
    remove ones it found -- the footprint is a superset of the single centroid
    pixel, so its best (lowest non-zero) class can only tie or improve.

    Class 0 means roadless and is the WORST outcome, not the smallest number, so
    grade is ranked with 0 lowest and class 1 (highway) highest before comparing;
    a naive numeric comparison of the raw class codes gets this backwards.
    """
    rng = np.random.default_rng(20260903)
    sample = rng.choice(idx.n_cells, size=4000, replace=False)
    cells = [idx.cells[i] for i in sample]

    centroids = np.array([h3.cell_to_latlng(c) for c in cells], dtype=np.float64)
    centroid_grade = roads.sample_class(centroids[:, 0], centroids[:, 1])
    footprint_grade = roads.cell_class(cells)

    def rank(grade: np.ndarray) -> np.ndarray:
        # 0 (roadless) is worst; class 1 (highway) is best.
        return np.where(grade == 0, 0, 6 - grade)

    assert (rank(footprint_grade) >= rank(centroid_grade)).all()


def test_cell_class_handles_the_antimeridian_without_crashing():
    """A land cell whose H3 boundary wraps +/-180 degrees longitude makes a plain
    min/max bounding box meaningless (it would span the wrong side of the globe),
    so cell_class must fall back to centroid sampling for it instead of crashing
    or silently returning a bogus window.

    Pin the fallback's actual OUTPUT, not just its shape: near +/-180 degrees the
    naive bbox path computes c0 about 0 and c1 about 4319 -- nearly the entire
    longitude band at that latitude -- which would still return some class in
    [0, 5] without crashing. Only checking the shape/range therefore cannot tell
    a working fallback from a dead one, so assert equality with the exact
    centroid sample the fallback is meant to return instead.
    """
    cell = "85045b23fffffff"  # near Chukotka, Russia; boundary lon span > 180 deg
    boundary = h3.cell_to_boundary(cell)
    lons = [p[1] for p in boundary]
    assert max(lons) - min(lons) > 180.0  # confirms this cell exercises the fallback

    lat, lon = h3.cell_to_latlng(cell)
    expected = roads.sample_class(np.array([lat]), np.array([lon]))[0]
    assert roads.cell_class([cell])[0] == expected


def test_row_and_col_helpers_are_not_transposed():
    """Direct pin against a source/column swap, rather than relying only on the
    statistical coverage of the Alta case and the 4,000-cell invariant test.

    lat=60, lon=-120 gives row = (90-60)*12 = 360 and col = (-120+180)*12 = 720 --
    clearly distinct values (12 = cells per degree, since 5 arcmin = 1/12 degree),
    so a `_row_of`/`_col_of` transposition fails this immediately.
    """
    assert roads._row_of(60.0) == 360
    assert roads._col_of(-120.0) == 720
