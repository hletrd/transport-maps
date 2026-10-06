"""Assemble the multi-modal graph as a scipy CSR matrix."""

import logging

import h3
import numpy as np
import polars as pl
import scipy.sparse as sp

from transport_maps.graph import air, ferry, ground, rail, refine, transfers
from transport_maps.graph.nodes import NodeIndex
from transport_maps.sources import airports, routes

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
# directed pairs (0.18%) when last measured, all downstream of the airports
# dropped then. That count was 25; at res 6 it is 12 of 4,008 (re-measured
# 2026-10-02, see graph/nodes.py), and the pair figure has not been re-taken
# since, so read it as an order of magnitude.
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

    Border control is paid once per AIRSIDE journey that leaves its
    immigration zone, not once per flight (A15). Seoul -> Narita -> Frankfurt
    passes emigration at Incheon and immigration at Frankfurt; at Narita the
    traveller never leaves the transit area. Charging every zone-crossing
    flight made that journey pay 45 + 45 minutes. Whether a border is still
    owed depends on the journey so far, which one node per airport cannot
    remember, so every airport has its two nodes twice -- a DOMESTIC layer
    (`airport_index`, `airport_arr_index`: nothing paid yet on this airside
    journey) and an INTERNATIONAL one (`airport_intl_index`,
    `airport_intl_arr_index`: the border has been paid). The edges:

        cell -> A_dep              processing (_access_edges)
        A_dep -> B_arr             block time; A and B in one zone
        A_dep -> B_intl_arr        block time + border_min; the first crossing
        A_intl_dep -> B_intl_arr   block time, whatever the zones: already paid
        B_arr -> B_dep             connection (_transfer_edges)
        B_intl_arr -> B_intl_dep   connection, airside transit
        B_intl_arr -> B_dep        connection where B's zone has no airside
                                   transit (transfers.NO_AIRSIDE_TRANSIT): the
                                   traveller is admitted to B's zone, so the
                                   next crossing is a new one
        B_arr -> cell              disembark (_access_edges)
        B_intl_arr -> cell         disembark: leaving the airport is entering
                                   the zone, and that was paid on the way in

    So the border is charged by the first flight that leaves the zone the
    traveller went airside in, at the larger terminal of THAT flight (exactly
    today's figure for a nonstop flight), and not again until the traveller
    goes landside: a later journey from a cell starts in the domestic layer,
    and a landside connection -- out through the arrival hall and back in --
    is one. A journey that flies out of its zone and back into it pays once,
    which is right too: it does pass emigration and immigration. The
    international departure node of a no-transit airport has no flights,
    because nothing reaches it.
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
    # The zone whose control each airport's passengers pass: OurAirports'
    # country unless transfers.AIRPORT_COUNTRY corrects it (Ercan).
    zone = {iata: transfers.immigration_zone(transfers.airport_country(iata, m[3]))
            for iata, m in meta.items()}

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
        (lat1, lon1, size1, _) = meta[src]
        (lat2, lon2, size2, _) = meta[dst]
        d = h3.great_circle_distance((lat1, lon1), (lat2, lon2), unit="km")
        if not is_geographically_plausible(d, size1, size2):
            rejected.append((src, dst, d))
            continue
        block = float(air.block_time_min(d, size1, size2, cal))
        # The flight edge carries block time ONLY, plus the border on a first
        # crossing. Waiting is charged on the connection edge instead (see
        # _transfer_edges), because a traveller plans their first departure
        # but cannot choose when a connecting service leaves. That also
        # removes the connection penalty this edge used to add to every
        # journey's first flight.
        #
        # Border control is charged where both zones are known. Schengen and
        # the Common Travel Area count as single zones: those flights cross a
        # national border but no passport desk.
        if zone[src] != zone[dst]:
            rows.append(idx.airport_index(src))
            cols.append(idx.airport_intl_arr_index(dst))
            minutes.append(block + transfers.border_min(max(size1, size2, key=_SIZE_RANK.get), cal))
        else:
            rows.append(idx.airport_index(src))
            cols.append(idx.airport_arr_index(dst))
            minutes.append(block)
        # The same flight for a traveller who has paid already.
        if transfers.airside_transit(zone[src]):
            rows.append(idx.airport_intl_index(src))
            cols.append(idx.airport_intl_arr_index(dst))
            minutes.append(block)

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
        # Enter on the departure side, leave from the arrival side -- of
        # either layer: a traveller from abroad paid the border on the flight
        # that crossed, so walking out costs what it costs anyone. Nobody
        # enters the international layer from the street.
        rows.append(cell); cols.append(node); minutes.append(access)
        rows.append(idx.airport_arr_index(iata)); cols.append(cell); minutes.append(egress)
        rows.append(idx.airport_intl_arr_index(iata)); cols.append(cell); minutes.append(egress)
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

    Each layer connects within itself (see _air_edges): a traveller who has
    paid the border stays paid through an airside transit. Where the zone has
    no airside transit, the international arrival connects to the DOMESTIC
    departure instead -- the traveller has been admitted, and the next
    crossing is charged again, as it is today. The connection costs the same
    either way: admission is what the border charge already paid for.
    """
    cal = air.load_calibration()
    apts = airports.scheduled_airports()
    meta = {
        iata: (lat, lon, size)
        for iata, lat, lon, size in zip(apts["iata"], apts["lat"], apts["lon"], apts["size"])
    }
    zone = {iata: transfers.immigration_zone(transfers.airport_country(iata, c))
            for iata, c in zip(apts["iata"], apts["country"])}
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
        conn = max(transfers.connection_min(meta[iata][2], cal), typical)
        rows.append(idx.airport_arr_index(iata))
        cols.append(idx.airport_index(iata))
        minutes.append(conn)
        rows.append(idx.airport_intl_arr_index(iata))
        cols.append(idx.airport_intl_index(iata) if transfers.airside_transit(zone[iata])
                    else idx.airport_index(iata))
        minutes.append(conn)
    return (
        np.asarray(rows, dtype=np.int64),
        np.asarray(cols, dtype=np.int64),
        np.asarray(minutes, dtype=np.float64),
    )


def _border_rules(idx: NodeIndex, country=None, zone=None):
    """Country and immigration zone per cell, plus the crossing charge.

    Ground edges applied these from the start; rail and ferry did not, and an
    OSM ferry way across the Yellow Sea carried travellers from Seoul into
    North Korea with every land border sealed. The same two rules -- cut a
    closed pair, charge a zone change -- now apply to every surface edge.

    `build_graph` calls this ONCE and hands the result to every edge builder.
    Each builder used to call it for itself -- spans, rail and ferry, beside
    hex_edges' own copy -- and every call materialised a ~10 M-string country
    array and walked it for zones: ~2.4 GB of churn in the parent before the
    fork (PR-5). `country` and `zone` are taken from the caller when it has
    them (cli._build_all_locked does).
    """
    from transport_maps.sources import countries

    if country is None:
        country = countries.cell_country(idx.cells)
    if zone is None:
        zone = ground.cell_zones(country)
    return country, zone, ground._land_border_min(), countries.is_closed


def _span_edges(idx: NodeIndex, rules=None) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Road bridges and tunnels long enough to cross a water cell (graph/landmass).

    Their two ends were never grid neighbours, so hex_edges had no edge for
    them and the Great Belt, the Oresund Bridge and the Confederation Bridge
    did not exist in the graph. The same two border rules as every other
    surface edge: a closed pair is cut, a change of immigration zone charged.
    """
    spans = getattr(idx, "spans", None) or {}
    if not spans:
        empty = np.zeros(0, dtype=np.int64)
        return empty, empty, np.zeros(0, dtype=np.float64)
    country, zone, crossing, is_closed = rules or _border_rules(idx)
    rows, cols, mins = [], [], []
    for (u, v), minutes in sorted(spans.items()):
        if is_closed(country[u], country[v]):
            continue
        rows.append(u)
        cols.append(v)
        mins.append(minutes + (crossing if zone[u] and zone[v] and zone[u] != zone[v] else 0.0))
    return (np.asarray(rows, dtype=np.int64), np.asarray(cols, dtype=np.int64),
            np.asarray(mins, dtype=np.float64))


def _rail_edges(idx: NodeIndex, routes, cal, rules=None) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
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

    country, zone, crossing, is_closed = rules or _border_rules(idx)
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


# The share of parsed crossings that may vanish into the drop reasons below
# before the build refuses. Measured today: 30,629 links parsed, 4,643 edges
# emitted -- but 50.8% of those are under MIN_FERRY_KM (river crossings inside
# one cell) and another large share duplicate a ground edge, both of which are
# correct refusals. The bound is on the ONE reason that is a data defect rather
# than a modelling decision: an endpoint whose cell is not in the land mask.
# 1,872 in-window links (12.4%) are lost that way today, which is why the
# bound is not tighter; a land-mask regression that pushed it much past this
# would silently delete the ferry network one island at a time.
MAX_OFF_MASK_FERRY_FRACTION = 0.20
# ...and a fraction over a handful of links says nothing at all. Below this
# many in-window crossings the bound is not applied: a unit test with two
# fixtures, or a single regional extract, would otherwise trip a gate that
# exists to catch a global land-mask regression. The real build sees 15,080
# in-window crossings, so the bound is live where it matters.
MIN_FERRY_LINKS_TO_BOUND = 200


def _ferry_pair_refused(idx: NodeIndex, u: int, v: int, country, is_closed) -> str | None:
    """Why a ferry may not join cells `u` and `v`, or None if it may."""
    # Same cell means the crossing is shorter than the grid can see; a
    # self-loop would be a zero-cost edge Dijkstra could sit on.
    if u == v:
        return "both endpoints in one cell"
    # Cells the ground network already joins are skipped. A crossing
    # between neighbours is a river ferry a few kilometres long, which you
    # can also drive around, and emitting it duplicates a (row, col) pair
    # that coo_matrix would silently SUM -- making the shared edge cost the
    # road time PLUS the sailing rather than the cheaper of the two.
    # "Joins" is judged the way ground.hex_edges joins cells: a fine cell
    # and the unsplit base cell beyond its ring are adjacent too, which a
    # same-resolution grid_disk test can never see -- and a pair open
    # water severs is NOT joined, so its ferry is the only way across and
    # is kept. Judged by adjacency alone, Saipan-Tinian's phantom road was
    # the reason a real crossing there would have been thrown away.
    if refine.ground_joined(idx, u, v):
        return "duplicates a ground edge"
    # A sailing into a sealed country is no more open than a road.
    if is_closed(country[u], country[v]):
        return "closed border"
    return None


def _ferry_edges(idx: NodeIndex, links, cal,
                 dropped_out: dict[str, int] | None = None, rules=None
                 ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Ferry crossings as direct cell-to-cell edges, both ways.

    Ferries get no node of their own: unlike rail you almost never chain two,
    so there is no through-journey whose terminal time would be double-charged,
    and a node per crossing would add tens of thousands of nodes to no end.
    The wait, the sailing and the terminal time therefore all land on this one
    edge -- see `graph/ferry.crossing_min`.

    Every drop is COUNTED. Seven filters stand between a parsed link and an
    edge and only one of them used to be logged, so 1,872 crossings (12.4% of
    those in the plausible length window) disappeared because an endpoint's
    cell was absent from the land mask -- Sanya-Yongshu at 1,034 km,
    Donghae-Vladivostok at 570 km -- with nothing in the build log and no gate
    able to see it. `_air_edges` has counted its rejects since commit fcb4d2a;
    this is the same pattern one function further down.
    """
    country, zone, crossing, is_closed = rules or _border_rules(idx)
    a_cells, b_cells, minutes = [], [], []
    dropped = dropped_out if dropped_out is not None else {}
    cut = 0
    in_window = 0
    below_window_kept = 0
    for row in links.iter_rows(named=True):
        km = float(ground.haversine_km(
            np.array([[row["from_lat"], row["from_lon"]]]),
            np.array([[row["to_lat"], row["to_lon"]]]))[0])
        u = idx.try_cell_index(idx.cell_at(row["from_lat"], row["from_lon"]))
        v = idx.try_cell_index(idx.cell_at(row["to_lat"], row["to_lon"]))
        if not ferry.plausible_crossing(km):
            # The floor stands for "a river crossing inside one cell, or one
            # the road already makes". Between two cells open water severs it
            # is neither: it is the only way over. Sangtaedo to Jungtaedo is
            # 0.85 km and the first hop of the only line on to Hataedo and
            # Gageodo, which read "no route" from everywhere while it was
            # dropped here (2026-10-04: 54 such crossings worldwide). Kept
            # there and nowhere else; the in-window count and its off-mask
            # bound below are unchanged.
            if not (km < ferry.MIN_FERRY_KM and u is not None and v is not None
                    and u != v and not refine.ground_joined(idx, u, v)):
                dropped["outside length window"] = dropped.get("outside length window", 0) + 1
                continue
            below_window_kept += 1
        else:
            in_window += 1
        if u is None or v is None:
            dropped["endpoint off the land mask"] = dropped.get("endpoint off the land mask", 0) + 1
            continue
        # An end in a water-only straddler child is landed on every shore of
        # its strait as well as in the child itself (landmass.shore_landings):
        # Natural Earth's coast put Rupat's pier on Sumatra, so the Dumai ferry
        # joined Sumatra to itself. Every pair that passes becomes an edge;
        # the ones back to the shore the ferry starts from cost more than the
        # road, so only the crossing is ever taken. The child stays an option
        # so that this only ever adds a way across: measured from Seoul,
        # replacing it lost 22 cells that only its own landing reached.
        kept_any, first_reason = False, None
        for uu in dict.fromkeys((u, *idx.landings.get(u, ()))):
            for vv in dict.fromkeys((v, *idx.landings.get(v, ()))):
                reason = _ferry_pair_refused(idx, uu, vv, country, is_closed)
                if reason is not None:
                    first_reason = first_reason or reason
                    continue
                kept_any = True
                extra = crossing if (zone[uu] and zone[vv] and zone[uu] != zone[vv]) else 0.0
                a_cells.append(uu)
                b_cells.append(vv)
                minutes.append(ferry.crossing_min(
                    km, cal,
                    duration_min=row.get("duration_min"),
                    interval_min=row.get("interval_min"),
                    service_fraction=row.get("service_fraction") if row.get("service_fraction") is not None else 1.0,
                    extra=extra))
        if not kept_any:
            if first_reason == "closed border":
                cut += 1
            dropped[first_reason] = dropped.get(first_reason, 0) + 1

    if cut:
        logger.info("%d ferry crossing(s) cut at closed borders", cut)
    if below_window_kept:
        logger.info("%d ferry crossing(s) under %.0f km kept: open water severs their "
                    "two cells, so each is the only way across", below_window_kept,
                    ferry.MIN_FERRY_KM)
    if dropped:
        logger.info("ferry links dropped: %s",
                    ", ".join(f"{k} {v:,}" for k, v in sorted(dropped.items())))
    off_mask = dropped.get("endpoint off the land mask", 0)
    if in_window >= MIN_FERRY_LINKS_TO_BOUND and off_mask > MAX_OFF_MASK_FERRY_FRACTION * in_window:
        raise RuntimeError(
            f"{off_mask:,} of {in_window:,} ferry crossings in the plausible length "
            f"window ({off_mask / in_window:.1%}) have an endpoint whose cell is not in "
            f"the land mask, above the {MAX_OFF_MASK_FERRY_FRACTION:.0%} bound. Every one "
            "of them is an island or a port the map can no longer sail to, and the "
            "previous code dropped them silently."
        )
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
    exclude: str | None = None,
    speeds=None,
    country=None,
    zone=None,
) -> sp.csr_matrix:
    """Assemble the graph. Pass a list as `rejected_air_pairs` to have it filled
    with the (src, dst, km) triples `is_geographically_plausible` dropped, and
    one as `unknown_airport_pairs` for those naming an airport the node index
    does not hold.

    `speeds` (ground.cell_speed_kmh), `country` (countries.cell_country) and
    `zone` (ground.cell_zones) are computed here when not given; the build
    passes the ones it already holds, so each is derived once per build
    rather than once per edge builder (R5). Either way every builder sees the
    same arrays.

    `exclude` ("air", "ferry" or "rail") builds the graph of an exclusion
    variant (transport_maps.variants): that mode's edges are simply absent, so
    every route found is one that never uses it. Nothing else changes -- the
    same nodes, the same ground, the same calibration -- so a variant differs
    from the full map only where the excluded mode had been the fastest.
    """
    if exclude is not None and exclude not in ("air", "ferry", "rail"):
        raise ValueError(f"cannot exclude {exclude!r}")
    # Checked before any edge is assembled: this is a caller mistake, and
    # discovering it after several minutes of graph building helps nobody.
    if idx.has_rail and rail_routes is None and exclude != "rail":
        raise ValueError(
            "the node index holds stations but no rail_routes frame was passed; "
            "the station nodes would sit unreachable in the graph"
        )

    rules = _border_rules(idx, country, zone)
    parts = [
        ground.hex_edges(idx, speeds=speeds, country=rules[0], zone=rules[1]),
        _span_edges(idx, rules),
    ]
    if exclude != "air":
        parts += [_air_edges(idx, rejected_air_pairs, unknown_airport_pairs),
                  _access_edges(idx),
                  _transfer_edges(idx)]
    if idx.has_rail and exclude != "rail":
        parts.append(_rail_edges(idx, rail_routes, rail.load_rail_calibration(), rules))
    if ferry_links is not None and len(ferry_links) and exclude != "ferry":
        parts.append(_ferry_edges(idx, ferry_links, ferry.load_ferry_calibration(),
                                  rules=rules))
    rows = np.concatenate([p[0] for p in parts])
    cols = np.concatenate([p[1] for p in parts])
    data = np.concatenate([p[2] for p in parts])

    if not np.isfinite(data).all() or (data <= 0).any():
        raise RuntimeError("graph contains non-positive or non-finite edge weights")

    # coo_matrix SUMS duplicate (row, col) entries rather than taking the
    # minimum -- two edges between the same pair of nodes would silently
    # become one edge weighing more than either original, and Dijkstra would
    # never see the cheaper of the two. No part builds a duplicate today, but
    # nothing enforces that either, and the rail and ferry station edges
    # (_rail_edges, _ferry_edges) are the obvious way one could sneak in later.
    # Encoding (row, col) as a single
    # int64 key keeps this an O(n log n) check instead of an O(n^2) one.
    keys = rows.astype(np.int64) * idx.n + cols.astype(np.int64)
    if keys.size != np.unique(keys).size:
        raise RuntimeError(
            "graph edge list contains duplicate (row, col) pairs; coo_matrix would "
            "silently sum their weights instead of keeping the cheaper edge"
        )

    coo = sp.coo_matrix((data, (rows, cols)), shape=(idx.n, idx.n))
    return coo.tocsr()
