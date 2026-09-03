"""Assemble the multi-modal graph as a scipy CSR matrix."""

import h3
import numpy as np
import scipy.sparse as sp

from transport_maps.graph import air, ground
from transport_maps.graph.nodes import NodeIndex
from transport_maps.sources import airports, routes

# Phase A constants, split by domestic/international in Task 12.
AIRPORT_ACCESS_MIN = 75.0   # arrive, check in, clear security
AIRPORT_EGRESS_MIN = 45.0   # deplane, immigration, baggage

# The longest real nonstop flight is about 15,300 km (e.g. Singapore-New York
# JFK), and no scheduled route beyond this distance is flown without a large
# hub at one end -- small/medium equipment can't cover it. This catches
# Wikidata P238 resolution errors that fabricate a route to the wrong tiny
# airfield (e.g. Lasondre_Airport, which has no IATA code of its own,
# resolving to LSE -- La Crosse Regional Airport, Wisconsin -- inventing an
# Indonesia-to-Wisconsin route). It does NOT touch legitimate long-haul pairs
# that Wikipedia lists as a single "route" even though they're flown with a
# stop, e.g. SYD->LHR, PEK->GRU, NOU->CDG: those always have a large airport
# at one or both ends.
IMPLAUSIBLE_LONGHAUL_KM = 8000.0


def is_geographically_plausible(distance_km: float, size1: str, size2: str) -> bool:
    """Reject ultra-long-haul pairs where neither endpoint is a large airport."""
    if distance_km <= IMPLAUSIBLE_LONGHAUL_KM:
        return True
    return size1 == "large" or size2 == "large"


def _air_edges(idx: NodeIndex) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    cal = air.load_calibration()
    apts = airports.scheduled_airports()
    meta = {
        iata: (lat, lon, size)
        for iata, lat, lon, size in zip(apts["iata"], apts["lat"], apts["lon"], apts["size"])
    }
    known = set(idx.airports)

    rows: list[int] = []
    cols: list[int] = []
    minutes: list[float] = []
    rejected: list[tuple[str, str, float]] = []
    net = routes.route_network()
    for src, dst in zip(net["src"], net["dst"]):
        if src not in known or dst not in known:
            continue
        (lat1, lon1, size1) = meta[src]
        (lat2, lon2, size2) = meta[dst]
        d = h3.great_circle_distance((lat1, lon1), (lat2, lon2), unit="km")
        if not is_geographically_plausible(d, size1, size2):
            rejected.append((src, dst, d))
            continue
        block = air.block_time_min(d, size1, size2, cal)
        wait = air.expected_wait_min(air.frequency_model(size1, size2, d, cal))
        rows.append(idx.airport_index(src))
        cols.append(idx.airport_index(dst))
        minutes.append(float(block + wait))

    if rejected:
        detail = ", ".join(f"{s}->{d} ({km:.0f} km)" for s, d, km in rejected)
        print(
            f"build: rejected {len(rejected)} geographically implausible route(s) "
            f"(>{IMPLAUSIBLE_LONGHAUL_KM:.0f} km, neither endpoint large): {detail}"
        )

    return (
        np.asarray(rows, dtype=np.int64),
        np.asarray(cols, dtype=np.int64),
        np.asarray(minutes, dtype=np.float64),
    )


def _access_edges(idx: NodeIndex) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    rows: list[int] = []
    cols: list[int] = []
    minutes: list[float] = []
    for iata in idx.airports:
        cell = idx.airport_cell_index(iata)
        node = idx.airport_index(iata)
        rows.append(cell); cols.append(node); minutes.append(AIRPORT_ACCESS_MIN)
        rows.append(node); cols.append(cell); minutes.append(AIRPORT_EGRESS_MIN)
    return (
        np.asarray(rows, dtype=np.int64),
        np.asarray(cols, dtype=np.int64),
        np.asarray(minutes, dtype=np.float64),
    )


def build_graph(idx: NodeIndex) -> sp.csr_matrix:
    parts = [ground.hex_edges(idx), _air_edges(idx), _access_edges(idx)]
    rows = np.concatenate([p[0] for p in parts])
    cols = np.concatenate([p[1] for p in parts])
    data = np.concatenate([p[2] for p in parts])

    if not np.isfinite(data).all() or (data <= 0).any():
        raise RuntimeError("graph contains non-positive or non-finite edge weights")

    coo = sp.coo_matrix((data, (rows, cols)), shape=(idx.n, idx.n))
    return coo.tocsr()
