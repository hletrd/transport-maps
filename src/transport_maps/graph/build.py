"""Assemble the multi-modal graph as a scipy CSR matrix."""

import logging

import h3
import numpy as np
import polars as pl
import scipy.sparse as sp

from transport_maps import config
from transport_maps.graph import air, ground, rail, transfers
from transport_maps.graph.nodes import NodeIndex
from transport_maps.sources import airports, osm, routes

logger = logging.getLogger(__name__)

# Border time scales with the larger terminal of the pair.
_SIZE_RANK = {"small": 0, "medium": 1, "large": 2}

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
        iata: (lat, lon, size, country)
        for iata, lat, lon, size, country in zip(
            apts["iata"], apts["lat"], apts["lon"], apts["size"], apts["country"]
        )
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
        (lat1, lon1, size1, country1) = meta[src]
        (lat2, lon2, size2, country2) = meta[dst]
        d = h3.great_circle_distance((lat1, lon1), (lat2, lon2), unit="km")
        if not is_geographically_plausible(d, size1, size2):
            rejected.append((src, dst, d))
            continue
        block = air.block_time_min(d, size1, size2, cal)
        # Border control is a property of the ROUTE, not of either airport, so
        # it is charged here where both countries are known. Schengen and the
        # Ireland/UK Common Travel Area count as single zones: those flights
        # cross a national border but no passport desk.
        if transfers.crosses_border(country1, country2):
            block += transfers.border_min(max(size1, size2, key=_SIZE_RANK.get), cal)
        # The flight edge carries block time ONLY. Waiting is charged on the
        # connection edge instead (see _transfer_edges), because a traveller
        # plans their first departure but cannot choose when a connecting
        # service leaves. That also removes the connection penalty this edge
        # used to add to every journey's first flight.
        rows.append(idx.airport_index(src))
        cols.append(idx.airport_arr_index(dst))
        minutes.append(float(block))

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
        # Only trip-independent time belongs here. Border control depends on
        # where the flight goes, which this edge cannot know, so it is charged
        # on the flight edge instead -- see _air_edges.
        access = transfers.processing_min(size, cal)
        egress = transfers.disembark_min(size, cal)
        # Enter on the departure side, leave from the arrival side.
        rows.append(cell); cols.append(node); minutes.append(access)
        rows.append(idx.airport_arr_index(iata)); cols.append(cell); minutes.append(egress)
    return (
        np.asarray(rows, dtype=np.int64),
        np.asarray(cols, dtype=np.int64),
        np.asarray(minutes, dtype=np.float64),
    )


