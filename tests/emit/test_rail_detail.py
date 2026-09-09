from typing import ClassVar

import numpy as np
import polars as pl

from transport_maps.emit import rail_detail


class Idx:
    """Two cells, one airport (dep+arr), two stations: cells 0,1; air 2,3; stations 4,5."""
    cells: ClassVar[list[str]] = ["8630e08ffffffff", "8630e087fffffff"]
    n_cells = 2
    airports: ClassVar[list[str]] = ["AAA"]
    stations = ("s1", "s2")


def test_last_station_follows_the_shortest_path_tree():
    idx = Idx()
    # cell0 -> station4 -> station5 -> cell1 ; airport nodes unreachable
    minutes = np.array([0.0, 30.0, np.inf, np.inf, 5.0, 20.0])
    pred = np.array([-9999, 5, -9999, -9999, 0, 4])
    last = rail_detail.last_station_per_node(idx, minutes, pred)
    assert last.tolist() == [-1, 5, -1, -1, 4, 5]


def test_line_name_comes_from_the_route_that_joins_the_two_stops():
    from transport_maps.graph.rail import station_key
    routes = pl.DataFrame({
        "route_id": [1, 1, 2, 2], "seq": [0, 1, 0, 1],
        "stop_id": [10, 11, 12, 13],
        "lat": [37.0, 37.1, 37.0, 37.1], "lon": [127.0, 127.1, 127.0, 127.1],
        "name": ["A", "B", "A", "B"], "highspeed": [False] * 4,
        "route_name": ["Line One", "Line One", "Line Two", "Line Two"],
    })
    lines = rail_detail._line_between(routes)
    a, b = station_key(37.0, 127.0), station_key(37.1, 127.1)
    assert lines[(a, b)] == "Line One" and lines[(b, a)] == "Line One"  # first route wins
