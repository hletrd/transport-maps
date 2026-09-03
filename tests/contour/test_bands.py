import numpy as np
import pytest

from transport_maps import config
from transport_maps.contour import bands


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
