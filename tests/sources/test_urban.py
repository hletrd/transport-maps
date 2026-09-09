"""Urban congestion must slow cities and leave open country alone."""

import h3
import numpy as np

from transport_maps import config
from transport_maps.graph import ground
from transport_maps.graph.nodes import NodeIndex
from transport_maps.sources import urban


def _idx(points):
    cells = [h3.latlng_to_cell(la, lo, config.SOLVE_RES) for la, lo in points]
    cells = list(dict.fromkeys(cells))
    return NodeIndex(cells, [], {c: i for i, c in enumerate(cells)}, {}, {}, ())


def test_cities_are_marked_and_empty_country_is_not():
    pts = [(51.5074, -0.1278),    # London
           (35.6762, 139.6503),   # Tokyo
           (-25.0, 132.0),        # central Australian desert
           (68.0, 100.0)]         # central Siberia
    mask = urban.urban_mask(
        [h3.latlng_to_cell(la, lo, config.SOLVE_RES) for la, lo in pts])
    assert mask[0] and mask[1], "a major city was not marked urban"
    assert not mask[2] and not mask[3], "empty country was marked urban"


def test_an_urban_cell_is_slower_than_the_same_class_in_open_country():
    """The whole point: GRIP4 gives both the grade of their best road."""
    idx = _idx([(51.5074, -0.1278), (-25.0, 132.0)])
    speeds = ground.cell_speed_kmh(idx)
    mask = urban.urban_mask(idx.cells)
    assert mask[0] and not mask[1]
    # London's cell holds a motorway, so without the factor it would be fastest.
    assert speeds[0] <= ground.SPEED_BY_ROAD_CLASS_KMH[1] / urban.URBAN_CONGESTION_FACTOR + 1e-9


def test_the_factor_actually_divides():
    idx = _idx([(51.5074, -0.1278)])
    from transport_maps.sources import roads

    raw = ground.SPEED_BY_ROAD_CLASS_KMH[roads.cell_class(idx.cells)][0]
    got = ground.cell_speed_kmh(idx)[0]
    assert np.isclose(got, raw / urban.URBAN_CONGESTION_FACTOR)


def test_roadless_terrain_is_never_slowed_by_traffic():
    """A roadless cell is already at walking pace.

    Applying congestion to it produced 2.5 km/h -- below the table's own floor
    for the slowest terrain on Earth, which is how the range test caught it.
    """
    from transport_maps.sources import roads

    # A roadless cell that nonetheless falls inside a city radius.
    idx = _idx([(51.5074, -0.1278), (-25.0, 132.0), (68.0, 100.0)])
    speeds = ground.cell_speed_kmh(idx)
    cls = roads.cell_class(idx.cells)
    for i, c in enumerate(cls):
        if c == 0:
            assert speeds[i] == ground.SPEED_BY_ROAD_CLASS_KMH[0], \
                "traffic was applied to roadless terrain"
    assert speeds.min() >= ground.SPEED_BY_ROAD_CLASS_KMH.min()
