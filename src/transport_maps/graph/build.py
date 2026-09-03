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
    net = routes.route_network()
    for src, dst in zip(net["src"], net["dst"]):
        if src not in known or dst not in known:
            continue
        (lat1, lon1, size1) = meta[src]
        (lat2, lon2, size2) = meta[dst]
        d = h3.great_circle_distance((lat1, lon1), (lat2, lon2), unit="km")
        block = air.block_time_min(d, size1, size2, cal)
        wait = air.expected_wait_min(air.frequency_model(size1, size2, d, cal))
        rows.append(idx.airport_index(src))
        cols.append(idx.airport_index(dst))
        minutes.append(float(block + wait))

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
