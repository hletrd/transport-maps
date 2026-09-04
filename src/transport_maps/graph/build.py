"""Assemble the multi-modal graph as a scipy CSR matrix."""

import logging

import h3
import numpy as np
import scipy.sparse as sp

from transport_maps.graph import air, ground, transfers
from transport_maps.graph.nodes import NodeIndex
from transport_maps.sources import airports, routes

logger = logging.getLogger(__name__)

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

# A route pair naming an airport that never made it into the node index (see
# nodes.MAX_DROPPED_AIRPORT_FRACTION) cannot become an edge. 124 of 68,152
# directed pairs today (0.18%), all downstream of the 25 dropped airports.
# Unbounded, a land-mask regression would silently delete the air network one
# pair at a time while every other gate stayed green.
MAX_UNKNOWN_PAIR_FRACTION = 0.02


def is_geographically_plausible(distance_km: float, size1: str, size2: str) -> bool:
    """Reject ultra-long-haul pairs where neither endpoint is a large airport."""
    if distance_km <= IMPLAUSIBLE_LONGHAUL_KM:
        return True
    return size1 == "large" or size2 == "large"


def _air_edges(
    idx: NodeIndex,
    rejected_out: list[tuple[str, str, float]] | None = None,
    unknown_out: list[tuple[str, str]] | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Directed flight edges. Pairs failing `is_geographically_plausible` are
    dropped and, if `rejected_out` is given, appended to it as (src, dst, km)
    so a caller (or a test) can inspect exactly what was rejected rather than
    only reading a log line.

    Pairs naming an airport absent from the node index are dropped too, and
    collected into `unknown_out` on the same principle -- that skip used to be
    silent and unbounded.
    """
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
    unknown: list[tuple[str, str]] = []
    net = routes.route_network()
    for src, dst in zip(net["src"], net["dst"]):
        if src not in known or dst not in known:
            unknown.append((src, dst))
            continue
        (lat1, lon1, size1) = meta[src]
        (lat2, lon2, size2) = meta[dst]
        d = h3.great_circle_distance((lat1, lon1), (lat2, lon2), unit="km")
        if not is_geographically_plausible(d, size1, size2):
            rejected.append((src, dst, d))
            continue
        block = air.block_time_min(d, size1, size2, cal)
        wait = air.expected_wait_min(air.frequency_model(size1, size2, d, cal))
        # Minimum connection time at the departure airport. This double-counts
        # slightly against access_min on a journey's very first hop (that leg
        # was never a connection), but a per-edge model can't distinguish "first
        # hop" from "connecting hop" without knowing the full path, so the brief
        # accepts the small overcount everywhere in exchange for realistic
        # connections on every later hop.
        conn = transfers.connection_min(size1, cal)
        # The design spec charges the air->air TRANSFER as max(MCT, headway/2),
        # not their sum: if flights are frequent, the wait is short and MCT
        # dominates; if flights are rare, the headway/2 wait already exceeds
        # MCT on its own, and adding MCT on top of it double-charges time
        # already spent waiting. The two forms agree on busy routes (wait is
        # small either way) and diverge on low-frequency ones, where a sum
        # overcounts by up to the smaller of the two terms.
        transfer = max(wait, conn)
        rows.append(idx.airport_index(src))
        cols.append(idx.airport_index(dst))
        minutes.append(float(block + transfer))

    if rejected:
        detail = ", ".join(f"{s}->{d} ({km:.0f} km)" for s, d, km in rejected)
        logger.warning(
            "rejected %d geographically implausible route(s) (>%.0f km, neither endpoint large): %s",
            len(rejected), IMPLAUSIBLE_LONGHAUL_KM, detail,
        )
    if rejected_out is not None:
        rejected_out.extend(rejected)

    if unknown:
        logger.warning(
            "dropped %d of %d route pair(s) naming an airport absent from the node "
            "index (%s%s)",
            len(unknown), len(net), ", ".join(f"{s}->{d}" for s, d in unknown[:10]),
            ", ..." if len(unknown) > 10 else "",
        )
    limit = MAX_UNKNOWN_PAIR_FRACTION * len(net)
    if len(unknown) > limit:
        raise RuntimeError(
            f"{len(unknown)} of {len(net)} route pairs name an airport absent from "
            f"the node index, above the {MAX_UNKNOWN_PAIR_FRACTION:.0%} bound "
            f"({limit:.0f}); the land mask or the airport table has regressed"
        )
    if unknown_out is not None:
        unknown_out.extend(unknown)

    return (
        np.asarray(rows, dtype=np.int64),
        np.asarray(cols, dtype=np.int64),
        np.asarray(minutes, dtype=np.float64),
    )


def _access_edges(idx: NodeIndex) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    cal = air.load_calibration()
    apts = airports.scheduled_airports()
    size_by_iata = dict(zip(apts["iata"], apts["size"]))

    rows: list[int] = []
    cols: list[int] = []
    minutes: list[float] = []
    for iata in idx.airports:
        cell = idx.airport_cell_index(iata)
        node = idx.airport_index(iata)
        size = size_by_iata[iata]
        # The graph is built once, before any particular origin is known, so
        # whether a given trip through this airport is domestic or
        # international can't be decided here. Use the international
        # variant unconditionally: it is the conservative (longer) choice,
        # and correct for the majority of hops on a global map, which are
        # long-haul international connections.
        access = transfers.access_min(size, True, cal)
        egress = transfers.egress_min(size, True, cal)
        rows.append(cell); cols.append(node); minutes.append(access)
        rows.append(node); cols.append(cell); minutes.append(egress)
    return (
        np.asarray(rows, dtype=np.int64),
        np.asarray(cols, dtype=np.int64),
        np.asarray(minutes, dtype=np.float64),
    )


def build_graph(
    idx: NodeIndex,
    rejected_air_pairs: list[tuple[str, str, float]] | None = None,
    unknown_airport_pairs: list[tuple[str, str]] | None = None,
) -> sp.csr_matrix:
    """Assemble the graph. Pass a list as `rejected_air_pairs` to have it filled
    with the (src, dst, km) triples `is_geographically_plausible` dropped, and
    one as `unknown_airport_pairs` for those naming an airport the node index
    does not hold.
    """
    parts = [
        ground.hex_edges(idx),
        _air_edges(idx, rejected_air_pairs, unknown_airport_pairs),
        _access_edges(idx),
    ]
    rows = np.concatenate([p[0] for p in parts])
    cols = np.concatenate([p[1] for p in parts])
    data = np.concatenate([p[2] for p in parts])

    if not np.isfinite(data).all() or (data <= 0).any():
        raise RuntimeError("graph contains non-positive or non-finite edge weights")

    # coo_matrix SUMS duplicate (row, col) entries rather than taking the
    # minimum -- two edges between the same pair of nodes would silently
    # become one edge weighing more than either original, and Dijkstra would
    # never see the cheaper of the two. No part builds a duplicate today, but
    # nothing enforces that either, and Task 9's future station edges are the
    # obvious way one could sneak in later. Encoding (row, col) as a single
    # int64 key keeps this an O(n log n) check instead of an O(n^2) one.
    keys = rows.astype(np.int64) * idx.n + cols.astype(np.int64)
    if keys.size != np.unique(keys).size:
        raise RuntimeError(
            "graph edge list contains duplicate (row, col) pairs; coo_matrix would "
            "silently sum their weights instead of keeping the cheaper edge"
        )

    coo = sp.coo_matrix((data, (rows, cols)), shape=(idx.n, idx.n))
    return coo.tocsr()