def _transfer_edges(idx: NodeIndex) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Arrival -> departure within one airport: the cost of connecting.

    This edge is the only place a connection is charged, so a journey's first
    flight never pays one. It is also where waiting lives: a traveller times
    their own first departure, but must take whatever onward service exists,
    so the wait is the expected headway of THIS airport's outbound routes.

    Cost is max(MCT, wait), not their sum -- when services are frequent the
    minimum connection time dominates, and when they are rare the wait already
    exceeds it, so adding both would charge the same minutes twice.
    """
    cal = air.load_calibration()
    apts = airports.scheduled_airports()
    meta = {
        iata: (lat, lon, size)
        for iata, lat, lon, size in zip(apts["iata"], apts["lat"], apts["lon"], apts["size"])
    }
    known = set(idx.airports)

    waits: dict[str, list[float]] = {}
    net = routes.route_network()
    for src, dst in zip(net["src"], net["dst"]):
        if src not in known or dst not in known:
            continue
        (lat1, lon1, size1) = meta[src]
        (lat2, lon2, size2) = meta[dst]
        d = h3.great_circle_distance((lat1, lon1), (lat2, lon2), unit="km")
        if not is_geographically_plausible(d, size1, size2):
            continue
        waits.setdefault(src, []).append(
            float(air.expected_wait_min(air.frequency_model(size1, size2, d, cal)))
        )

    rows: list[int] = []
    cols: list[int] = []
    minutes: list[float] = []
    for iata in idx.airports:
        onward = waits.get(iata)
        if not onward:
            continue  # nothing departs here, so no connection is possible
        typical = float(np.median(onward))
        conn = transfers.connection_min(meta[iata][2], cal)
        rows.append(idx.airport_arr_index(iata))
        cols.append(idx.airport_index(iata))
        minutes.append(max(conn, typical))
    return (
        np.asarray(rows, dtype=np.int64),
        np.asarray(cols, dtype=np.int64),
        np.asarray(minutes, dtype=np.float64),
    )


def _border_rules(idx: NodeIndex):
    """Country and immigration zone per cell, plus the crossing charge.

    Ground edges applied these from the start; rail and ferry did not, and an
    OSM ferry way across the Yellow Sea carried travellers from Seoul into
    North Korea with every land border sealed. The same two rules -- cut a
    closed pair, charge a zone change -- now apply to every surface edge.
    """
    from transport_maps.sources import countries

    country = countries.cell_country(idx.cells)
    zone = np.array([transfers.immigration_zone(countries.iso2(c)) if c else ""
                     for c in country])
    return country, zone, ground._land_border_min(), countries.is_closed


def _rail_edges(idx: NodeIndex, routes, cal) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Station-to-station rides, plus the cell edges that board and alight.

    Rides are symmetrised. OSM usually models the two directions of a service
    as separate relations, but not always, and a line present in only one
    direction would otherwise be a one-way railway. Where both directions do
    exist the pair is collapsed to the faster of the two, which also keeps the
    edge list free of the duplicates `build_graph` refuses.
    """
    e = rail.ride_edges(routes, cal)
    known = set(idx.stations)
    e = e.filter(pl.col("from_station").is_in(known) & pl.col("to_station").is_in(known))

    lo = pl.min_horizontal("from_station", "to_station")
    hi = pl.max_horizontal("from_station", "to_station")
    undirected = (e.with_columns(lo.alias("a"), hi.alias("b"))
                   .group_by("a", "b").agg(pl.col("minutes").min())
                   .filter(pl.col("a") != pl.col("b")))

    country, zone, crossing, is_closed = _border_rules(idx)
    a_l, b_l, m_l = [], [], []
    cut = 0
    for sa, sb, mins in zip(undirected["a"], undirected["b"], undirected["minutes"]):
        ca, cb = idx.station_cell_index(sa), idx.station_cell_index(sb)
        if is_closed(country[ca], country[cb]):
            cut += 1
            continue
        if zone[ca] and zone[cb] and zone[ca] != zone[cb]:
            mins = float(mins) + crossing
        a_l.append(idx.station_index(sa)); b_l.append(idx.station_index(sb)); m_l.append(float(mins))
    if cut:
        logger.info("%d rail segment(s) cut at closed land borders", cut)
    a = np.array(a_l, dtype=np.int64); b = np.array(b_l, dtype=np.int64); m = np.array(m_l, dtype=np.float64)

    # Boarding is charged on the way IN to the network and alighting on the way
    # out, so riding through an intermediate station costs only running time.
    s = np.array([idx.station_index(x) for x in idx.stations], dtype=np.int64)
    c = np.array([idx.station_cell_index(x) for x in idx.stations], dtype=np.int64)

    rows = np.concatenate([a, b, c, s])
    cols = np.concatenate([b, a, s, c])
    data = np.concatenate([m, m,
                           np.full(s.size, cal.boarding_min, dtype=float),
                           np.full(s.size, cal.alighting_min, dtype=float)])
    return rows, cols, data


