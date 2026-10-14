"""What the track says that the route relations do not.

`sources/osm.py` builds rail from `type=route, route=train` relations: an
ordered stop list per service. Two things that list cannot carry, measured on
the rebuild-29 extracts (2026-10-14):

1. HOW FAST THE LINE IS. The relation's `service` tag picks a speed tier, and
   26.7% of relations carry none. Every one of the twenty Shinkansen relations
   in the Asia extract is untagged and was priced at the `default` tier's
   81.8 km/h. The ways the relation runs over say otherwise: 110,000 of Asia's
   987,000 `railway=rail` ways carry `highspeed=yes`, and 296,000 a
   `maxspeed`. `relation_profile` reads a relation's member ways for the share
   of its length that is high-speed track and the harmonic mean of the line
   speed over it.

2. THAT THE LINE IS THERE AT ALL. Mainland China's 40,000 km of high-speed
   railway is almost absent as relations -- about 470 train relations in the
   whole country, 21 of them G or D trains -- while its track is mapped
   end to end. `network` builds rail from the high-speed track itself:
   stations along it, the track distance between neighbouring stations, and
   the time at line speed.

What the track network does NOT know, and must not be read as knowing: which
trains stop where. It is an express network -- a ride between any two of its
stations pays one boarding and running time, no intermediate stops -- because
the long-distance service on a high-speed line is an express (a Nozomi calls
at four of the Tokaido line's sixteen stations, a G train at a handful of
twenty-odd). It is therefore optimistic by the dwell of the stops a real train
makes on the way, a few minutes each; `[rail] track_speed_factor` is fitted on
timetabled services that did stop, which absorbs part of that.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import numpy as np

# A line is high-speed track at 200 km/h and above: the UIC's own threshold for
# an upgraded line (250 for a new one). OSM's `highspeed=yes` is honoured
# whatever the `maxspeed`, as `osm.service_tier` honours it on a relation.
HS_MIN_KMH = 200.0
# Track that belongs to a high-speed line: the running lines and the loops and
# crossovers in its stations. Yards, spurs and depots do not carry passengers.
HS_SERVICES = ("", "siding", "crossover")
EXCLUDED_USAGE = ("industrial", "military", "tourism", "test")
# Running speed where a way carries no `maxspeed`. Published-figure defaults,
# not fitted. 250 km/h is the UIC minimum for a NEW high-speed line, which is
# what an untagged `highspeed=yes` way most often is; 80 km/h is the speed of
# the turnouts and platform roads of a station throat (60-80 km/h is the
# common figure for the switches that lead into one).
HS_DEFAULT_KMH = 250.0
STATION_TRACK_KMH = 80.0
# Gaps in the mapped track. OSM splits a line into thousands of ways, and two
# that should share a node sometimes end metres apart (the Tokaido Shinkansen
# breaks four times between Tokyo and Shin-Osaka); and a line's own station
# roads are often untagged. A dead end within 50 m of another piece is joined;
# two pieces are bridged through at most 3 km of other main or station track.
GAP_SNAP_KM = 0.05
BRIDGE_KM = 3.0
CONNECTOR_MAX_WAY_KM = 5.0
# A station belongs to the line when it lies within 0.8 km of its running track
# and within 1.0 km of a switch on it: a station has turnouts, a viaduct
# passing over one does not. A big Chinese terminal puts its station node at
# the building, up to 0.7 km from the tracks; tighter radii lost 杭州东, 成都东
# and 重庆西 outright.
STATION_TRACK_KM = 0.8
STATION_SWITCH_KM = 1.0
# A relation is high-speed when at least half its member track is.
PROMOTE_SHARE = 0.5
_EARTH_KM = 6371.0088
_MAXSPEED = re.compile(r"^(\d+(?:\.\d+)?)\s*(mph|km/h|kmh|kph)?$")
_NOT_MAINLINE_STATION = ("subway", "light_rail", "monorail", "funicular", "miniature", "tram")
# Bumped when what this module derives changes without a constant changing.
# 2: promotion only of untagged relations whose line speed is high-speed.
# 3: track a high-speed relation runs over is left out of the network.
# 4: ... and track any train relation runs over.
TRACK_VERSION = 4


def params() -> tuple:
    """Everything here that governs the rail parquet's content, for its key."""
    return (HS_MIN_KMH, HS_SERVICES, EXCLUDED_USAGE, HS_DEFAULT_KMH, STATION_TRACK_KMH,
            GAP_SNAP_KM, BRIDGE_KM, CONNECTOR_MAX_WAY_KM, STATION_TRACK_KM,
            STATION_SWITCH_KM, PROMOTE_SHARE, _NOT_MAINLINE_STATION, _MAXSPEED.pattern,
            TRACK_VERSION)


