"""The per-origin writers read the international airport layer (A15).

Since A15 an airport has its departure and arrival nodes twice
(graph/layout.py): the international pair sits AFTER the stations, so every
writer that classified a node by `node >= first_station` would have read a
traveller from abroad as a rail passenger, and every one that took
`node - first_arrival` as an airport ordinal would have named an airport that
does not exist. One hand-built shortest-path tree, checked against each:

    ids   0 1 2 | 3 4  | 5 6  | 7  | 8 9    | 10 11
          cells | dep  | arr  | st | i-dep  | i-arr     airports A, B; one station

    c0 (origin) -> A dep -> B intl arr -> c2 (B's cell)   a flight from abroad
    A dep -> B arr -> B dep                               B's domestic side, used
    B intl arr -> B intl dep                              reached, but leads nowhere
    c0 -> c1 (A's cell)                                   overland
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import h3
import numpy as np

from transport_maps import config
from transport_maps.emit import itinerary, modes, override, rail_detail, routes_json
from transport_maps.graph.layout import NodeLayout
from transport_maps.graph.nodes import NodeIndex

INF = np.inf
NO = -9999
#                    c0   c1   c2    depA depB arrA arrB  st0  xdA  xdB  xaA  xaB
MINUTES = np.array([0.0, 5.0, 120.0, 10.0, 200.0, INF, 150.0, INF, INF, 170.0, INF, 100.0])
PRED = np.array([NO, 0, 11, 0, 6, NO, 3, NO, NO, 11, NO, 3])


def _idx():
    base = h3.latlng_to_cell(37.5665, 126.9780, config.SOLVE_RES)
    cells = [base, *sorted(h3.grid_ring(base, 1))[:2]]
    return NodeIndex(cells=cells, airports=["A", "B"],
                     _cell_pos={c: i for i, c in enumerate(cells)},
                     _airport_pos={"A": 3, "B": 4},
                     _airport_cell={"A": 1, "B": 2},
                     stations=("s0",), _station_pos={"s0": 7}, _station_cell={"s0": 0})


def test_the_layout_puts_the_international_layer_after_the_stations():
    lay = _idx().layout
    assert lay == NodeLayout(3, 2, 1)
    assert (lay.first_station, lay.first_intl_departure, lay.first_intl_arrival, lay.n) == \
        (7, 8, 10, 12)
    assert [lay.is_station(v) for v in (6, 7, 8)] == [False, True, False]
    assert [lay.arrival_ordinal(v) for v in (4, 5, 6, 7, 9, 10, 11)] == [-1, 0, 1, -1, -1, 0, 1]
    idx = _idx()
    assert (idx.airport_intl_index("B"), idx.airport_intl_arr_index("B")) == (9, 11)


def test_a_journey_from_abroad_names_its_airport_in_the_itinerary(tmp_path):
    """`.air.bin` carries the airport ordinal, whichever layer it landed on.

    Mutations performed and reverted, each -> red: `is_arrival` -> the
    domestic range only (c2 reads as overland); `arrival_ordinal(node)` ->
    `node - first_arrival` (ordinal 6, an airport that does not exist).
    """
    idx = _idx()
    last = itinerary.arrival_airport_per_node(idx, MINUTES, PRED)
    assert last[2] == 11 and last[1] == -1
    out = tmp_path / "x.air.bin"
    itinerary.write_itinerary(idx, MINUTES, PRED, out, parents=["p0", "p1", "p2"],
                              rep={0: 0, 1: 1, 2: 2})
    assert np.frombuffer(out.read_bytes(), "<u2").tolist() == \
        [itinerary.NO_AIRPORT, itinerary.NO_AIRPORT, 1]


def test_the_override_names_the_same_airport():
    """Mutation performed and reverted: `last[nodes] - first_arrival` -> red."""
    idx = _idx()
    last = itinerary.arrival_airport_per_node(idx, MINUTES, PRED)
    layout = SimpleNamespace(source=np.array([2]), dest=np.array([42]))
    acc = np.zeros((len(MINUTES), len(modes.CHANNELS)))
    slots, airport, _ = override.override_entries(idx, last, acc, np.array([1]),
                                                  np.array([0]), layout)
    assert slots.tolist() == [42] and airport.tolist() == [1]


def test_an_international_arrival_is_not_counted_as_rail():
    """Mutation performed and reverted: `is_station` -> `node >= first_station`
    -> red (the flight and the walk out booked as 110 rail minutes)."""
    acc = modes.mode_minutes_per_node(_idx(), MINUTES, PRED, cell_class=np.array([1, 1, 1]))
    assert acc[2][0] == 0.0


def test_an_international_arrival_is_not_a_station_for_the_rail_caption():
    """Mutation performed and reverted: `is_station` -> `node >= first_station`
    -> red (c2's "last station" is an airport node)."""
    assert rail_detail.last_station_per_node(_idx(), MINUTES, PRED)[2] == -1


def test_the_routes_file_enters_at_the_node_the_journey_left_the_airport_from(tmp_path):
    """B's cell was reached from B's INTERNATIONAL arrival, so that node is
    listed under the id the page enters at (`airports + n_air + 1` = 6) and
    the domestic one under the other id (11); every `prev` follows the swap.
    International nodes no chain reaches are left out.

    Mutations performed and reverted, each -> red: skip the swap (id 6 is
    the domestic arrival, min 150); rename `id` but not `prev` (B's departure
    points at the international arrival); list no international node (the
    entry is missing); list every reachable one (B's international
    departure, 9, appears); walk back from the listed nodes only, without
    the entries (the entry is missing).
    """
    out = tmp_path / "x.json"
    routes_json.write_routes(_idx(), MINUTES, PRED, out)
    payload = json.loads(out.read_text())
    assert payload["offsets"] == {"cells": 0, "airports": 3, "stations": 7, "intl": 8}
    by_id = {n["id"]: n for n in payload["nodes"]}
    assert by_id[6] == {"id": 6, "kind": "arr", "code": "B", "min": 100, "prev": 3}
    assert by_id[11] == {"id": 11, "kind": "arr", "code": "B", "min": 150, "prev": 3}
    assert by_id[4] == {"id": 4, "kind": "dep", "code": "B", "min": 200, "prev": 11}
    assert set(by_id) == {3, 4, 6, 11}