def _ferry_edges(idx: NodeIndex, links, cal) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Ferry crossings as direct cell-to-cell edges, both ways.

    Ferries get no node of their own: unlike rail you almost never chain two,
    so there is no through-journey whose terminal time would be double-charged,
    and a node per crossing would add tens of thousands of nodes to no end.
    """
    country, zone, crossing, is_closed = _border_rules(idx)
    a_cells, b_cells, minutes = [], [], []
    cut = 0
    for row in links.iter_rows(named=True):
        km = float(ground.haversine_km(
            np.array([[row["from_lat"], row["from_lon"]]]),
            np.array([[row["to_lat"], row["to_lon"]]]))[0])
        if not (osm.MIN_FERRY_KM <= km <= osm.MAX_FERRY_KM):
            continue
        u = idx.try_cell_index(idx.cell_at(row["from_lat"], row["from_lon"]))
        v = idx.try_cell_index(idx.cell_at(row["to_lat"], row["to_lon"]))
        # Same cell means the crossing is shorter than the grid can see; a
        # self-loop would be a zero-cost edge Dijkstra could sit on.
        if u is None or v is None or u == v:
            continue
        # Cells the ground network already joins are skipped. At resolution 5 a
        # crossing between neighbours is a river ferry spanning ~8 km, which you
        # can also drive around, and emitting it duplicates a (row, col) pair
        # that coo_matrix would silently SUM -- making the shared edge cost the
        # road time PLUS the sailing rather than the cheaper of the two.
        if idx.cells[v] in h3.grid_disk(idx.cells[u], 1):
            continue
        # A sailing into a sealed country is no more open than a road.
        if is_closed(country[u], country[v]):
            cut += 1
            continue
        extra = crossing if (zone[u] and zone[v] and zone[u] != zone[v]) else 0.0
        a_cells.append(u)
        b_cells.append(v)
        minutes.append(60.0 * km / cal.speed_kmh + cal.terminal_min + extra)

    if cut:
        logger.info("%d ferry crossing(s) cut at closed borders", cut)
    if not a_cells:
        empty_i = np.array([], dtype=np.int64)
        return empty_i, empty_i, np.array([], dtype=np.float64)

    # Several ferry ways can join the same pair of cells; keep the quickest,
    # or build_graph refuses the duplicate (row, col) pair outright.
    best: dict[tuple[int, int], float] = {}
    for u, v, m in zip(a_cells, b_cells, minutes):
        for pair in ((u, v), (v, u)):
            if m < best.get(pair, float("inf")):
                best[pair] = m

    rows = np.fromiter((p[0] for p in best), dtype=np.int64, count=len(best))
    cols = np.fromiter((p[1] for p in best), dtype=np.int64, count=len(best))
    data = np.fromiter(best.values(), dtype=np.float64, count=len(best))
    return rows, cols, data


def build_graph(
    idx: NodeIndex,
    rejected_air_pairs: list[tuple[str, str, float]] | None = None,
    unknown_airport_pairs: list[tuple[str, str]] | None = None,
    rail_routes=None,
    ferry_links=None,
) -> sp.csr_matrix:
    """Assemble the graph. Pass a list as `rejected_air_pairs` to have it filled
    with the (src, dst, km) triples `is_geographically_plausible` dropped, and
    one as `unknown_airport_pairs` for those naming an airport the node index
    does not hold.
    """
    # Checked before any edge is assembled: this is a caller mistake, and
    # discovering it after several minutes of graph building helps nobody.
    if idx.has_rail and rail_routes is None:
        raise ValueError(
            "the node index holds stations but no rail_routes frame was passed; "
            "the station nodes would sit unreachable in the graph"
        )

    parts = [
        ground.hex_edges(idx),
        _air_edges(idx, rejected_air_pairs, unknown_airport_pairs),
        _access_edges(idx),
        _transfer_edges(idx),
    ]
    if idx.has_rail:
        parts.append(_rail_edges(idx, rail_routes, rail.load_rail_calibration()))
    if ferry_links is not None and len(ferry_links):
        parts.append(_ferry_edges(idx, ferry_links, rail.load_ferry_calibration()))
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