def parse_maxspeed(raw: str | None) -> float | None:
    """A `maxspeed` value in km/h, or None. `125 mph` is the UK's one form;
    `signals`, `none` and anything conditional say nothing usable."""
    if not raw:
        return None
    m = _MAXSPEED.match(raw.strip().lower())
    if not m:
        return None
    v = float(m.group(1))
    if m.group(2) == "mph":
        v *= 1.609344
    return v if 5.0 <= v <= 600.0 else None


def is_high_speed(tags_highspeed: str | None, vmax: float | None) -> bool:
    return tags_highspeed == "yes" or (vmax is not None and vmax >= HS_MIN_KMH)


def _hav(la1, lo1, la2, lo2):
    r1, r2 = np.radians(la1), np.radians(la2)
    a = (np.sin((r2 - r1) / 2) ** 2
         + np.cos(r1) * np.cos(r2) * np.sin(np.radians(lo2 - lo1) / 2) ** 2)
    return _EARTH_KM * 2 * np.arcsin(np.sqrt(a))


def _xyz(lat, lon):
    la, lo = np.radians(np.asarray(lat, float)), np.radians(np.asarray(lon, float))
    return np.stack([np.cos(la) * np.cos(lo), np.cos(la) * np.sin(lo), np.sin(la)],
                    axis=-1).reshape(-1, 3) * _EARTH_KM


@dataclass
class Track:
    """One extract's track, as `scan` reads it."""

    # way id -> (length km, maxspeed km/h or None, high-speed?) for every
    # `railway=rail` way: what relation_profile reads.
    ways: dict[int, tuple[float, float | None, bool]] = field(default_factory=dict)
    # High-speed running, siding and crossover ways, with their geometry.
    hs: dict[int, tuple] = field(default_factory=dict)
    # Short other main and station track, for bridging gaps and finding switches.
    conn: dict[int, tuple] = field(default_factory=dict)
    # railway=station|halt nodes that a main-line train can call at.
    stations: list[tuple] = field(default_factory=list)
    # Coordinates and names of the relation stop nodes asked for.
    nodes: dict[int, tuple] = field(default_factory=dict)


def scan(path, wanted_nodes: set[int]) -> Track:
    """One pass over an extract's nodes and ways, with locations."""
    import osmium

    out = Track()
    fp = osmium.FileProcessor(str(path), osmium.osm.NODE | osmium.osm.WAY).with_locations()
    for o in fp:
        t = o.tags
        if o.is_node():
            if o.id in wanted_nodes:
                out.nodes[o.id] = (o.location.lat, o.location.lon, t.get("name") or "")
            if (t.get("railway") in ("station", "halt") and t.get("train") != "no"
                    and t.get("station") not in _NOT_MAINLINE_STATION):
                out.stations.append((o.location.lat, o.location.lon,
                                     t.get("name") or t.get("name:en") or "",
                                     t.get("railway"), t.get("operator") or ""))
            continue
        if t.get("railway") != "rail":
            continue
        try:
            lat = np.fromiter((n.lat for n in o.nodes), float)
            lon = np.fromiter((n.lon for n in o.nodes), float)
        except osmium.InvalidLocationError:
            continue
        if len(lat) < 2:
            continue
        km = float(_hav(lat[:-1], lon[:-1], lat[1:], lon[1:]).sum())
        vmax = parse_maxspeed(t.get("maxspeed"))
        hs = is_high_speed(t.get("highspeed"), vmax)
        svc = t.get("service") or ""
        out.ways[o.id] = (km, vmax, hs)
        if svc not in HS_SERVICES:
            continue
        ids = np.fromiter((n.ref for n in o.nodes), np.int64)
        if hs and t.get("usage") not in EXCLUDED_USAGE:
            out.hs[o.id] = (ids, lat, lon, vmax, svc, t.get("name") or "",
                            t.get("operator") or "")
        elif km <= CONNECTOR_MAX_WAY_KM:
            out.conn[o.id] = (ids, lat, lon, svc)
    return out


