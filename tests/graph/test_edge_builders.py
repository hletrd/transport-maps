"""The air, access and transfer edge builders, run for real on seven airports (F10).

Every other test reaches these three through `build_graph` over the whole
cached universe (`test_build.py`, integration) or replaces them with stubs
(`test_duplicate_row_col_pairs_across_edge_parts_are_rejected`). Neither can
say whether a border is charged on the right flight, whether a traveller
enters an airport on the departure side, or whether a connection costs
`max(MCT, wait)` rather than their sum: the real-graph tests check only that
the weights are finite and that ICN reaches NRT.

Only the two INPUT tables are stubbed -- the airport table and the route
network -- so the builders, the calibration file and the transfer rules all
run as the build runs them. The block time itself comes from
`air.block_time_min`, which has its own tests (`test_air.py`); what is under
test here is what the builders add to it and where they put it.
"""

from __future__ import annotations

import h3
import numpy as np
import polars as pl
import pytest

from transport_maps import config
from transport_maps.graph import air, build
from transport_maps.graph.nodes import NodeIndex

# iata, lat, lon, size, country
AIRPORTS = [
    ("ICN", 37.4602, 126.4407, "large", "KR"),
    ("NRT", 35.7720, 140.3929, "large", "JP"),
    ("PUS", 35.1795, 128.9382, "medium", "KR"),
    ("CDG", 49.0097, 2.5479, "large", "FR"),
    ("FRA", 50.0379, 8.5622, "large", "DE"),
    ("XSM", 36.0000, 140.0000, "small", "JP"),   # flown to, never from
    ("SML", 43.6290, 1.3638, "small", "FR"),     # only reached by an implausible pair
]
ROUTES = [
    ("ICN", "NRT"),    # international, large-large
    ("ICN", "CDG"),    # 8,960 km, but two large ends: plausible
    ("NRT", "ICN"),
    ("PUS", "NRT"),    # medium -> large: the border is the LARGER terminal's
    ("PUS", "XSM"),    # medium -> small: the medium terminal's
    ("CDG", "FRA"),    # Schengen: a national border, no passport desk
    ("PUS", "SML"),    # > 8,000 km, neither end large: rejected
]
META = {a[0]: a[1:] for a in AIRPORTS}
CAL = air.load_calibration()


@pytest.fixture
def idx(monkeypatch):
    monkeypatch.setattr(build.airports, "scheduled_airports", lambda: pl.DataFrame(
        AIRPORTS, schema=["iata", "lat", "lon", "size", "country"], orient="row"))
    monkeypatch.setattr(build.routes, "route_network", lambda: pl.DataFrame(
        ROUTES, schema=["src", "dst"], orient="row"))
    cells = [h3.latlng_to_cell(lat, lon, config.SOLVE_RES) for _, lat, lon, _, _ in AIRPORTS]
    assert len(set(cells)) == len(cells)
    iatas = [a[0] for a in AIRPORTS]
    return NodeIndex(cells=cells, airports=iatas,
                     _cell_pos={c: i for i, c in enumerate(cells)},
                     _airport_pos={a: len(cells) + i for i, a in enumerate(iatas)},
                     _airport_cell={a: i for i, a in enumerate(iatas)})


def _edges(parts) -> dict[tuple[int, int], float]:
    rows, cols, w = parts
    assert len(rows) == len(cols) == len(w)
    out = {(int(r), int(c)): float(x) for r, c, x in zip(rows, cols, w)}
    assert len(out) == len(rows), "duplicate edge"
    return out


def _km(a: str, b: str) -> float:
    return h3.great_circle_distance(META[a][:2], META[b][:2], unit="km")


def _block(a: str, b: str) -> int:
    return air.block_time_min(_km(a, b), META[a][2], META[b][2], CAL)


def _wait(a: str, b: str) -> int:
    return air.expected_wait_min(air.frequency_model(META[a][2], META[b][2], _km(a, b), CAL))


def test_flights_run_departure_side_to_arrival_side_with_the_border_on_the_route(idx):
    """Border control is charged on the flight, by the larger terminal of the
    pair, and only where the two countries are in different zones.

    Mutations performed and reverted, each -> red: drop the border line
    (ICN->NRT short by 45); `max(...)` -> `size1` (PUS->NRT charged the
    medium 35, not 45); `crosses_border` -> `country1 != country2` (CDG->FRA
    charged 45 inside Schengen); `airport_arr_index(dst)` -> `airport_index(dst)`
    (lands on the departure side, so no edge matches); remove the
    plausibility `continue` (PUS->SML appears, seven edges).
    """
    rejected: list = []
    edges = _edges(build._air_edges(idx, rejected_out=rejected))

    want = {
        ("ICN", "NRT"): _block("ICN", "NRT") + CAL.border_min["large"],
        ("ICN", "CDG"): _block("ICN", "CDG") + CAL.border_min["large"],
        ("NRT", "ICN"): _block("NRT", "ICN") + CAL.border_min["large"],
        ("PUS", "NRT"): _block("PUS", "NRT") + CAL.border_min["large"],
        ("PUS", "XSM"): _block("PUS", "XSM") + CAL.border_min["medium"],
        ("CDG", "FRA"): _block("CDG", "FRA"),
    }
    assert CAL.border_min["large"] != CAL.border_min["medium"], "fixture cannot tell sizes apart"
    assert edges == {(idx.airport_index(a), idx.airport_arr_index(b)): float(w)
                     for (a, b), w in want.items()}
    assert [(s, d) for s, d, _ in rejected] == [("PUS", "SML")]


