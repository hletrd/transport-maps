from typing import ClassVar

import h3
import numpy as np
import polars as pl
import pytest

from transport_maps import config
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


def test_lookup_tables_are_plain_dicts_a_fork_can_use():
    from transport_maps.graph.rail import station_key
    routes = pl.DataFrame({
        "route_id": [1, 1], "seq": [0, 1], "stop_id": [10, 11],
        "lat": [37.0, 37.1], "lon": [127.0, 127.1],
        "name": ["A", "B"], "highspeed": [False, False], "route_name": ["Line One", "Line One"],
    })
    t = rail_detail.lookup_tables(routes)
    assert set(t) == {"lines", "stop_names"}
    assert isinstance(t["lines"], dict) and isinstance(t["stop_names"], dict)
    assert t["stop_names"][station_key(37.0, 127.0)] == "A"
    assert rail_detail.lookup_tables(None) == {"lines": {}, "stop_names": {}}


def test_write_rail_detail_never_touches_polars(monkeypatch, tmp_path):
    """The writer runs inside forked workers, where a polars call deadlocks
    (its thread pool does not survive fork). The lookup tables are built in
    the parent; with the module's `pl` removed the writer must still run."""
    tables = rail_detail.lookup_tables(pl.DataFrame({
        "route_id": [1, 1], "seq": [0, 1], "stop_id": [10, 11],
        "lat": [37.0, 37.1], "lon": [127.0, 127.1],
        "name": ["A", "B"], "highspeed": [False, False], "route_name": ["Line One", "Line One"],
    }))
    monkeypatch.setattr(rail_detail, "pl", None)        # any pl.* in the writer -> AttributeError

    class RealIdx(Idx):
        # real cells: the writer groups them into hover parents
        a = h3.latlng_to_cell(37.5, 127.0, config.SOLVE_RES)
        cells: ClassVar[list[str]] = [a, h3.grid_ring(a, 1)[0]]
    idx = RealIdx()
    minutes = np.array([0.0, 30.0, np.inf, np.inf, 5.0, 20.0])
    pred = np.array([-9999, 5, -9999, -9999, 0, 4])
    rail_detail.write_rail_detail(idx, minutes, pred, tables,
                                  tmp_path / "x.rail.bin", tmp_path / "x.rail.json")
    assert (tmp_path / "x.rail.bin").stat().st_size == 2 * len({h3.cell_to_parent(c, config.HOVER_RES) for c in idx.cells})


def test_a_rail_table_that_reaches_the_sentinel_is_refused(monkeypatch, tmp_path):
    """np.minimum used to fold table indexes past 65,535 into NO_RAIL silently."""
    tables = rail_detail.lookup_tables(pl.DataFrame({
        "route_id": [1, 1], "seq": [0, 1], "stop_id": [10, 11],
        "lat": [37.0, 37.1], "lon": [127.0, 127.1],
        "name": ["A", "B"], "highspeed": [False, False], "route_name": ["Line One", "Line One"],
    }))

    class OneCell:
        """cell 0; airport dep 1 / arr 2; stations 3, 4 -- the cell is reached by rail."""
        cells: ClassVar[list[str]] = [h3.latlng_to_cell(37.5, 127.0, config.SOLVE_RES)]
        n_cells = 1
        airports: ClassVar[list[str]] = ["AAA"]
        stations = ("s1", "s2")
    minutes = np.array([30.0, np.inf, np.inf, 5.0, 20.0])
    pred = np.array([4, -9999, -9999, -9999, 3])
    monkeypatch.setattr(rail_detail, "NO_RAIL", 1)     # a one-row table now "reaches" it
    with pytest.raises(ValueError, match="uint16 holds"):
        rail_detail.write_rail_detail(OneCell(), minutes, pred, tables,
                                      tmp_path / "x.rail.bin", tmp_path / "x.rail.json")