def promotes(hs_share: float, vmax: float | None) -> bool:
    """Whether an UNTAGGED relation is a high-speed service by its track: most
    of its length high-speed, and the line speed over it -- where mapped -- a
    high-speed line's. A stopping train on a 200 km/h upgraded line has the
    first and not, on average over its route, the second."""
    return hs_share >= PROMOTE_SHARE and (vmax is None or vmax >= HS_MIN_KMH)


def relation_profile(member_ways, ways) -> tuple[float, float, float | None, float]:
    """(member km, high-speed share, harmonic-mean maxspeed, maxspeed cover).

    Over the relation's member ways the extract holds. The mean is
    length-weighted and HARMONIC -- time is length over speed, so a 50 km
    section at 100 km/h costs what 150 km at 300 does, and an arithmetic mean
    would hide it. None where no member way carries a `maxspeed`.
    """
    total = hs_km = cov_km = inv = 0.0
    for w in member_ways:
        rec = ways.get(w)
        if rec is None:
            continue
        km, vmax, hs = rec
        total += km
        if hs:
            hs_km += km
        if vmax:
            cov_km += km
            inv += km / vmax
    if total <= 0:
        return 0.0, 0.0, None, 0.0
    return total, hs_km / total, (cov_km / inv if inv > 0 else None), cov_km / total


@dataclass(frozen=True)
class Link:
    """Two neighbouring stations on high-speed track."""

    a: tuple[float, float, str]
    b: tuple[float, float, str]
    track_km: float
    line_h: float          # hours at line speed, sum of length / maxspeed
    name: str
    operator: str


