"""The arrival-airport array must name the route that produced the time."""

import numpy as np
import pytest

from transport_maps.emit import itinerary


class Idx:
    """cells [0,3), departures [3,5), arrivals [5,7)."""
    cells = ["a", "b", "c"]
    airports = ["AAA", "BBB"]
    n_cells = 3


def test_a_node_reached_through_an_airport_reports_that_airport():
    # 0 -> dep AAA(3) -> arr BBB(6) -> cell 2
    minutes = np.array([0.0, np.inf, 40.0, 10.0, np.inf, np.inf, 30.0])
    prev = np.array([-9999, -9999, 6, 0, -9999, -9999, 3])
    last = itinerary.arrival_airport_per_node(Idx(), minutes, prev)
    assert last[2] == 6, "cell did not inherit the arrival airport it came through"
    assert last[6] == 6, "an arrival node must be its own airport"


def test_a_purely_overland_journey_reports_no_airport():
    minutes = np.array([0.0, 12.0, 25.0, np.inf, np.inf, np.inf, np.inf])
    prev = np.array([-9999, 0, 1, -9999, -9999, -9999, -9999])
    last = itinerary.arrival_airport_per_node(Idx(), minutes, prev)
    assert last[2] == -1


def test_unreachable_nodes_are_left_unassigned():
    minutes = np.array([0.0, np.inf, np.inf, np.inf, np.inf, np.inf, np.inf])
    prev = np.array([-9999] * 7)
    last = itinerary.arrival_airport_per_node(Idx(), minutes, prev)
    assert (last[1:] == -1).all()


def test_the_second_leg_of_a_connection_wins_over_the_first():
    """A connecting journey must report where it LANDED, not where it changed.

    0 -> dep AAA(3) -> arr AAA(5) -> dep BBB(4) -> arr BBB(6) -> cell 2
    Reporting node 5 would caption the reading with the connecting airport.
    """
    minutes = np.array([0.0, np.inf, 300.0, 10.0, 150.0, 120.0, 260.0])
    prev = np.array([-9999, -9999, 6, 0, 5, 3, 4])
    last = itinerary.arrival_airport_per_node(Idx(), minutes, prev)
    assert last[2] == 6, "reported the connecting airport, not the arrival"


def test_written_array_is_one_uint16_per_hover_cell(tmp_path):
    import h3

    from transport_maps import config

    class RealIdx:
        cells = [h3.latlng_to_cell(37.5, 127.0, config.SOLVE_RES),
                 h3.latlng_to_cell(35.6, 139.7, config.SOLVE_RES)]
        airports = ["AAA", "BBB"]
        n_cells = 2

    n = RealIdx.n_cells
    minutes = np.concatenate([np.array([0.0, 90.0]), np.full(4, np.inf)])
    prev = np.full(n + 4, -9999)
    out = tmp_path / "x.air.bin"
    itinerary.write_itinerary(RealIdx(), minutes, prev, out)

    parents = {h3.cell_to_parent(c, config.HOVER_RES) for c in RealIdx.cells}
    assert out.stat().st_size == len(parents) * 2
    assert (np.frombuffer(out.read_bytes(), dtype="<u2") == itinerary.NO_AIRPORT).all()
