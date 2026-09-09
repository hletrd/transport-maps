"""Surface minutes must be attributed to the mode that actually carried them."""

from typing import ClassVar

import h3
import numpy as np
import pytest

from transport_maps import config
from transport_maps.emit import modes


class Idx:
    """cells [0,3), departures [3,5), arrivals [5,7), stations [7,9)."""

    n_cells = 3
    airports: ClassVar[list[str]] = ["AAA", "BBB"]
    stations = ("s0", "s1")

    def __init__(self, cells):
        self.cells = cells


def _adjacent_pair():
    a = h3.latlng_to_cell(48.85, 2.35, config.SOLVE_RES)
    b = [c for c in h3.grid_disk(a, 1) if c != a][0]
    far = h3.latlng_to_cell(-33.87, 151.21, config.SOLVE_RES)
    return a, b, far


def test_road_and_ferry_are_told_apart_by_adjacency():
    """Two cells that do not touch can only be joined by a crossing."""
    a, b, far = _adjacent_pair()
    idx = Idx([a, b, far])
    minutes = np.array([0.0, 30.0, 200.0, *([np.inf] * 6)])
    prev = np.array([-9999, 0, 0, -9999, -9999, -9999, -9999, -9999, -9999])
    acc = modes.mode_minutes_per_node(idx, minutes, prev, cell_class=np.array([1, 1, 0]))
    road = acc[1][2:].sum()
    assert road == 30.0 and acc[1][1] == 0.0, "neighboring cells are road"
    assert acc[2][1] == 200.0 and acc[2][2:].sum() == 0.0, \
        "a jump between cells is a ferry"


@pytest.mark.parametrize("grip_class,channel", [
    (1, "highway"), (2, "major road"), (3, "major road"),
    (4, "minor road"), (5, "minor road"), (0, "track"),
])
def test_road_minutes_land_in_the_channel_of_the_destination_cells_grade(grip_class, channel):
    """Summing the road channels hid WHICH one received the minutes: a swapped
    ROAD_CHANNEL table stayed green. Each GRIP4 grade is pinned to its
    channel here, by name, so the page's tooltips describe the right road."""
    a, b, far = _adjacent_pair()
    idx = Idx([a, b, far])
    minutes = np.array([0.0, 30.0, np.inf, *([np.inf] * 6)])
    prev = np.array([-9999, 0, -9999, -9999, -9999, -9999, -9999, -9999, -9999])
    acc = modes.mode_minutes_per_node(idx, minutes, prev,
                                      cell_class=np.array([0, grip_class, 0]))
    expected = np.zeros(len(modes.CHANNELS)); expected[modes.CHANNELS.index(channel)] = 30.0
    assert acc[1].tolist() == expected.tolist(), f"class {grip_class} booked as {acc[1]}"


def test_station_edges_count_as_rail_and_accumulate():
    a, b, far = _adjacent_pair()
    idx = Idx([a, b, far])
    #   cell0 -> station7 (board) -> station8 (ride) -> cell1 (alight)
    minutes = np.array([0.0, 100.0, np.inf, *([np.inf] * 4), 15.0, 80.0])
    prev = np.array([-9999, 8, -9999, -9999, -9999, -9999, -9999, 0, 7])
    acc = modes.mode_minutes_per_node(idx, minutes, prev, cell_class=np.array([1, 1, 0]))
    assert acc[8][0] == 80.0, "boarding plus riding must accumulate as rail"
    assert acc[1][0] == 100.0, "alighting adds to the rail total"
    assert acc[1][1] == 0.0 and acc[1][2:].sum() == 0.0


def test_air_and_airport_time_are_not_counted_as_surface():
    a, b, far = _adjacent_pair()
    idx = Idx([a, b, far])
    #   cell0 -> dep3 (airport) -> arr6 (flight) -> cell1 (disembark)
    minutes = np.array([0.0, 300.0, np.inf, 70.0, np.inf, np.inf, 260.0, np.inf, np.inf])
    prev = np.array([-9999, 6, -9999, 0, -9999, -9999, 3, -9999, -9999])
    acc = modes.mode_minutes_per_node(idx, minutes, prev, cell_class=np.array([1, 1, 0]))
    assert acc[1].sum() == 0.0, "flight and airport time leaked into the surface totals"


def test_written_file_is_one_uint16_per_channel_per_hover_cell(tmp_path):
    a, b, far = _adjacent_pair()
    idx = Idx([a, b, far])
    minutes = np.array([0.0, 30.0, 200.0, *([np.inf] * 6)])
    prev = np.array([-9999, 0, 0, -9999, -9999, -9999, -9999, -9999, -9999])
    out = tmp_path / "x.modes.bin"
    modes.write_modes(idx, minutes, prev, out, cell_class=np.array([1, 1, 0]))
    parents = {h3.cell_to_parent(c, config.HOVER_RES) for c in idx.cells}
    assert out.stat().st_size == len(parents) * len(modes.CHANNELS) * 2
