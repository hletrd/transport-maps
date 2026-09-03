import h3
import numpy as np
import pytest
from shapely.geometry import Polygon

from transport_maps import config, validate
from transport_maps.contour import bands
from transport_maps.graph import build, nodes
from transport_maps.solve import dijkstra


def test_band_boundaries_are_inclusive_of_the_lower_band():
    assert bands.band_of(0.0) == 0
    assert bands.band_of(119.0) == 0
    assert bands.band_of(120.0) == 0      # exactly 2h is still the first band
    assert bands.band_of(121.0) == 1


def test_beyond_the_last_edge_is_the_open_ended_band():
    last = len(config.BAND_EDGES_MIN)
    assert bands.band_of(config.BAND_EDGES_MIN[-1] + 1) == last
    assert bands.band_of(float("inf")) == bands.UNREACHABLE_BAND


def test_feature_collection_has_one_feature_per_occupied_band():
    class FakeIndex:
        cells = ["8530e08ffffffff", "8530e087fffffff"]
        n_cells = 2
    fc = bands.band_feature_collection(FakeIndex(), np.array([10.0, 5000.0]))
    assert fc["type"] == "FeatureCollection"
    assert len(fc["features"]) == 2
    assert {f["properties"]["band"] for f in fc["features"]} == {0, 10}


def test_bands_are_emitted_in_ascending_order():
    """Bands are drawn as stacked fills on the frontend; emitting the slow
    bands before the fast ones would paint the fast bands underneath."""
    class FakeIndex:
        cells = ["8530e08ffffffff", "8530e087fffffff", "852f5a37fffffff"]
        n_cells = 3
    # Insertion order (9, 0, 5) deliberately does not match ascending band order,
    # so a reversed or unsorted emission order would show up here.
    fc = bands.band_feature_collection(FakeIndex(), np.array([3000.0, 10.0, 1000.0]))
    assert [f["properties"]["band"] for f in fc["features"]] == [0, 5, 9]


def test_max_minutes_matches_the_band_edge_and_is_none_past_the_last_edge():
    class FakeIndex:
        cells = ["8530e08ffffffff", "8530e087fffffff", "852f5a37fffffff"]
        n_cells = 3
    # band 0 (10 min), band 5 (1000 min), and past the last edge (5000 min -> open band)
    fc = bands.band_feature_collection(FakeIndex(), np.array([10.0, 1000.0, 5000.0]))
    by_band = {f["properties"]["band"]: f["properties"]["max_minutes"] for f in fc["features"]}
    assert by_band[0] == config.BAND_EDGES_MIN[0]
    assert by_band[5] == config.BAND_EDGES_MIN[5]
    assert by_band[len(config.BAND_EDGES_MIN)] is None


def test_cell_minutes_shorter_than_the_cell_universe_is_rejected():
    class FakeIndex:
        cells = ["8530e08ffffffff", "8530e087fffffff"]
        n_cells = 2
    with pytest.raises(ValueError, match="cell_minutes shorter than the cell universe"):
        bands.band_feature_collection(FakeIndex(), np.array([10.0]))


# A real H3 res-5 cell near Fiji whose boundary straddles +/-180. Confirmed by
# search: max(lons) - min(lons) > 180 for its raw h3.cell_to_boundary output.
ANTIMERIDIAN_CELL = "859b400bfffffff"


def test_antimeridian_cell_naively_read_is_invalid_and_globe_spanning():
    """Pins the bug this fix exists for: building a polygon straight from the
    raw H3 boundary (no unwrapping) makes a wrapping cell's ring invalid and
    inflates its area by three orders of magnitude -- 0.02 deg^2 of real land
    read as 27+ deg^2, which is what made isochrone bands appear to overlap.
    """
    assert bands._crosses_antimeridian(ANTIMERIDIAN_CELL)
    boundary = h3.cell_to_boundary(ANTIMERIDIAN_CELL)
    naive = Polygon([(lon, lat) for lat, lon in boundary])
    assert not naive.is_valid
    assert naive.area == pytest.approx(27.316365837306222, rel=1e-9)


def test_antimeridian_cell_splits_into_a_valid_geometry_at_its_true_area():
    """The fix: dissolving the same cell must produce a VALID geometry whose
    area matches its true unwrapped size, not the globe-spanning naive one.
    """
    geometry = bands._dissolve([ANTIMERIDIAN_CELL])
    assert geometry.is_valid
    assert geometry.area == pytest.approx(0.020117758657720624, rel=1e-9)
    # Nowhere near the 27+ deg^2 the naive (buggy) reading produced.
    assert geometry.area < 1.0


@pytest.fixture(scope="module")
def seoul_band_feature_collection():
    idx = nodes.build_index()
    csr = build.build_graph(idx)
    source = dijkstra.origin_node(idx, 37.5665, 126.9780)
    minutes = dijkstra.solve_from(csr, source)
    return bands.band_feature_collection(idx, minutes[: idx.n_cells])


def test_real_multi_band_solve_passes_the_disjoint_bands_gate(seoul_band_feature_collection):
    """Regression guard for the antimeridian bug: a real Seoul solve produces
    bands (including far bands with hundreds of disconnected, globe-scattered
    components and antimeridian-crossing cells) that the publish gate accepts.
    Before the fix this raised inside `check_bands_disjoint` with a GEOS
    TopologyException, and after a naive validity repair it raised ValueError
    for genuine overlap between the far bands.
    """
    assert len(seoul_band_feature_collection["features"]) > 5  # exercise the far bands too
    validate.check_bands_disjoint(seoul_band_feature_collection)  # must not raise