def test_access_enters_on_the_departure_side_and_leaves_from_the_arrival_side(idx):
    """Two edges per airport: cell -> departure node at the processing time,
    arrival node -> cell at the disembark time, each by the airport's own
    size. The reverse of either would let a traveller walk out through
    security or board straight off an arriving aircraft.

    Mutations performed and reverted, each -> red: swap rows and cols on the
    access edge (cell <- departure); `processing_min` -> `disembark_min` on
    the way in; the size looked up for `idx.airports[0]` for every airport.
    """
    edges = _edges(build._access_edges(idx))
    assert len(edges) == 2 * len(AIRPORTS)
    for iata, _, _, size, _ in AIRPORTS:
        cell = idx.airport_cell_index(iata)
        dep, arr = idx.airport_index(iata), idx.airport_arr_index(iata)
        assert edges[(cell, dep)] == CAL.processing_min[size], iata
        assert edges[(arr, cell)] == CAL.disembark_min[size], iata
        assert (dep, cell) not in edges and (cell, arr) not in edges, iata


def test_a_connection_costs_the_larger_of_mct_and_the_wait_and_needs_a_departure(idx):
    """arrival -> departure inside one airport, at max(MCT, median onward
    wait) -- never their sum, which would charge the same minutes twice --
    and only where something departs. Implausible pairs, which never become
    flights, must not shape the wait either.

    The fixture has both regimes: NRT's one onward service (to ICN) is
    frequent, so its minimum connection time dominates; ICN's median sits
    between a frequent Tokyo service and a thin Paris one, far above its MCT.

    Mutations performed and reverted, each -> red: `max` -> sum (every
    weight high); `max` -> `min` (ICN at its MCT); replace `if not onward:
    continue` with a zero wait (FRA, XSM and SML get a connection); drop the
    plausibility `continue` (PUS's median takes the SML pair in);
    `idx.airport_index` and `airport_arr_index` swapped (departure -> arrival).
    """
    edges = _edges(build._transfer_edges(idx))

    nrt_wait = _wait("NRT", "ICN")
    icn_wait = float(np.median([_wait("ICN", "NRT"), _wait("ICN", "CDG")]))
    assert nrt_wait < CAL.connection_min["large"] < icn_wait, "fixture lost a regime"

    want = {
        "ICN": icn_wait,
        "NRT": CAL.connection_min["large"],
        "PUS": max(CAL.connection_min["medium"],
                   float(np.median([_wait("PUS", "NRT"), _wait("PUS", "XSM")]))),
        "CDG": max(CAL.connection_min["large"], float(_wait("CDG", "FRA"))),
    }
    assert edges == {(idx.airport_arr_index(a), idx.airport_index(a)): float(w)
                     for a, w in want.items()}
    # FRA, XSM and SML have nothing (plausible) departing: no connection at all.


def test_a_flight_is_charged_by_the_zone_its_passengers_actually_enter(monkeypatch):
    """A15's corrected memberships, through the flight edge itself: the Isle
    of Man is in the Common Travel Area (no border to Heathrow), Ercan is the
    north's airport whatever OurAirports files it under (a border to Larnaca),
    and Réunion is outside Schengen with its check at Paris (a border).

    Mutations performed and reverted, each -> red: drop "IM" from the CTA
    (IOM->LHR charged); call `crosses_border` on the raw OurAirports countries
    (ECN->LCA free); add "RE" to Schengen (CDG->RUN free).
    """
    apts = [("IOM", 54.0833, -4.6239, "medium", "IM"),
            ("LHR", 51.4706, -0.4619, "large", "GB"),
            ("ECN", 35.1547, 33.4961, "medium", "CY"),
            ("LCA", 34.8751, 33.6249, "medium", "CY"),
            ("CDG", 49.0097, 2.5479, "large", "FR"),
            ("RUN", -20.8871, 55.5103, "medium", "RE")]
    pairs = [("IOM", "LHR"), ("ECN", "LCA"), ("CDG", "RUN")]
    monkeypatch.setattr(build.airports, "scheduled_airports", lambda: pl.DataFrame(
        apts, schema=["iata", "lat", "lon", "size", "country"], orient="row"))
    monkeypatch.setattr(build.routes, "route_network", lambda: pl.DataFrame(
        pairs, schema=["src", "dst"], orient="row"))
    cells = [h3.latlng_to_cell(lat, lon, config.SOLVE_RES) for _, lat, lon, _, _ in apts]
    iatas = [a[0] for a in apts]
    small = NodeIndex(cells=cells, airports=iatas,
                      _cell_pos={c: i for i, c in enumerate(cells)},
                      _airport_pos={a: len(cells) + i for i, a in enumerate(iatas)},
                      _airport_cell={a: i for i, a in enumerate(iatas)})
    meta = {a[0]: a[1:] for a in apts}

    def block(a, b):
        km = h3.great_circle_distance(meta[a][:2], meta[b][:2], unit="km")
        return air.block_time_min(km, meta[a][2], meta[b][2], CAL)

    edges = _edges(build._air_edges(small))
    want = {("IOM", "LHR"): block("IOM", "LHR"),
            ("ECN", "LCA"): block("ECN", "LCA") + CAL.border_min["medium"],
            ("CDG", "RUN"): block("CDG", "RUN") + CAL.border_min["large"]}
    assert edges == {(small.airport_index(a), small.airport_arr_index(b)): float(w)
                     for (a, b), w in want.items()}