def network(track: Track, covered_ways: set[int]) -> list[Link]:
    """The high-speed track no train relation runs over, as station-to-station
    links.

    `covered_ways` are the ways the extract's train relations run over, and
    they are left out: where OSM says which trains call where, the relations
    price it, and an express link laid over the same track counts the line
    twice -- a UK 125 mph main line is high-speed track by `maxspeed` and was
    given 592 km of links over the track its `long_distance` relations already
    run. A station is a mainline
    station within STATION_TRACK_KM of the running track and STATION_SWITCH_KM
    of a switch on it, the switch's own nearest one -- preferring a station of
    the track's operator, then a station over a halt.
    """
    import scipy.sparse as sp
    from scipy.sparse.csgraph import connected_components, dijkstra
    from scipy.spatial import cKDTree

    if not track.hs:
        return []
    node_of: dict[int, int] = {}
    lats: list[float] = []
    lons: list[float] = []

    def index(ids, lat, lon):
        out = np.empty(len(ids), np.int64)
        for k, nd in enumerate(ids.tolist()):
            i = node_of.get(nd)
            if i is None:
                i = node_of[nd] = len(lats)
                lats.append(lat[k]); lons.append(lon[k])
            out[k] = i
        return out

    ea, eb, ek, eh, kind = [], [], [], [], []
    node_op: dict[int, str] = {}
    node_name: dict[int, str] = {}
    for wid, (ids, lat, lon, vmax, svc, name, op) in track.hs.items():
        if wid in covered_ways:
            continue
        ix = index(ids, lat, lon)
        km = _hav(lat[:-1], lon[:-1], lat[1:], lon[1:])
        v = vmax or (HS_DEFAULT_KMH if not svc else STATION_TRACK_KMH)
        ea.append(ix[:-1]); eb.append(ix[1:]); ek.append(km); eh.append(km / v)
        kind.append(np.full(len(km), {"": 0, "siding": 1, "crossover": 2}[svc], np.int8))
        for i in ix.tolist():
            if op:
                node_op.setdefault(i, op)
            if name and not svc:
                node_name.setdefault(i, name)
    n_hs = len(lats)
    if not n_hs:
        return []
    ca, cb, ck, cx = [], [], [], []
    for _, (ids, lat, lon, svc) in track.conn.items():
        ix = index(ids, lat, lon)
        ca.append(ix[:-1]); cb.append(ix[1:])
        ck.append(_hav(lat[:-1], lon[:-1], lat[1:], lon[1:]))
        cx.append(np.full(len(ix) - 1, svc == "crossover"))
    LAT, LON = np.asarray(lats), np.asarray(lons)
    n = len(LAT)
    a, b = np.concatenate(ea), np.concatenate(eb)
    km, h, kind = np.concatenate(ek), np.concatenate(eh), np.concatenate(kind)

    def labels(a, b):
        G = sp.coo_matrix((np.ones(2 * len(a)), (np.r_[a, b], np.r_[b, a])), shape=(n, n)).tocsr()
        return G, connected_components(G, directed=False)[1]

    # 1. topology gaps: a dead end within GAP_SNAP_KM of another piece's node
    G, lab = labels(a, b)
    dead = np.flatnonzero(np.diff(G.indptr)[:n_hs] == 1)
    if len(dead):
        tree = cKDTree(_xyz(LAT[:n_hs], LON[:n_hs]))
        gx, gy, gk = [], [], []
        for u, cands in zip(dead, tree.query_ball_point(_xyz(LAT[dead], LON[dead]), r=GAP_SNAP_KM)):
            best = min(((float(_hav(LAT[u], LON[u], LAT[v], LON[v])), v)
                        for v in cands if lab[v] != lab[u]), default=None)
            if best:
                gx.append(u); gy.append(best[1]); gk.append(best[0])
        if gx:
            gk = np.asarray(gk)
            a, b = np.r_[a, gx], np.r_[b, gy]
            km, h = np.r_[km, gk], np.r_[h, gk / STATION_TRACK_KMH]
            kind = np.r_[kind, np.full(len(gk), 3, np.int8)]
    # 2. bridges through short other track between different pieces
    if ca:
        ca, cb, ck, cx = (np.concatenate(ca), np.concatenate(cb), np.concatenate(ck),
                          np.concatenate(cx))
        G, lab = labels(a, b)
        C = sp.coo_matrix((np.r_[ck, ck], (np.r_[ca, cb], np.r_[cb, ca])), shape=(n, n)).tocsr()
        touch = np.unique(np.r_[ca, cb])
        touch = touch[touch < n_hs]
        if len(touch):
            Dc, _, Sc = dijkstra(C, directed=False, indices=touch, min_only=True,
                                 return_predecessors=True, limit=BRIDGE_KM)
            sx, sy = Sc[ca], Sc[cb]
            tot = Dc[ca] + ck + Dc[cb]
            ok = (sx >= 0) & (sy >= 0) & (tot <= BRIDGE_KM)
            ok &= lab[np.maximum(sx, 0)] != lab[np.maximum(sy, 0)]
            br: dict[tuple[int, int], float] = {}
            for x, y, t in zip(sx[ok].tolist(), sy[ok].tolist(), tot[ok].tolist()):
                k = (min(x, y), max(x, y))
                br[k] = min(t, br.get(k, np.inf))
            if br:
                bk = np.fromiter(br.values(), float)
                a = np.r_[a, [k[0] for k in br]]
                b = np.r_[b, [k[1] for k in br]]
                km, h = np.r_[km, bk], np.r_[h, bk / STATION_TRACK_KMH]
                kind = np.r_[kind, np.full(len(bk), 3, np.int8)]
    else:
        ca = cb = np.zeros(0, np.int64)
        cx = np.zeros(0, bool)

    # 3. stations
    main = np.unique(np.r_[a[kind == 0], b[kind == 0]])
    if not len(main):
        return []
    main_tree = cKDTree(_xyz(LAT[main], LON[main]))
    chosen: dict[int, tuple[float, float, str]] = {}
    nc = kind != 2
    ee = np.r_[np.stack([a[nc], b[nc]], 1), np.stack([ca[~cx], cb[~cx]], 1)]
    ee = np.unique(np.sort(ee, axis=1), axis=0)
    deg = np.bincount(ee.ravel(), minlength=n)
    sw = np.flatnonzero(deg[:n_hs] >= 3)
    if len(sw) and track.stations:
        st = track.stations
        S = _xyz([s[0] for s in st], [s[1] for s in st])
        tdist, tnear = main_tree.query(S, distance_upper_bound=STATION_TRACK_KM)
        stree = cKDTree(S)
        SW = _xyz(LAT[sw], LON[sw])
        for s_i, p, cands in zip(sw.tolist(), SW, stree.query_ball_point(SW, r=STATION_SWITCH_KM)):
            op = node_op.get(s_i, "")
            best = None
            for i in cands:
                if not np.isfinite(tdist[i]):
                    continue
                sop = st[i][4]
                match = 1 if not (op and sop) else (0 if (op in sop or sop in op) else 2)
                rank = (match, 0 if st[i][3] == "station" else 1, float(np.linalg.norm(S[i] - p)))
                if best is None or rank < best[0]:
                    best = (rank, i)
            if best:
                i = best[1]
                chosen.setdefault(int(main[tnear[i]]), (st[i][0], st[i][1], st[i][2]))
    if len(chosen) < 2:
        return []

    # 4. neighbouring stations by time along the track, with its length
    src = np.asarray(sorted(chosen), np.int64)
    Gh = sp.coo_matrix((np.r_[h, h], (np.r_[a, b], np.r_[b, a])), shape=(n, n)).tocsr()
    Gh.sum_duplicates()
    D, P, SRC = dijkstra(Gh, directed=False, indices=src, min_only=True, return_predecessors=True)
    # km along each node's time-shortest path from its station
    edge_km: dict[tuple[int, int], float] = {}
    for x, y, k in zip(a.tolist(), b.tolist(), km.tolist()):
        key = (x, y) if x < y else (y, x)
        edge_km[key] = min(k, edge_km.get(key, np.inf))
    DK = np.zeros(n)
    for v in np.argsort(D, kind="stable").tolist():
        p = P[v]
        if p >= 0 and np.isfinite(D[v]):
            DK[v] = DK[p] + edge_km[(p, v) if p < v else (v, p)]
    sa, sb = SRC[a], SRC[b]
    cross = (sa >= 0) & (sb >= 0) & (sa != sb)
    best: dict[tuple[int, int], tuple[float, float, int]] = {}
    for x, y, hh, kk, u, v in zip(sa[cross].tolist(), sb[cross].tolist(), h[cross].tolist(),
                                  km[cross].tolist(), a[cross].tolist(), b[cross].tolist()):
        key = (x, y) if x < y else (y, x)
        t = D[u] + hh + D[v]
        if t < best.get(key, (np.inf,))[0]:
            best[key] = (t, DK[u] + kk + DK[v], u)
    links = []
    for (x, y), (t, kk, u) in sorted(best.items()):
        name = node_name.get(u) or node_name.get(x) or node_name.get(y) or ""
        op = node_op.get(u) or node_op.get(x) or node_op.get(y) or ""
        links.append(Link(chosen[x], chosen[y], float(kk), float(t), name, op))
    return links
